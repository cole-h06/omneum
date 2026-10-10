"""Run inside the disposable Compose API container; no production configuration."""
import json
import os
from pathlib import Path
import ssl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from omneum.base64url import decode_unpadded, encode_unpadded
from omneum.oprf import VOPRFClient, VOPRFEvaluation

root = Path('/config')
assert (root / 'ready').read_text() == 'disposable local integration only\n'
context = ssl.create_default_context(cafile=str(root / 'tls.crt'))
credential = Path('/client/api-token').read_text().strip()
url = os.environ.get('OMNEUM_SMOKE_URL', 'https://localhost:8443')


def post(path, value, token=credential):
    request = Request(url + path, data=json.dumps(value).encode(),
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    try:
        response = urlopen(request, context=context, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.code, json.loads(response.read())


assert post('/v1/voprf', {}, 'invalid-test-token')[0] == 401
client = VOPRFClient(decode_unpadded((root / 'public-key').read_text(), expected_length=32))


def token(data):
    blind = client.blind(data)
    request = dict(protocol_version='v1', deployment_id=(root / 'deployment-id').read_text(),
                   voprf_key_version=1, voprf_mode='voprf', voprf_ciphersuite='ristretto255-SHA512',
                   linkage_encoding_version=1, blinded_element=encode_unpadded(blind.blinded_element, expected_length=32))
    status, response = post('/v1/voprf', request)
    assert status == 200, response
    evaluation = VOPRFEvaluation(decode_unpadded(response['evaluated_element'], expected_length=32),
                                 decode_unpadded(response['proof'], expected_length=64))
    return encode_unpadded(client.finalize(input_data=data, client_state=blind.client_state,
                                          evaluation=evaluation), expected_length=64)


source, claim = token(b'disposable-source'), token(b'disposable-claim')
payload = dict(idempotency_key='compose-smoke-1', evaluator_version='v2', estimator_version='v4',
    sources=[dict(source_id='s1', source_token=source, source_kind='url', key_version=1)],
    claims=[dict(claim_id='c1', claim_token=claim, key_version=1)],
    observations=[dict(source_id='s1', claim_id='c1')],
    source_scores=[], claim_scores=[], dependencies=[])
status, receipt = post('/v1/contributions', payload)
assert status == 200 and receipt['code'] == 'accepted', receipt
assert post('/v1/contributions', payload) == (status, receipt)
with psycopg.connect((root / 'database-dsn').read_text(), autocommit=True) as db:
    assert db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()[0]
    assert db.execute('SELECT count(*) FROM control.ingestion_receipts WHERE id=%s',
                      (receipt['receipt_id'],)).fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM network.evaluation_runs WHERE id=%s',
                      (receipt['evaluation_run_id'],)).fetchone()[0] == 1
print('PASS: HTTPS startup, auth rejection, VOPRF proof, ingestion, idempotency and PostgreSQL persistence')
