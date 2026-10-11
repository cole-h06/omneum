"""Explicit live acceptance: synthetic installation/reports, never existing history.

Run hosted checks on the VM as root; run local-outage on an installed MCP client.
No private credential is accepted on the command line or retained after testing.
"""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from .network_deploy import require
from .contribution.config import _NoRedirect


def post(endpoint, body, token):
    try:
        response = build_opener(ProxyHandler({}), _NoRedirect()).open(Request(endpoint,
            data=json.dumps(body).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}), timeout=20)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(16385)
        require(len(raw) <= 16384, 'acceptance response too large')
        return response.code, json.loads(raw)


async def proof_payload(c, credential, key):
    from .base64url import encode_unpadded
    from .contribution.network import HTTPSNetworkEvaluator
    # Exact domain separation comes from the existing contribution pipeline.
    from .contribution.linkage import NetworkLinkageConfig, NetworkLinkageClient
    evaluator = HTTPSNetworkEvaluator('https://' + c['domain'] + '/v1/voprf', credential,
                                    c['deployment_id'], c['network_key_version'])
    namespace = uuid4().hex
    config = NetworkLinkageConfig(c['network_key_version'], key)
    client = NetworkLinkageClient(config)
    values = (client.blind_source('web_publisher', 'https://' + namespace + '.acceptance.invalid'),
              client.blind_claim('acceptance', namespace, 'synthetic', True))
    tokens = []
    for blind in values:
        result = await evaluator.evaluate(key_version=c['network_key_version'], blinded_element=blind.blinded_element)
        tokens.append(encode_unpadded(client.finalize(blind, result).value, expected_length=64))
    return dict(idempotency_key='acceptance-' + namespace, evaluator_version='v2', estimator_version='v4',
        sources=[dict(source_id='s1', source_token=tokens[0], source_kind='web_publisher', key_version=c['network_key_version'])],
        claims=[dict(claim_id='c1', claim_token=tokens[1], key_version=c['network_key_version'])],
        observations=[dict(source_id='s1', claim_id='c1')], source_scores=[], claim_scores=[], dependencies=[])


def hosted(c, admin_file):
    import psycopg
    from .network_deploy import preflight, database_settings
    from .base64url import decode_unpadded
    from .enrollment import OIDCAuthenticator
    from .onboarding import account_token, OnboardingPins
    preflight(c)
    pins = OnboardingPins('https://' + c['domain'] + '/v1/enrollment', c['oidc_device_endpoint'],
        c['oidc_token_endpoint'], c['oidc_verification_uri'], c['oidc_client_id'],
        'omneum:enroll', c['consent_url'], c['consent_version'], c['oidc_audience'])
    print('This creates one synthetic installation and retained synthetic report in the live Network.')
    print('Consent terms: ' + c['consent_url'])
    require(input('Type research_context_graph to grant consent for this test: ') == 'research_context_graph', 'explicit test consent required')
    account = account_token(pins, print)
    require(OIDCAuthenticator(issuer=c['oidc_issuer'], audience=c['oidc_audience'],
        jwks_path=c['oidc_jwks_file']).authenticate(account) is not None, 'real provider-issued token validation failed')
    installation = str(uuid4())
    def enrollment(action, **extra):
        return post(pins.enrollment_endpoint, dict(action=action, installation_id=installation, **extra), account)
    contribution = 'https://' + c['domain'] + '/v1/contributions'
    issued = False
    withdrawn = False
    try:
        require(enrollment('enroll', consent=False, consent_version=c['consent_version'])[0] == 403, 'consent bypass accepted')
        status, response = enrollment('enroll', consent=True, consent_version=c['consent_version'])
        require(status == 200 and response['consent_active'], 'self-service consent enrollment failed')
        issued = True
        credential = response['api_key']
        require(enrollment('enroll', consent=True, consent_version=c['consent_version'])[0] == 409, 'duplicate enrollment accepted')
        body = asyncio.run(proof_payload(c, credential, decode_unpadded(c['network_public_key'], expected_length=32)))
        status, receipt = post(contribution, body, credential)
        require(status == 200 and receipt.get('code') == 'accepted', 'contribution failed')
        require(post(contribution, body, credential) == (status, receipt), 'idempotency replay failed')
        with psycopg.connect(database_settings(c, admin_file), autocommit=True) as db:
            require(db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone() == (True,), 'verification DB must use TLS')
            require(db.execute('SELECT count(*) FROM control.ingestion_receipts WHERE id=%s AND installation_id=%s',
                (UUID(receipt['receipt_id']), UUID(installation))).fetchone() == (1,), 'receipt persistence/installation binding failed')
            require(db.execute('SELECT count(*) FROM network.evaluation_runs WHERE id=%s',
                (UUID(receipt['evaluation_run_id']),)).fetchone() == (1,), 'evaluation persistence failed')
        for action in ('renew', 'rotate'):
            status, response = enrollment(action)
            require(status == 200, action + ' failed')
            require(post(contribution, body, credential)[0] == 401, action + ' did not revoke previous credential')
            credential = response['api_key']
            require(post(contribution, body, credential) == (200, receipt), 'credential lifecycle lost replay binding')
        require(enrollment('revoke')[0] == 200, 'revocation failed')
        require(post(contribution, body, credential)[0] == 401, 'revoked credential accepted')
        status, response = enrollment('renew')
        require(status == 200, 'account-authenticated renewal after revocation failed')
        credential = response['api_key']
        require(enrollment('withdraw')[0] == 200, 'withdrawal failed')
        withdrawn = True
        require(post(contribution, body, credential)[0] == 401, 'withdrawn consent accepted')
        require(enrollment('renew')[0] == 403, 'withdrawn installation renewed')
        print('PASS: configured provider token, explicit consent, VOPRF proof, persistence, replay, renewal, rotation, revocation, withdrawal')
    finally:
        if issued and not withdrawn:
            # Never delete retained reports or revoke unrelated account installations.
            cleanup = enrollment('withdraw')[0]
            require(cleanup == 200, 'test installation cleanup failed; administratively withdraw the synthetic installation')


async def local_outage():
    from . import OmneumClientConfig, open_stdio_client, Source, Claim, Observation
    from .contribution.network import OmneumNetwork
    from .contributor import evaluate, AssertionInput
    from .dependency import DependencyEstimatorConfig
    from .onboarding import stored_credential
    from .local_persistence import LocalPersistenceConfig
    from mcp import StdioServerParameters
    import tempfile
    # Deliberate caller-side transport failure, not a production service outage.
    # Exercise the real installed MCP and SDK recovery path with private test SQLite.
    class Unavailable:
        async def evaluate(self, **kwargs):
            raise TimeoutError('acceptance simulated Network timeout')
    credential = stored_credential()
    require(credential, 'local-outage requires an enrolled local installation')
    config = replace(OmneumNetwork.pseudonymous(api_key=credential), evaluator=Unavailable())
    value = AssertionInput(observation_id=uuid4().hex, source_kind='web_publisher',
        source_identifier='https://' + uuid4().hex + '.acceptance.invalid',
        entity_namespace='acceptance', entity=uuid4().hex, attribute='synthetic', value=True,
        observed_at=datetime.now(timezone.utc))
    from .contributor import local_environment
    with tempfile.TemporaryDirectory(prefix='omneum-acceptance-') as directory:
        Path(directory).chmod(0o700)
        from .storage import SQLiteStorage
        persistence = LocalPersistenceConfig(storage=SQLiteStorage(Path(directory) / 'graph.sqlite3'))
        async with open_stdio_client(OmneumClientConfig.from_local_deployment(),
            StdioServerParameters(command='omneum-server', env=local_environment()),
            network_contribution=config, local_persistence=persistence) as client:
            estimator = DependencyEstimatorConfig(upstream_weight=0.25, citation_weight=0.2,
                assertion_lineage_weight=0.2, ownership_weight=0.1, temporal_weight=0.1,
                graph_weight=0.15, temporal_window_seconds=7200.0, retrieval_weight=0.1,
                dependency_cluster_threshold=0.5)
            result = await evaluate(client, [value], estimator, True)
            require(result['network_contribution'] == 'failed_or_uncertain' and result['claim_support'],
                    'Network outage interrupted local evaluation')
        import sqlite3
        with sqlite3.connect(Path(directory) / 'graph.sqlite3') as db:
            require(db.execute('SELECT count(*) FROM observations').fetchone()[0] == 1,
                    'local evaluation was not persisted before contribution failure')
    print('PASS: installed MCP local evaluation and private SQLite persistence during simulated Network unavailability')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('hosted', 'local-outage'))
    parser.add_argument('--config', default='/etc/omneum-network/production.json')
    parser.add_argument('--admin-dsn-file')
    parser.add_argument('--confirm-live', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'hosted':
            import os
            from .network_deploy import load
            require(os.geteuid() == 0 and args.confirm_live and args.admin_dsn_file,
                    'hosted requires root, --confirm-live and private --admin-dsn-file')
            hosted(load(args.config), args.admin_dsn_file)
        else:
            asyncio.run(local_outage())
    except Exception:
        parser.exit(1, 'FAIL: acceptance incomplete; no production-readiness claim. Inspect configuration and sanitized service logs.\n')


if __name__ == '__main__':
    main()
