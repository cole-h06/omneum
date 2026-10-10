"""Disposable Compose operator enrollment; never part of the API process."""
import json
from pathlib import Path
import psycopg
from omneum.network_api import setting
from omneum.network_operator import create_workspace, issue
from uuid import UUID

root = Path('/client')
assert Path('/config/ready').read_text() == 'disposable local integration only\n'
if (root / 'enrollment.json').exists():
    raise SystemExit(0)
if (root / 'api-token').exists():
    raise SystemExit('Incomplete disposable enrollment; inspect or remove the test volumes')
dsn = setting('OMNEUM_NETWORK_OPERATOR_DSN')
from psycopg.conninfo import conninfo_to_dict
parameters = conninfo_to_dict(dsn)
assert parameters.get('dbname') == 'omneum_network_test' and parameters.get('host') == 'postgres'
with psycopg.connect(dsn, autocommit=True) as db:
    workspace = create_workspace(db)
    metadata = issue(db, principal=None, output=root / 'api-token',
                     enroll_workspace=UUID(workspace['workspace_id']),
                     consent_version='disposable-test-1', confirm_consent=True)
(root / 'enrollment.json').write_text(json.dumps(metadata))
