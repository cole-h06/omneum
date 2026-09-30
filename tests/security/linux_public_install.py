"""Post-install checks as the original login user on a disposable systemd CI host."""
import grp
import os
from pathlib import Path
import socket
import sys

from omneum.installation import verify_managed_connection

assert sys.platform == 'linux' and os.geteuid() != 0
import pwd
account = pwd.getpwuid(os.getuid())
groups = os.getgrouplist(account.pw_name, account.pw_gid)
assert grp.getgrnam('omneum-client').gr_gid in groups
assert grp.getgrnam('omneum-ipc').gr_gid not in groups
assert grp.getgrnam('omneum-session').gr_gid not in groups
for path in ('/var/lib/omneumd/voprf.key',):
    try:
        Path(path).read_bytes()
    except PermissionError:
        pass
    else:
        raise AssertionError('login user can read private key')
with socket.socket(socket.AF_UNIX) as stream:
    try:
        stream.connect('/run/omneumd/eval.sock')
    except PermissionError:
        pass
    else:
        raise AssertionError('login user can connect directly to daemon')
for path in ('/opt/omneum/.venv/pyvenv.cfg', '/etc/omneum/config.toml'):
    assert Path(path).stat().st_uid == 0
    assert not os.access(path, os.W_OK)
verify_managed_connection()
print('PASS: fresh-host install, frontend proxy, proof verification, identity and key isolation')
