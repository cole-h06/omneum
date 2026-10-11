"""Disposable Linux VM deployment integration, extending the security harnesses.

Requires vm.Dockerfile, read-only /repo, --network none, no production volumes.
Provider tokens are deliberately synthetic. This cannot establish Auth0 compatibility.
"""
import builtins
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import threading
import time

assert os.geteuid() == 0 and Path('/.dockerenv').exists() and os.environ.get('OMNEUM_VM_DISPOSABLE') == '1'
sys.path.insert(0, '/repo')
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import jwt
import uvicorn
from omneum import network_deploy as deploy, network_acceptance as acceptance
from omneum import onboarding
from omneum.contribution import network
from omneum.base64url import encode_unpadded
from omneum.transport.network import NetworkHTTPApp


def run(*command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)


def write(path, value, mode=0o600):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(value if isinstance(value, bytes) else value.encode())
    p.chmod(mode)
    return p


root = Path('/etc/omneum-network')
root.mkdir(mode=0o700)
secrets = root / 'secrets'
secrets.mkdir(mode=0o700)
run('systemd-sysusers', '/repo/deploy/network/vm/sysusers.conf')
api, enrollment, crypto = deploy.identities()
write('/etc/hosts', Path('/etc/hosts').read_text() + '\n127.0.0.1 network.fixture-audit.net db.fixture-audit.net identity.fixture-audit.net\n', 0o644)

# A disposable root CA signs the actual DB, backend, ingress and mock IdP cert.
private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Omneum disposable deployment CA')])
now = datetime.now(timezone.utc)
ca = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).add_extension(x509.SubjectKeyIdentifier.from_public_key(private.public_key()),False).add_extension(x509.KeyUsage(True,False,False,False,False,True,True,None,None),True).sign(private, hashes.SHA256())
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
leaf = x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'network.fixture-audit.net')])).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=False,path_length=None),True).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(private.public_key()),False).add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False).add_extension(x509.KeyUsage(True,False,True,False,False,False,False,None,None),True).add_extension(x509.SubjectAlternativeName([x509.DNSName(host) for host in ('network.fixture-audit.net','db.fixture-audit.net','identity.fixture-audit.net')]), critical=False).sign(private, hashes.SHA256())
pem = leaf.public_bytes(serialization.Encoding.PEM)
ca_pem = ca.public_bytes(serialization.Encoding.PEM)
secret = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
write(secrets/'tls.crt', pem+ca_pem)
write(secrets/'tls.key', secret)
write(secrets/'database-ca.pem', ca_pem)
write('/usr/local/share/ca-certificates/omneum-disposable.crt', ca_pem, 0o644)
run('update-ca-certificates')
pg = pwd.getpwnam('postgres')
pgdata = Path('/var/lib/postgresql/audit')
pgdata.mkdir(mode=0o700)
os.chown(pgdata, pg.pw_uid, pg.pw_gid)
pgbin = next(Path('/usr/lib/postgresql').glob('*/bin'))
run('runuser','-u','postgres','--',str(pgbin/'initdb'),'-D',str(pgdata),'-A','trust','--encoding=UTF8')
for file, contents in (('tls.crt', pem),('tls.key',secret)):
    target = write(pgdata/file, contents)
    os.chown(target, pg.pw_uid, pg.pw_gid)
with (pgdata/'postgresql.conf').open('a') as stream:
    stream.write("\nlisten_addresses='127.0.0.1'\nport=25060\nssl=on\nssl_cert_file='tls.crt'\nssl_key_file='tls.key'\npassword_encryption='scram-sha-256'\n")
# Admin only over Unix socket; TCP runtime roles must authenticate with SCRAM/TLS.
write(pgdata/'pg_hba.conf','local all postgres trust\nhostssl all all 127.0.0.1/32 scram-sha-256\n')
os.chown(pgdata/'pg_hba.conf', pg.pw_uid, pg.pw_gid)
run('runuser','-u','postgres','--',str(pgbin/'pg_ctl'),'-D',str(pgdata),'-l',str(pgdata/'server.log'),'-w','start')
run('runuser','-u','postgres','--',str(pgbin/'psql'),'-p','25060','-X','-v','ON_ERROR_STOP=1','-c',"ALTER USER postgres PASSWORD 'disposable-admin';")
run('runuser','-u','postgres','--',str(pgbin/'createdb'),'-p','25060','omneum_network_test')

deploy.KEY_DIR.mkdir(mode=0o700)
os.chown(deploy.KEY_DIR, crypto.pw_uid, crypto.pw_gid)
deploy.SOCKET.parent.mkdir(mode=0o750)
os.chown(deploy.SOCKET.parent, crypto.pw_uid, api.pw_gid)
public_hex = run('runuser','-u',crypto.pw_name,'--','/usr/local/bin/omneumd','provision','--key-dir',str(deploy.KEY_DIR)).stdout.strip()
local_dir = Path('/var/lib/omneum-disposable-local')
local_dir.mkdir(mode=0o700)
os.chown(local_dir, crypto.pw_uid, crypto.pw_gid)
local_hex = run('runuser','-u',crypto.pw_name,'--','/usr/local/bin/omneumd','provision','--key-dir',str(local_dir)).stdout.strip()
idp_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(idp_key.public_key()))
jwk.update(kid='disposable-key',use='sig',alg='RS256')
write(secrets/'jwks.json',json.dumps({'keys':[jwk]}))
c = dict(domain='network.fixture-audit.net', deployment_id='urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741',network_key_version=1,
    network_public_key=encode_unpadded(bytes.fromhex(public_hex),expected_length=32),local_public_key=encode_unpadded(bytes.fromhex(local_hex),expected_length=32),
    database_host='db.fixture-audit.net',database_port=25060,database_name='omneum_network_test', database_ca=str(secrets/'database-ca.pem'),
    ingestion_dsn_file=str(secrets/'ingestion.dsn'),enrollment_dsn_file=str(secrets/'enrollment.dsn'),tls_certificate=str(secrets/'tls.crt'),tls_private_key=str(secrets/'tls.key'),
    oidc_issuer='https://identity.fixture-audit.net/',oidc_audience='omneum-enrollment',oidc_jwks_uri='https://identity.fixture-audit.net/jwks',oidc_jwks_file=str(secrets/'jwks.json'),
    oidc_device_endpoint='https://identity.fixture-audit.net/device',oidc_token_endpoint='https://identity.fixture-audit.net/token',oidc_verification_uri='https://identity.fixture-audit.net/activate',
    oidc_client_id='disposable-public-client',consent_url='https://network.fixture-audit.net/consent',consent_version='disposable-v1')
deploy.validate_config(c)
deploy.generate_dsns(c)
write(root/'admin.dsn',f"host={c['database_host']} port=25060 dbname=omneum_network_test user=postgres password=disposable-admin sslmode=verify-full")
# Fail closed before reading symlinked, publicly readable or foreign-owned DSNs.
link=secrets/'unsafe.dsn'
link.symlink_to(c['ingestion_dsn_file'])
try: deploy.private_read(link)
except ValueError: pass
else: raise AssertionError('symlinked DSN accepted')
link.unlink()
target=Path(c['enrollment_dsn_file'])
for mode,owner in ((0o644,0),(0o600,enrollment.pw_uid)):
    target.chmod(mode)
    os.chown(target,owner,0)
    try: deploy.private_read(target)
    except ValueError: pass
    else: raise AssertionError('unsafe DSN accepted')
target.chmod(0o600)
os.chown(target,0,0)
print('PASS: secret generation and symlink/mode/ownership rejection')
write(root/'production.json',json.dumps(c))
copy = Path('/opt/audit-migrations')
copy.mkdir()
for migration in deploy.MIGRATIONS:
    shutil.copyfile(Path('/repo/migrations')/migration,copy/migration)
deploy.migrate(c,str(root/'admin.dsn'),copy)
deploy.migrate(c,str(root/'admin.dsn'),copy)
for field,role in (('ingestion_dsn_file','omneum_ingestion'),('enrollment_dsn_file','omneum_enrollment')):
    deploy.check_database(c,c[field],role)
import psycopg
with psycopg.connect(deploy.database_settings(c,root/'admin.dsn'),autocommit=True) as db:
    db.execute('GRANT UPDATE(enabled) ON control.contributor_accounts TO omneum_enrollment')
    try:
        try: deploy.check_database(c,c['enrollment_dsn_file'],'omneum_enrollment')
        except ValueError: pass
        else: raise AssertionError('account-reactivation privilege accepted')
    finally:
        db.execute('REVOKE UPDATE(enabled) ON control.contributor_accounts FROM omneum_enrollment')
print('PASS: verified TLS DB, migration ledger/retry, role separation and least privilege')

# Validate effective unit syntax without claiming that Docker starts systemd.
deploy.RUNTIME.mkdir()
(deploy.RUNTIME/'libexec').mkdir()
(deploy.RUNTIME/'venv/bin').mkdir(parents=True)
os.symlink('/usr/local/bin/python',deploy.RUNTIME/'venv/bin/python')
(deploy.RUNTIME/'venv/lib').mkdir()
os.symlink('lib',deploy.RUNTIME/'venv/lib64')
deploy.validate_runtime_tree()
(deploy.RUNTIME/'venv/lib64').unlink()
os.symlink('/usr/local/lib',deploy.RUNTIME/'venv/lib64')
try: deploy.validate_runtime_tree()
except ValueError: pass
else: raise AssertionError('redirected venv library accepted')
(deploy.RUNTIME/'venv/lib64').unlink()
os.symlink('lib',deploy.RUNTIME/'venv/lib64')
shutil.copyfile('/usr/local/bin/omneumd',deploy.RUNTIME/'libexec/omneumd')
(deploy.RUNTIME/'libexec/omneumd').chmod(0o755)
rendered = root/'rendered'
rendered.mkdir(mode=0o700)
deploy.render(c,rendered)
for kind in ('ingestion','enrollment','evaluator'):
    target = Path('/etc/systemd/system')/('omneum-network-'+kind+'.service')
    shutil.copyfile(rendered/target.name,target)
    target.chmod(0o644)
run('systemd-analyze','verify',*(str(Path('/etc/systemd/system')/('omneum-network-'+kind+'.service')) for kind in ('ingestion','enrollment','evaluator')))
print('PASS: generated systemd unit syntax and isolated credential paths')

processes = []
try:
    processes.append(subprocess.Popen(['runuser','-u',crypto.pw_name,'--','/usr/local/bin/omneumd','serve','--key-dir',str(deploy.KEY_DIR),'--socket',str(deploy.SOCKET),'--client-uid',str(api.pw_uid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    for _ in range(100):
        if deploy.SOCKET.exists(): break
        time.sleep(.05)
    run('runuser','-u',api.pw_name,'--',sys.executable,'-m','omneum.network_deploy','evaluator-check','--uid',str(crypto.pw_uid),'--public-key',c['network_public_key'],env={**os.environ,'PYTHONPATH':'/repo'})
    denied = subprocess.run(['runuser','-u',enrollment.pw_name,'--',sys.executable,'-m','omneum.network_deploy','evaluator-check','--uid',str(crypto.pw_uid),'--public-key',c['network_public_key']],env={**os.environ,'PYTHONPATH':'/repo'},capture_output=True)
    assert denied.returncode != 0
    for user in (api,enrollment):
        assert subprocess.run(['runuser','-u',user.pw_name,'--','test','-r',str(deploy.KEY_DIR/'voprf.key')]).returncode != 0
    env = dict(PYTHONPATH='/repo',PATH=os.environ['PATH'],OMNEUM_NETWORK_BIND_HOST='127.0.0.1',OMNEUM_NETWORK_DEPLOYMENT_ID=c['deployment_id'],OMNEUM_NETWORK_KEY_VERSION='1',OMNEUM_NETWORK_PUBLIC_KEY=c['network_public_key'],OMNEUM_LOCAL_PUBLIC_KEY=c['local_public_key'],OMNEUM_DAEMON_SOCKET=str(deploy.SOCKET),OMNEUM_DAEMON_UID=str(crypto.pw_uid),OMNEUM_ACCOUNT_ISSUER=c['oidc_issuer'],OMNEUM_ACCOUNT_AUDIENCE=c['oidc_audience'],OMNEUM_NETWORK_CONSENT_VERSION=c['consent_version'])
    for user,kind,field,module in ((api,'ingestion','ingestion_dsn_file','network_api'),(enrollment,'enrollment','enrollment_dsn_file','enrollment_api')):
        directory = Path('/run/audit-credentials')/kind
        directory.mkdir(parents=True)
        os.chown(directory,user.pw_uid,user.pw_gid)
        directory.chmod(0o700)
        for name,source in (('database.dsn',c[field]),('ca.pem',c['database_ca']),('tls.crt',c['tls_certificate']),('tls.key',c['tls_private_key']),('jwks.json',c['oidc_jwks_file'])):
            if name == 'jwks.json' and kind == 'ingestion': continue
            target = write(directory/name,Path(source).read_bytes(),0o400)
            os.chown(target,user.pw_uid,user.pw_gid)
        variables = {**env,'OMNEUM_'+('NETWORK' if kind == 'ingestion' else 'ENROLLMENT')+'_DATABASE_DSN_FILE':str(directory/'database.dsn'), 'PGSSLROOTCERT':str(directory/'ca.pem'),'OMNEUM_NETWORK_TLS_CERT':str(directory/'tls.crt'),'OMNEUM_NETWORK_TLS_KEY':str(directory/'tls.key'),'OMNEUM_ACCOUNT_JWKS':str(directory/'jwks.json')}
        processes.append(subprocess.Popen(['runuser','-u',user.pw_name,'--',sys.executable,'-m','omneum.'+module],env=variables,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    async def provider(scope,receive,send):
        path=scope['path']
        if scope['type'] == 'lifespan':
            return await NetworkHTTPApp(None,None,None,None)(scope,receive,send)
        if path == '/.well-known/openid-configuration':
            value=dict(issuer=c['oidc_issuer'],jwks_uri=c['oidc_jwks_uri'],token_endpoint=c['oidc_token_endpoint'],device_authorization_endpoint=c['oidc_device_endpoint'],id_token_signing_alg_values_supported=['RS256'],grant_types_supported=['urn:ietf:params:oauth:grant-type:device_code'])
        elif path == '/jwks': value={'keys':[jwk]}
        elif path == '/device':
            from urllib.parse import parse_qs
            body=await receive()
            form=parse_qs(body['body'].decode())
            assert form['audience'] == [c['oidc_audience']]
            assert form['client_id'] == [c['oidc_client_id']]
            value=dict(verification_uri=c['oidc_verification_uri'],user_code='AUDIT-ONLY',device_code='disposable-device-code',expires_in=300,interval=1)
        elif path == '/token':
            t=int(time.time())
            value=dict(token_type='Bearer',access_token=jwt.encode(dict(iss=c['oidc_issuer'],sub='disposable-account',aud=[c['oidc_audience'],'https://identity.fixture-audit.net/userinfo'],iat=t,exp=t+300,scope='omneum:enroll'),idp_key,algorithm='RS256',headers={'kid':'disposable-key'}))
        else: return await NetworkHTTPApp._reply(send,404,{'code':'not_found'})
        return await NetworkHTTPApp._reply(send,200,value)
    idp=uvicorn.Server(uvicorn.Config(provider,host='127.0.0.1',port=9443,ssl_certfile=c['tls_certificate'],ssl_keyfile=c['tls_private_key'],lifespan='off',access_log=False,proxy_headers=False,log_level='error'))
    thread=threading.Thread(target=idp.run,daemon=True)
    thread.start()
    for _ in range(100):
        if idp.started: break
        time.sleep(.05)
    write('/etc/nginx/conf.d/omneum-network.conf',deploy.nginx_config(c))
    write('/etc/nginx/conf.d/disposable-provider.conf',f"server {{ listen 443 ssl; server_name identity.fixture-audit.net; ssl_certificate {c['tls_certificate']}; ssl_certificate_key {c['tls_private_key']}; access_log off; error_log /var/log/nginx/provider-error.log crit; location / {{ proxy_pass https://127.0.0.1:9443; }} }}\n",0o644)
    Path('/etc/nginx/sites-enabled/default').unlink(missing_ok=True)
    run('nginx','-t')
    run('nginx')
    network._PRODUCTION_NETWORK=network._ProductionNetwork('https://'+c['domain']+'/v1/contributions','https://'+c['domain']+'/v1/voprf',c['deployment_id'],1,bytes.fromhex(public_hex))
    onboarding._PRODUCTION_ONBOARDING=onboarding.OnboardingPins('https://'+c['domain']+'/v1/enrollment',c['oidc_device_endpoint'],c['oidc_token_endpoint'],c['oidc_verification_uri'],c['oidc_client_id'],'omneum:enroll',c['consent_url'],c['consent_version'],c['oidc_audience'])
    for _ in range(100):
        try:
            deploy.preflight(c,services=False)
            break
        except Exception as error:
            last_error = error
            time.sleep(.1)
    else: raise last_error
    original=acceptance.__dict__.get('preflight')
    # hosted imports preflight; retain every live check except systemd PID1
    # attestation, which is explicitly unavailable in this disposable container.
    real_preflight=deploy.preflight
    deploy.preflight=lambda config: real_preflight(config,services=False)
    original_input=builtins.input
    builtins.input=lambda prompt: 'research_context_graph'
    acceptance.hosted(c,str(root/'admin.dsn'))
    builtins.input=original_input
    from urllib.request import Request,ProxyHandler,build_opener
    from urllib.error import HTTPError
    from omneum.contribution.config import _NoRedirect
    opener=build_opener(ProxyHandler({}),_NoRedirect())
    try:
        opener.open(Request('https://'+c['domain']+'/v1/contributions',data=b'x'*(1048576+1),headers={'Content-Type':'application/json'}),timeout=10)
    except HTTPError as error:
        assert error.code == 413
        error.close()
    else: raise AssertionError('oversized ingress body accepted')
    statuses=[]
    for _ in range(15):
        try:
            opener.open(Request('https://'+c['domain']+'/v1/enrollment',data=b'{}',headers={'Content-Type':'application/json'}),timeout=10)
        except HTTPError as error:
            statuses.append(error.code)
            error.close()
    assert 429 in statuses
    print('PASS: actual ingress body limit and source-IP admission enforcement')
    print('PASS: generated nginx ingress, verified backend TLS, three Unix identities, evaluator authorization, synthetic-provider lifecycle acceptance')
    print('UNVERIFIED: actual systemd runtime confinement, real OIDC provider, production provisioning/acceptance')
finally:
    for process in processes:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill()
