"""Server-only narrow ASGI boundary; no MCP tools or client-selected databases.

Deploy with an ASGI server providing TLS (or a trusted TLS termination layer
that sets scheme securely). Forwarded headers are never interpreted here.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from typing import Callable
from uuid import UUID

from ..config import DeploymentState
from ..contribution.validation import _object, MAX_BODY_BYTES
from ..ingestion.service import Authenticator, IngestionService, authenticate
from ..models import EvaluateVOPRFRequest
from ..oprf import VOPRFClient
from ..tools.evaluate_voprf import EvaluationService


class NetworkHTTPApp:
    """Bounded adapters around the existing evaluation and ingestion cores.

    rate_limiter is a server-owned synchronous admission policy receiving an
    authenticated principal and route. It must enforce per-principal quotas;
    errors and non-True results deny admission. Edge/IP limits remain necessary.
    Each ingestion call uses the IngestionService's own authenticator as well.
    Pass ingestion.authenticator as authenticator so admission and persistence
    resolve credentials through the same authority.
    """
    def __init__(self, *, network_state: DeploymentState, local_public_key: bytes,
                 authenticator: Authenticator, ingestion: IngestionService,
                 rate_limiter: Callable[[UUID, str], bool]):
        VOPRFClient(local_public_key)
        VOPRFClient(network_state.voprf_server.public_key)
        if network_state.voprf_server.public_key == local_public_key:
            raise ValueError("Network VOPRF key must be distinct from local key")
        if authenticator is not ingestion.authenticator:
            raise ValueError("HTTP admission and ingestion must share one credential authority")
        if network_state.voprf_key_version not in ingestion.allowed_key_versions:
            raise ValueError("Network VOPRF key version must be accepted by ingestion")
        if not callable(rate_limiter):
            raise TypeError("server-owned rate limiter is required")
        self._evaluation = EvaluationService(network_state)
        self._ingestion = ingestion
        self._authenticator = authenticator
        self._rate_limiter = rate_limiter
        self._active = 0
        self._capacity = 64

    def close(self):
        self._evaluation.close()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            while True:
                event = await receive()
                if event['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif event['type'] == 'lifespan.shutdown':
                    await asyncio.to_thread(self.close)
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        if scope['type'] != 'http':
            return
        if self._active >= self._capacity:
            await self._reply(send, 503, {'code': 'server_busy'})
            return
        self._active += 1
        try:
            await self._handle(scope, receive, send)
        finally:
            self._active -= 1

    async def _handle(self, scope, receive, send):
        async def reject(status, code):
            await self._reply(send, status, {'code': code})
        if scope.get('scheme') != 'https':
            return await reject(400, 'https_required')
        path = scope.get('path')
        if path not in ('/v1/voprf', '/v1/contributions') or scope.get('query_string'):
            return await reject(404, 'not_found')
        if scope.get('method') != 'POST':
            return await reject(405, 'method_not_allowed')
        headers = scope.get('headers', [])
        if len(headers) > 64 or sum(len(k) + len(v) for k, v in headers) > 16384:
            return await reject(431, 'headers_too_large')
        def values(name):
            return [v for k, v in headers if k.lower() == name]
        authorizations = values(b'authorization')
        if len(authorizations) != 1:
            return await reject(401, 'unauthorized')
        try:
            authorization = authorizations[0].decode('ascii')
        except UnicodeError:
            return await reject(401, 'unauthorized')
        principal = await self._run_sync(authenticate, self._authenticator, authorization)
        if principal is None:
            return await reject(401, 'unauthorized')
        try:
            allowed = await self._run_sync(self._rate_limiter, principal, path) is True
        except Exception:
            allowed = False
        if not allowed:
            return await reject(429, 'rate_limited')
        if values(b'content-type') != [b'application/json'] or values(b'content-encoding'):
            return await reject(415, 'unsupported_media_type')
        maximum = 4096 if path == '/v1/voprf' else MAX_BODY_BYTES
        lengths = values(b'content-length')
        if lengths and (len(lengths) != 1 or not lengths[0].isdigit()
                        or len(lengths[0]) > 10):
            return await reject(400, 'invalid_request')
        if lengths and int(lengths[0]) > maximum:
            return await reject(413, 'request_too_large')
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    event = await receive()
                    if event['type'] == 'http.disconnect':
                        return
                    if event['type'] != 'http.request':
                        return await reject(400, 'invalid_request')
                    chunk = event.get('body', b'')
                    if len(body) + len(chunk) > maximum:
                        return await reject(413, 'request_too_large')
                    body.extend(chunk)
                    if not event.get('more_body', False):
                        break
        except TimeoutError:
            return await reject(408, 'request_timeout')
        if lengths and len(body) != int(lengths[0]):
            return await reject(400, 'invalid_request')
        if path == '/v1/contributions':
            try:
                response = await self._run_sync(self._ingestion.handle,
                                               authorization=authorization, body=bytes(body))
            except Exception:
                return await reject(503, 'ingestion_unavailable')
            return await self._reply(send, response.status, asdict(response))
        try:
            request = EvaluateVOPRFRequest.model_validate(
                json.loads(body, object_pairs_hook=_object))
        except Exception:
            return await reject(400, 'invalid_request')
        try:
            result = await self._evaluation.evaluate(request)
        except Exception:
            return await reject(503, 'evaluation_unavailable')
        status = 200
        if result.isError:
            code = result.structuredContent['omneum_code']
            status = 503 if code in ('server_busy', 'internal_error') else 400
            if code == 'request_timeout':
                status = 504
        await self._reply(send, status, result.structuredContent)

    @staticmethod
    async def _run_sync(function, *args, **kwargs):
        # Authentication, quota stores and PostgreSQL may block. Keep the active
        # admission slot until the worker finishes, even if ASGI cancels a call.
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            # Retrieve worker exceptions without exposing them during cancellation.
            if not task.cancelled():
                task.exception()
            raise

    @staticmethod
    async def _reply(send, status, result):
        body = json.dumps(result, default=str, allow_nan=False, separators=(',', ':')).encode()
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json'), (b'cache-control', b'no-store'),
            (b'content-length', str(len(body)).encode()),
        ]})
        await send({'type': 'http.response.body', 'body': body})
