"""Disposable Compose provisioning only; never run against an existing deployment."""
import datetime
import ipaddress
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from omneum.base64url import encode_unpadded

root = Path('/config')
# A completed configuration is stable across stop/start and restart.
if (root / 'ready').exists():
    raise SystemExit(0)
if any(root.iterdir()):
    raise SystemExit('Incomplete local provisioning: remove the disposable volumes and retry')
for path, mode in ((Path('/keys'), 0o700), (Path('/run/omneum'), 0o750)):
    os.chown(path, 10002, 10001)
    path.chmod(mode)


def provision(path):
    return bytes.fromhex(subprocess.check_output(
        ['omneumd', 'provision', '--key-dir', str(path)],
        user=10002, group=10001, text=True).strip())


public = provision('/keys')
# Distinct local-domain public key for boundary validation; retain no local secret.
with tempfile.TemporaryDirectory(dir='/opt', prefix='local-key-') as temp:
    os.chown(temp, 10002, 10001)
    local = provision(temp)


def write(name, content, mode=0o640):
    path = root / name
    path.write_text(content)
    os.chown(path, 0, 10001)
    path.chmod(mode)


write('deployment-id', 'urn:uuid:' + str(uuid4()))
write('public-key', encode_unpadded(public, expected_length=32))
write('local-public-key', encode_unpadded(local, expected_length=32))
admin = Path('/admin-config')
client = Path('/client')
os.chown(client, 10001, 10001)
client.chmod(0o700)
admin_password = secrets.token_urlsafe(48)
(admin / 'admin-password').write_text(admin_password)
(admin / 'admin-password').chmod(0o644)
(admin / 'operator-dsn').write_text(f'host=postgres dbname=omneum_network_test user=network_test_admin password={admin_password} sslmode=verify-full sslrootcert=/config/database-ca.crt')
os.chown(admin / 'operator-dsn', 0, 10001)
(admin / 'operator-dsn').chmod(0o640)
password = secrets.token_urlsafe(48)
write('ingestion-password', password, 0o644)
write('database-dsn', f'host=postgres dbname=omneum_network_test user=omneum_ingestion password={password} sslmode=verify-full sslrootcert=/config/database-ca.crt')
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=7))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName('localhost'), x509.DNSName('network-api'),
            x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
write('tls.crt', cert.public_bytes(serialization.Encoding.PEM).decode(), 0o644)
write('tls.key', key.private_bytes(serialization.Encoding.PEM,
      serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
# Keep PostgreSQL's independent TLS private key out of API-mounted volumes.
database_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
database_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'postgres')])
database_cert = (x509.CertificateBuilder().subject_name(database_name).issuer_name(database_name)
        .public_key(database_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=7))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('postgres')]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(database_key, hashes.SHA256()))
database_tls = Path('/database-tls')
os.chown(database_tls, 999, 999)  # postgres:17-bookworm image identity
database_tls.chmod(0o700)
certificate = database_cert.public_bytes(serialization.Encoding.PEM).decode()
write('database-ca.crt', certificate, 0o644)
for filename, content in (
    ('tls.crt', certificate),
    ('tls.key', database_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()),
):
    path = database_tls / filename
    path.write_text(content)
    os.chown(path, 999, 999)
    path.chmod(0o600)
write('ready', 'disposable local integration only\n', 0o644)
