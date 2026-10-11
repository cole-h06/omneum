"""Dedicated account control-plane HTTPS service; no Network evaluator access."""
import asyncio
import json
import re

from .contribution.validation import _object
from .enrollment import EnrollmentRequest, EnrollmentService, OIDCAuthenticator
from .network_api import setting, validate_database_transport, bind_host
from .transport.network import NetworkHTTPApp


class EnrollmentHTTPApp:
    def __init__(self, authenticator, service):
        self.authenticator, self.service = authenticator, service
        self.active = 0

    async def __call__(self, scope, receive, send):
        reply = NetworkHTTPApp._reply
        if scope['type'] == 'lifespan':
            while True:
                event = await receive()
                if event['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif event['type'] == 'lifespan.shutdown':
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        if scope['type'] != 'http':
            return
        if self.active >= 32:
            return await reply(send, 503, {'code': 'server_busy'})
        self.active += 1
        try:
            if scope.get('scheme') != 'https':
                return await reply(send, 400, {'code': 'https_required'})
            if scope.get('path') != '/v1/enrollment' or scope.get('query_string'):
                return await reply(send, 404, {'code': 'not_found'})
            if scope.get('method') != 'POST':
                return await reply(send, 405, {'code': 'method_not_allowed'})
            headers = scope.get('headers', [])
            if len(headers) > 64 or sum(len(k)+len(v) for k,v in headers) > 16384:
                return await reply(send, 431, {'code': 'headers_too_large'})
            def values(name):
                return [v for k,v in headers if k.lower() == name]
            auth = values(b'authorization')
            if len(auth) != 1 or not re.fullmatch(rb'Bearer [A-Za-z0-9_.-]{1,8192}', auth[0]):
                return await reply(send, 401, {'code': 'unauthorized'})
            # Browser cookie authentication and cross-origin requests are not supported.
            if values(b'origin') or values(b'cookie') or values(b'content-type') != [b'application/json'] or values(b'content-encoding'):
                return await reply(send, 415, {'code': 'unsupported_media_type'})
            identity = await NetworkHTTPApp._run_sync(self.authenticator.authenticate, auth[0][7:].decode('ascii'))
            if identity is None:
                return await reply(send, 401, {'code': 'unauthorized'})
            lengths = values(b'content-length')
            if lengths and (len(lengths) != 1 or len(lengths[0]) > 10 or not lengths[0].isdigit()):
                return await reply(send, 400, {'code': 'invalid_request'})
            if lengths and int(lengths[0]) > 4096:
                return await reply(send, 413, {'code': 'request_too_large'})
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        event = await receive()
                        if event['type'] != 'http.request':
                            return
                        body.extend(event.get('body', b''))
                        if len(body) > 4096:
                            return await reply(send, 413, {'code': 'request_too_large'})
                        if not event.get('more_body', False):
                            break
            except TimeoutError:
                return await reply(send, 408, {'code': 'request_timeout'})
            if lengths and len(body) != int(lengths[0]):
                return await reply(send, 400, {'code': 'invalid_request'})
            try:
                request = EnrollmentRequest.model_validate(json.loads(body, object_pairs_hook=_object))
                request.installation()
            except Exception:
                return await reply(send, 400, {'code': 'invalid_request'})
            try:
                result = await NetworkHTTPApp._run_sync(self.service.handle, identity, request)
            except PermissionError:
                return await reply(send, 403, {'code': 'forbidden'})
            except FileExistsError:
                return await reply(send, 409, {'code': 'already_enrolled'})
            except OverflowError:
                return await reply(send, 429, {'code': 'rate_limited'})
            except Exception:
                return await reply(send, 503, {'code': 'enrollment_unavailable'})
            return await reply(send, 200, result)
        finally:
            self.active -= 1


def create_app():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    dsn = setting('OMNEUM_ENROLLMENT_DATABASE_DSN')
    config = conninfo_to_dict(dsn)
    validate_database_transport(config)
    if config.get('user') != 'omneum_enrollment':
        raise ValueError('dedicated enrollment identity required')
    def connection():
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    with connection() as db:
        from .network_api import validate_database_role
        validate_database_role(db, expected_role='omneum_enrollment')
        db.execute('SELECT 1 FROM control.account_installations LIMIT 0')
        if db.execute("""SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='network' AND c.relkind IN ('r','v','m','p')
            AND has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER'))""").fetchone()[0]:
            raise ValueError('enrollment must not access Network report tables')
    version = setting('OMNEUM_NETWORK_CONSENT_VERSION')
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', version):
        raise ValueError('invalid consent version')
    return EnrollmentHTTPApp(OIDCAuthenticator(issuer=setting('OMNEUM_ACCOUNT_ISSUER'),
        audience=setting('OMNEUM_ACCOUNT_AUDIENCE'), jwks_path=setting('OMNEUM_ACCOUNT_JWKS')),
        EnrollmentService(connection, version))


def main():
    try:
        import uvicorn
        uvicorn.run(create_app(), host=bind_host(), port=8444, workers=1,
            proxy_headers=False, access_log=False,
            ssl_certfile=setting('OMNEUM_NETWORK_TLS_CERT'),
            ssl_keyfile=setting('OMNEUM_NETWORK_TLS_KEY'), timeout_graceful_shutdown=30)
    except Exception:
        raise SystemExit('Enrollment startup failed; check server configuration') from None


if __name__ == '__main__':
    main()
