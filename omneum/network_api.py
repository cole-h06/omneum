"""Network-only bootstrap. The MCP stdio installation does not import this module."""
from __future__ import annotations

import os
import ipaddress
import time
from pathlib import Path

from .base64url import decode_unpadded
from .config import DeploymentConfig, DeploymentState
from .daemon import DaemonServerContext, DaemonUnavailableError
from .ingestion.service import IngestionService
from .ingestion.credentials import CredentialAuthenticator
from .oprf import VOPRFServer
from .transport.network import NetworkHTTPApp


def validate_database_transport(config):
    """Local test sockets/loopback are allowed; remote credentials require verified TLS."""
    hosts = config.get('host', os.environ.get('PGHOST', '')).split(',')
    addresses = config.get('hostaddr', os.environ.get('PGHOSTADDR', '')).split(',')
    # libpq service files can override host/TLS defaults. Require the TLS mode
    # in the DSN itself when connection details come from a service file.
    if (config.get('service') or os.environ.get('PGSERVICE')) and config.get('sslmode') != 'verify-full':
        raise ValueError('Network database services require explicit sslmode=verify-full')
    def local(value):
        if not value or value.startswith('/') or value == 'localhost':
            return True
        try:
            return ipaddress.ip_address(value).is_loopback
        except ValueError:
            return False
    if (not all(local(value) for value in (*hosts, *addresses))
            and config.get('sslmode', os.environ.get('PGSSLMODE')) != 'verify-full'):
        raise ValueError('remote Network database requires sslmode=verify-full')


def validate_database_role(db):
    """A role name alone does not prove least privilege after administrator changes."""
    if db.execute('SELECT current_user').fetchone()[0] != 'omneum_ingestion':
        raise ValueError('dedicated ingestion role required')
    unsafe = db.execute('''SELECT EXISTS (
        SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user, r.oid, 'MEMBER')
          AND (r.rolname <> current_user OR r.rolsuper OR r.rolcreaterole
               OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls)
    ) OR EXISTS (
        SELECT 1 FROM pg_namespace n WHERE n.nspname IN ('control', 'network', 'public')
          AND pg_has_role(current_user, n.nspowner, 'MEMBER')
    ) OR EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('control', 'network')
          AND pg_has_role(current_user, c.relowner, 'MEMBER')
    )''').fetchone()[0]
    if unsafe:
        raise ValueError('Network database role has unsafe privileges or ownership')


def setting(name: str) -> str:
    """Accept an environment value or a mounted file, never both."""
    value, filename = os.environ.get(name), os.environ.get(name + "_FILE")
    if (value is None) == (filename is None):
        raise ValueError(f"configure exactly one of {name} and {name}_FILE")
    return Path(filename).read_text().strip() if filename else value


class MinuteQuota:
    """Atomic per-principal budgets shared across replicas and credential rotations."""
    def __init__(self, maximum: int, *, connection_factory):
        if not 1 <= maximum <= 100_000:
            raise ValueError("Network requests per minute must be 1–100000")
        self._maximum = maximum
        self._connections = connection_factory

    def __call__(self, principal, route) -> bool:
        try:
            with self._connections() as db:
                db.execute("SET statement_timeout = '5s'")
                row = db.execute("""INSERT INTO control.network_admission_budgets
                    (principal_id, window_start, requests)
                    VALUES (%s, date_trunc('minute', clock_timestamp()), 1)
                    ON CONFLICT (principal_id, window_start) DO UPDATE
                        SET requests = control.network_admission_budgets.requests + 1
                        WHERE control.network_admission_budgets.requests < %s
                    RETURNING requests""", (principal, self._maximum)).fetchone()
            return row is not None
        except Exception:
            return False


def create_app() -> NetworkHTTPApp:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    config = DeploymentConfig(
        deployment_id=setting("OMNEUM_NETWORK_DEPLOYMENT_ID"),
        voprf_key_version=int(setting("OMNEUM_NETWORK_KEY_VERSION")),
        voprf_public_key=decode_unpadded(setting("OMNEUM_NETWORK_PUBLIC_KEY"), expected_length=32),
        daemon_socket=Path(os.environ.get("OMNEUM_DAEMON_SOCKET", "/run/omneum/eval.sock")),
        daemon_uid=int(os.environ.get("OMNEUM_DAEMON_UID", "10002")),
    )
    dsn = setting("OMNEUM_NETWORK_DATABASE_DSN")
    database_config = conninfo_to_dict(dsn)
    if database_config.get("user") != "omneum_ingestion":
        raise ValueError("Network database must use the omneum_ingestion role")
    validate_database_transport(database_config)

    def connection():
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5)

    # Fail startup on incorrect privileges or incomplete migrations.
    with connection() as db:
        validate_database_role(db)
        if not db.execute("SELECT to_regclass('network.reported_sources') IS NOT NULL").fetchone()[0]:
            raise ValueError("Network migrations are incomplete")
        db.execute("SELECT 1 FROM control.ingestion_principals LIMIT 0")
    with connection() as db:
        db.execute("SELECT 1 FROM control.ingestion_credentials LIMIT 0")
        db.execute("SELECT 1 FROM control.network_admission_budgets LIMIT 0")
    auth = CredentialAuthenticator(connection)
    context = DaemonServerContext(config.daemon_socket, config.daemon_uid,
                                  config.voprf_public_key)
    state = DeploymentState(config.deployment_id, config.voprf_key_version, "network",
                            VOPRFServer(context))
    ingestion = IngestionService(authenticator=auth, connection_factory=connection,
                                allowed_key_versions=frozenset({config.voprf_key_version}))
    return NetworkHTTPApp(
        network_state=state,
        local_public_key=decode_unpadded(setting("OMNEUM_LOCAL_PUBLIC_KEY"), expected_length=32),
        authenticator=auth, ingestion=ingestion,
        rate_limiter=MinuteQuota(int(os.environ.get("OMNEUM_NETWORK_REQUESTS_PER_MINUTE", "600")),
                                connection_factory=connection),
    )


def main():
    import uvicorn
    app = None
    try:
        cert, key = setting("OMNEUM_NETWORK_TLS_CERT"), setting("OMNEUM_NETWORK_TLS_KEY")
        # Kubernetes starts both containers together. Wait only for daemon
        # availability; a mismatched pin or bad database configuration is fatal.
        deadline = time.monotonic() + 30
        while True:
            try:
                app = create_app()
                break
            except DaemonUnavailableError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        uvicorn.run(app, host="0.0.0.0", port=8443, workers=1, proxy_headers=False,
                    ssl_certfile=cert, ssl_keyfile=key, access_log=False,
                    timeout_graceful_shutdown=30)
    except Exception:
        # Configuration exceptions can contain passwords or private file contents.
        raise SystemExit("Network API startup failed; check configuration and dependencies") from None
    finally:
        if app is not None:
            app.close()


if __name__ == "__main__":
    main()
