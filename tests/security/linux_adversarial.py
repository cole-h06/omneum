"""Destructive probes: root, disposable systemd host, installed managed runtime only.

Run after linux_runtime.py. Only ExecStart changes; production sandbox properties
remain in force. Synthetic credentials and cross-session data are used. A failed
write protection test restores ordinary files; no private key bytes are read.
"""
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import select
import shutil
import socket
import subprocess
import sys
import struct

from adversarial_probe import LIBC, queue_create, queue_open
import time

from linux_runtime import CLIENT, PROXY, ROOT, instances, run


def exchange(client, request):
    client.stdin.write(json.dumps(request)+'\n'); client.stdin.flush()
    assert select.select([client.stdout], [], [], 45)[0], 'probe timed out'
    line = client.stdout.readline()
    assert line, 'probe exited; inspect journalctl -u omneum-server@*'
    return json.loads(line)


def denied(result):
    assert result['allowed'] is False, result


def host_denials(result):
    for collection in ('homes','shared_temp_read','storage','key_mutations','directories'):
        for value in result[collection].values(): denied(value)
    for name,value in result['network'].items():
        if name != 'DNS': denied(value)
    for values in result['mutations'].values():
        for value in values.values(): denied(value)
    for name in ('key_read','abstract','frontend_path'): denied(result[name])
    for value in result['unix'].values(): denied(value['connect'])
    for name in ('init','root','other_user','daemon'):
        for operation in ('environ','maps','mem_open','fds','ptrace','signal','kill_zero','pidfd_signal'):
            denied(result['processes'][name][operation])
    for value in result['persistence'].values():
        if 'artifact' in value: denied(value['artifact'])
    assert result['config_read']['allowed'] and len(result['daemon_public_key']) == 64
    assert result['threads'] == 4
    assert 'NoNewPrivs:\t1' in result['self_status'] and 'CapEff:\t0000000000000000' in result['self_status']


def unauthorized_peers(other):
    """Prove native rejection separately from socket DAC, using the real client."""
    directory, endpoint = Path('/run/omneumd'), Path('/run/omneumd/eval.sock')
    modes = directory.stat().st_mode & 0o777, endpoint.stat().st_mode & 0o777
    checks = []
    try:
        directory.chmod(0o755); endpoint.chmod(0o666)
        script = '''
import json,os,pwd,socket,sys
from omneum.daemon import DaemonServerContext
from omneum.oprf import OPRFProtocolError
with socket.socket(socket.AF_UNIX) as s: s.connect('/run/omneumd/eval.sock')
try: DaemonServerContext.fetch_public_key('/run/omneumd/eval.sock',pwd.getpwnam('omneum-crypto').pw_uid)
except OPRFProtocolError: pass
else: raise AssertionError('unauthorized evaluator access')
try: os.setgid(int(sys.argv[1]))
except PermissionError: pass
else: raise AssertionError('reserved primary group acquired')
print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'groups':os.getgroups(),'socket_connect':True,'evaluation':False,'setgid':False}))
'''
        for args in (['-u',CLIENT], ['-u',other.pw_name], ['-u',other.pw_name,'-g','omneum-ipc']):
            checks.append(json.loads(run('runuser',*args,'--',str(ROOT/'.venv/bin/python'),
                '-I','-B','-c',script,str(grp.getgrnam('omneum-session').gr_gid)).stdout))
        for name in (CLIENT,other.pw_name):
            switched = subprocess.run(['runuser','-u',name,'--','sg','omneum-session','-c','id -g'],
                                      input='\n',capture_output=True,text=True,timeout=5)
            assert switched.returncode != 0, 'reserved group acquired through sg'
    finally:
        directory.chmod(modes[0]); endpoint.chmod(modes[1])
    return checks


def main():
    assert sys.platform == 'linux' and os.geteuid() == 0
    assert not instances(), 'run without other sessions'
    override = Path('/etc/systemd/system/omneum-server@.service.d')
    assert not override.exists()
    try:
        pwd.getpwnam('omneum-adversarial-other')
        created_account = False
    except KeyError:
        created_account = True
    run('systemd-sysusers', '-', input='u omneum-adversarial-other - "Test user" /home/omneum-adversarial-other /usr/sbin/nologin\n')
    other = pwd.getpwnam('omneum-adversarial-other')
    client = pwd.getpwnam(CLIENT)
    assert grp.getgrnam('omneum-ipc').gr_gid not in os.getgrouplist(CLIENT, client.pw_gid)
    assert grp.getgrnam('omneum-client').gr_gid != grp.getgrnam('omneum-ipc').gr_gid
    home = Path(other.pw_dir)
    user_run = Path(f'/run/user/{other.pw_uid}')
    assert not home.exists() and not user_run.exists()
    site = next((ROOT/'.venv/lib').glob('python*/site-packages'))
    native = next(site.rglob('omneum_oprf*.so'), None)
    if native is None: native = next((site/'omneum_oprf').glob('*.so'))
    protected = [ (ROOT/'.venv/bin/python').resolve(), ROOT/'.venv/pyvenv.cfg',
        site/'omneum/server.py', native, ROOT/'.venv/bin/omneum-server',
        Path(PROXY), Path('/usr/local/libexec/omneumd'), Path('/etc/omneum/config.toml'),
        Path('/etc/omneumd/peer.conf'), Path('/etc/systemd/system/omneumd.service'),
        Path('/etc/systemd/system/omneum-server@.service') ]
    snapshots = {p: (p.read_bytes(), p.stat()) for p in protected}
    for p, (_, st) in snapshots.items():
        assert st.st_uid == 0 and not st.st_mode & 0o022, p
        for parent in p.parents:
            info = parent.stat()
            assert info.st_uid == 0 and not info.st_mode & 0o022, parent
    key_stat = Path('/var/lib/omneumd/voprf.key').stat()
    # Prove the underlying files also deny writes outside the service namespace.
    run('runuser','-u','omneum-mcp','--','/usr/bin/python3','-c',
        'import os,sys\nfor p in sys.argv[1:]:\n try: fd=os.open(p,os.O_WRONLY)\n except PermissionError: continue\n os.close(fd); raise AssertionError(p)',
        *map(str, protected))
    markers = [Path(p)/'omneum-adversarial-marker' for p in ('/tmp','/var/tmp','/dev/shm')]
    root_marker = Path('/root/omneum-adversarial-marker')
    replacement = Path('/etc/omneum/adversarial-source')
    assert not any(p.exists() for p in markers+[root_marker,replacement])
    helpers, clients = [], []
    host_socket = socket.socket(socket.AF_UNIX)
    result = {}
    collector = None
    host_queue = "/omneum-host-fixture"
    host_queue_fd = None
    yama = Path("/proc/sys/kernel/yama/ptrace_scope")
    old_yama = yama.read_text()
    try:
        home.mkdir(mode=0o755); os.chown(home, other.pw_uid, other.pw_gid)
        user_run.mkdir(mode=0o755)
        files = [home/p for p in ('.ssh/id_test', '.ssh/config', '.aws/credentials',
                  '.config/gcloud/application_default_credentials.json', '.azure/accessTokens.json',
                  '.bash_history', '.profile')]+[user_run/'credential',root_marker]
        for p in files+markers+[replacement]:
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('synthetic credential'); p.chmod(0o644)
        # These world-readable home fixtures ARE readable by the same UID outside
        # the service. Thus an in-service denial measures containment, not DAC.
        run('runuser','-u','omneum-mcp','--','/usr/bin/python3','-c',
            'import sys; [open(p).read() for p in sys.argv[1:]]', *map(str, files[:-1]))
        host_socket.bind('\0omneum-adversarial-host'); host_socket.listen(4)
        for identity in ('root', other.pw_name):
            helpers.append(subprocess.Popen(['runuser','-u',identity,'--','/usr/bin/sleep','300']))
        # runuser has a child; identify that actual process rather than its root launcher.
        time.sleep(.2)
        helper_pids = [int(run('pgrep','-P',str(p.pid)).stdout.strip()) for p in helpers]
        daemon = int(run('systemctl','show','--value','-p','MainPID','omneumd').stdout)
        unix = [(p,kind) for p,kind in [('/run/dbus/system_bus_socket',1),('/run/systemd/private',1),
            ('/run/systemd/journal/stdout',1),('/run/systemd/journal/socket',2),
            ('/run/systemd/resolve/io.systemd.Resolve',1),('/run/snapd.socket',1),
            ('/run/polkit-1/polkitd',1)] if Path(p).exists()]
        # Remove Yama as a possible explanation for cross-session denial.
        yama.write_text('0')
        host_queue_fd = queue_create(host_queue)
        collector = socket.socket(socket.AF_UNIX)
        collector.bind('/run/omneumd/credentials.sock')
        os.chown('/run/omneumd/credentials.sock', 0, grp.getgrnam('omneum-ipc').gr_gid)
        os.chmod('/run/omneumd/credentials.sock', 0o660)
        collector.listen(2); collector.settimeout(5)
        override.mkdir()
        (override/'adversarial.conf').write_text('[Service]\nExecStart=\nExecStart=/opt/omneum/.venv/bin/python -I -B /opt/omneum/tests/security/adversarial_probe.py\n')
        run('systemctl','daemon-reload')
        clients = [subprocess.Popen(['runuser','-u',CLIENT,'--',PROXY],stdin=subprocess.PIPE,
                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        ready = [exchange(p,{'mode':'ready'}) for p in clients]
        assert len(instances()) == 2 and ready[0]['pid'] != ready[1]['pid']
        # Reinstallation must preserve live identities and accept valid dynamic
        # users while rejecting statically assigned reserved identities.
        run('sh',str(ROOT/'deploy/install-server.sh'),str(ROOT/'target/release/omneum-server'),
            '/var/lib/omneum/.config/Omneum/config.toml')
        assert ready[0]['uid'] != ready[1]['uid']
        assert len({os.readlink('/proc/self/ns/ipc'), *(r['ipc'] for r in ready)}) == 3
        peer_credentials = []
        for index, p in enumerate(clients):
            exchange(p, {'mode':'credentials'})
            peer,_ = collector.accept()
            with peer:
                cred = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                peer_credentials.append(cred)
                assert tuple(cred) == (ready[index]['pid'],ready[index]['uid'],ready[index]['gid'])
            assert ready[index]['gid'] == grp.getgrnam('omneum-session').gr_gid
            assert set(ready[index]['groups']) == {grp.getgrnam('omneum-session').gr_gid,grp.getgrnam('omneum-ipc').gr_gid}
            assert not Path('/dev/mqueue/'+ready[index]['queue'][1:]).exists()
            try: queue_open(ready[index]['queue'])
            except FileNotFoundError: pass
            else: raise AssertionError('host can open session queue')
        rounds = []
        for index in range(2):
            victim = ready[1-index]
            request = {'mode':'attack','home_files':list(map(str,files)), 'home':str(home),
                'user_run':str(user_run),'protected':list(map(str,protected)), 'replacement':str(replacement),
                'temp_files':list(map(str,markers)), 'site':str(site), 'unix':unix,
                'pids':{'init':1,'root':helper_pids[0],'other_user':helper_pids[1],
                        'daemon':daemon,'other_session':victim['pid']},'victim_fd':victim['fd'],
                'queues':[host_queue,victim['queue']]}
            attacked = exchange(clients[index], request)
            host_denials(attacked)
            attacked['cross_session_terminate'] = exchange(clients[index],{'mode':'terminate','pid':victim['pid']})
            denied(attacked['cross_session_terminate'])
            attacked['victim_status'] = exchange(clients[1-index],{'mode':'status'})
            assert attacked['victim_status']['signals'] == 0
            assert attacked['victim_status']['data'] == 'original synthetic data'
            assert attacked['victim_status']['uid'] == victim['uid']
            assert attacked['victim_status']['public_key'] == attacked['daemon_public_key']
            for name in ('cross_session_signal','cross_session_memfd_read','cross_session_memfd_write','cross_session_frontend_fd'):
                denied(attacked[name])
            for name in ('environ','maps','mem_open','fds','ptrace','signal','kill_zero','pidfd_signal'):
                denied(attacked['processes']['other_session'][name])
            for value in attacked['queues'].values():
                assert not value['visible']
                denied(value['open'])
            assert attacked['message_queue']['allowed']
            assert attacked['message_queue']['value']['ipc_namespace'] == ready[index]['ipc']
            rounds.append(attacked)
        result = rounds[0]
        result['reverse'] = rounds[1]
        result['identities'] = ready
        result['SO_PEERCRED'] = peer_credentials
        result['unauthorized_peers'] = unauthorized_peers(other)
        result['host'] = {'uname':run('uname','-a').stdout.strip(),
            'ipc_namespace':os.readlink('/proc/self/ns/ipc'),
            'systemd':run('systemctl','--version').stdout.splitlines()[0],
            'yama':Path('/proc/sys/kernel/yama/ptrace_scope').read_text().strip(),
            'units':{p:Path(p).read_text() for p in ['/etc/systemd/system/omneum-server@.service','/etc/systemd/system/omneum-server.socket']},
            'ownership':{str(p):{'uid':s.st_uid,'gid':s.st_gid,'mode':oct(s.st_mode & 0o7777),
                       'sha256':hashlib.sha256(data).hexdigest()} for p,(data,s) in snapshots.items()}}
        # Preserve evidence even if an assertion reveals a defect.
        Path('/tmp/omneum-adversarial-results.json').write_text(json.dumps(result,indent=2))
        for p in clients:
            p.stdin.close(); p.wait(timeout=15)
            assert not p.stderr.read(), 'proxy stderr contains unexpected diagnostics'
        for _ in range(120):
            if not instances() and not any(Path(f'/proc/{r["child_pid"]}').exists() for r in rounds): break
            time.sleep(.1)
        assert not instances() and not any(Path(f'/proc/{r["child_pid"]}').exists() for r in rounds), 'session/child leak'
        for p,(data,_) in snapshots.items(): assert p.read_bytes() == data, p
        current = Path('/var/lib/omneumd/voprf.key').stat()
        assert (current.st_ino,current.st_size,current.st_mtime_ns) == (key_stat.st_ino,key_stat.st_size,key_stat.st_mtime_ns)
        assert int(run('systemctl','show','--value','-p','MainPID','omneumd').stdout) == daemon
        result['cleanup'] = 'session processes and child gone; protected files unchanged; daemon stable'
        Path('/tmp/omneum-adversarial-results.json').write_text(json.dumps(result,indent=2))
        print('PASS: adversarial managed-runtime properties; detailed results in /tmp/omneum-adversarial-results.json')
    finally:
        for unit in instances(): run('systemctl','stop',unit)
        for p in clients:
            if p.poll() is None: p.terminate(); p.wait(timeout=10)
        for p in helpers:
            if p.poll() is None: p.terminate(); p.wait(timeout=10)
        host_socket.close()
        yama.write_text(old_yama)
        if collector is not None:
            collector.close(); Path('/run/omneumd/credentials.sock').unlink(missing_ok=True)
        if host_queue_fd is not None:
            LIBC.mq_close(host_queue_fd); assert LIBC.mq_unlink(host_queue.encode()) == 0
        if override.exists():
            (override/'adversarial.conf').unlink(missing_ok=True); override.rmdir()
            run('systemctl','daemon-reload')
        for p in markers+[root_marker,replacement]: p.unlink(missing_ok=True)
        for p in (home,user_run):
            if p.exists(): shutil.rmtree(p)
        if created_account:
            run('userdel',other.pw_name)
            try: grp.getgrnam(other.pw_name)
            except KeyError: pass
            else: run('groupdel',other.pw_name)
        for p,(data,st) in snapshots.items():
            if not p.exists() or p.read_bytes() != data:
                p.write_bytes(data); os.chown(p,st.st_uid,st.st_gid); p.chmod(st.st_mode & 0o7777)
            Path(str(p)+'.adversarial-moved').unlink(missing_ok=True)
            (p.parent/'.adversarial-sibling').unlink(missing_ok=True)
    # Finish through the public proxy with the production ExecStart restored.
    run('runuser','-u',CLIENT,'--',str(ROOT/'.venv/bin/python'),
        str(ROOT/'tests/security/linux_runtime.py'),'workload')
    assert not Path('/dev/mqueue/omneum-adversarial-queue').exists()
    print('PASS: production MCP workload after adversarial sessions')


if __name__ == '__main__': main()
