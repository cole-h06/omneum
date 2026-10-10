"""Operator-only enrollment over PostgreSQL. Raw tokens are issued once to a private file."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path
import stat
from uuid import UUID, uuid4

from .ingestion.credentials import generate
def setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"missing required setting: {name}")
    return value



def require_operator(db):
    if not db.execute("SELECT pg_has_role(current_user, 'omneum_network_operator', 'MEMBER')").fetchone()[0]:
        raise PermissionError('operator role required')


def lock_installation(db, installation):
    db.execute('SELECT pg_advisory_xact_lock(%s)',
               (int.from_bytes(installation.bytes[:8], 'big', signed=True),))


def binding(db, principal):
    row = db.execute('SELECT installation_id FROM control.ingestion_principals WHERE principal_id=%s',
                     (principal,)).fetchone()
    if row is None:
        raise ValueError('unknown contributor principal')
    lock_installation(db, row[0])
    return row[0]


def create_workspace(db):
    require_operator(db)
    with db.transaction():
        organization = db.execute('INSERT INTO control.organizations DEFAULT VALUES RETURNING id').fetchone()[0]
        workspace = db.execute('INSERT INTO control.workspaces(organization_id) VALUES (%s) RETURNING id',
                               (organization,)).fetchone()[0]
    return {'organization_id': str(organization), 'workspace_id': str(workspace)}


def private_output(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('issuance file must be an absolute path')
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise PermissionError('issuance directory must be owned by the operator and private (0700)')
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        return os.fdopen(fd, 'w', encoding='ascii')
    finally:
        os.close(directory)


def issue(db, *, principal, output, expires_days=90, enroll_workspace=None,
          consent_version=None, confirm_consent=False):
    require_operator(db)
    if type(expires_days) is not int or not 1 <= expires_days <= 365:
        raise ValueError('credential lifetime must be 1–365 days')
    if enroll_workspace is not None:
        if not confirm_consent or type(consent_version) is not str or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', consent_version):
            raise ValueError('verified explicit consent and a consent version are required')
    credential = generate(datetime.now(timezone.utc) + timedelta(days=expires_days))
    # Reserve the private output first. Never overwrite an issued credential.
    # On an uncertain commit keep the file for operator inspection, not retry.
    with private_output(output) as file, db.transaction():
        db.execute("SET LOCAL statement_timeout = '10s'")
        db.execute("SET LOCAL lock_timeout = '5s'")
        if enroll_workspace is not None:
            principal = uuid4()
            installation = uuid4()
            db.execute('INSERT INTO control.installations(id) VALUES (%s)', (installation,))
            db.execute('INSERT INTO control.ingestion_principals(principal_id,installation_id,workspace_id) VALUES (%s,%s,%s)',
                       (principal, installation, enroll_workspace))
            db.execute("INSERT INTO control.consent_grants(installation_id,scope,consent_version) VALUES (%s,'research_context_graph',%s)",
                       (installation, consent_version))
        else:
            installation = binding(db, principal)
        if not db.execute("""SELECT EXISTS (SELECT 1 FROM control.ingestion_principals p
                WHERE p.principal_id=%s AND p.enabled AND EXISTS (
                    SELECT 1 FROM control.consent_grants g WHERE g.installation_id=p.installation_id
                    AND g.scope='research_context_graph' AND g.revoked_at IS NULL))""",
                (principal,)).fetchone()[0]:
            raise PermissionError('enabled enrollment with active consent required')
        db.execute('INSERT INTO control.ingestion_credentials(id,principal_id,token_sha256,expires_at) VALUES (%s,%s,%s,%s)',
                   (credential.id, principal, credential.token_sha256, credential.expires_at))
        file.write(credential.token + '\n')
        file.flush()
        os.fsync(file.fileno())
    return {'principal_id': str(principal), 'installation_id': str(installation),
            'credential_id': str(credential.id), 'expires_at': credential.expires_at.isoformat()}


def revoke(db, *, principal=None, credential_id=None):
    require_operator(db)
    with db.transaction():
        db.execute("SET LOCAL statement_timeout = '10s'")
        db.execute("SET LOCAL lock_timeout = '5s'")
        if credential_id is not None:
            row = db.execute('SELECT principal_id FROM control.ingestion_credentials WHERE id=%s',
                             (credential_id,)).fetchone()
            if row is None:
                raise ValueError('unknown credential')
            principal = row[0]
        installation = binding(db, principal)
        if credential_id is None:
            db.execute('UPDATE control.ingestion_principals SET enabled=false WHERE principal_id=%s', (principal,))
            db.execute('UPDATE control.consent_grants SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE installation_id=%s', (installation,))
            db.execute('UPDATE control.ingestion_credentials SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE principal_id=%s', (principal,))
        else:
            db.execute('UPDATE control.ingestion_credentials SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE id=%s', (credential_id,))
    return {'principal_id': str(principal), 'credential_id': str(credential_id) if credential_id else None,
            'status': 'revoked'}


class OperatorParser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo malformed arguments that may accidentally contain secrets.
        self.exit(2, 'Invalid operator command; run --help.\n')


def main():
    parser = OperatorParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=OperatorParser)
    commands.add_parser('create-workspace')
    for name in ('enroll', 'issue'):
        command = commands.add_parser(name)
        command.add_argument('--output', required=True)
        command.add_argument('--expires-days', type=int, default=90)
        if name == 'enroll':
            command.add_argument('--workspace-id', type=UUID, required=True)
            command.add_argument('--consent-version', required=True)
            command.add_argument('--confirm-consent', action='store_true', required=True)
        else:
            command.add_argument('--principal-id', type=UUID, required=True)
    command = commands.add_parser('revoke-credential')
    command.add_argument('--credential-id', type=UUID, required=True)
    command = commands.add_parser('revoke-contributor')
    command.add_argument('--principal-id', type=UUID, required=True)
    command = commands.add_parser('prune-quotas')
    command.add_argument('--retention-days', type=int, default=2)
    args = parser.parse_args()
    try:
        import psycopg
        with psycopg.connect(setting('OMNEUM_NETWORK_OPERATOR_DSN'), autocommit=True, connect_timeout=5) as db:
            db.execute("SET statement_timeout = '10s'")
            require_operator(db)
            if args.command == 'create-workspace':
                result = create_workspace(db)
            elif args.command in ('enroll', 'issue'):
                result = issue(db, principal=getattr(args, 'principal_id', None), output=args.output,
                    expires_days=args.expires_days, enroll_workspace=getattr(args, 'workspace_id', None),
                    consent_version=getattr(args, 'consent_version', None),
                    confirm_consent=getattr(args, 'confirm_consent', False))
            elif args.command.startswith('revoke-'):
                result = revoke(db, principal=getattr(args, 'principal_id', None),
                                credential_id=getattr(args, 'credential_id', None))
            else:
                if not 1 <= args.retention_days <= 90:
                    raise ValueError('retention must be 1–90 days')
                cursor = db.execute("DELETE FROM control.network_admission_budgets WHERE window_start < clock_timestamp() - %s * interval '1 day'",
                                    (args.retention_days,))
                result = {'deleted': cursor.rowcount}
        print(json.dumps(result))
    except Exception:
        raise SystemExit('Network operator command failed; check role, consent, configuration and private output. Inspect any reserved issuance file before retrying.') from None


if __name__ == '__main__':
    main()
