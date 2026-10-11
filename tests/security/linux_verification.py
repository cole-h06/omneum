"""Real credential checks at Python startup and imports on a disposable install.

Run as root after /opt/omneum and the service accounts are installed. The .pth
fixture is removed in finally; no key, service or account is changed.
"""
import json
import os
from pathlib import Path
import pwd
import runpy
import sys


def main():
    assert sys.platform == 'linux' and os.geteuid() == 0
    root = Path('/opt/omneum')
    scope = runpy.run_path(root / 'deploy/install_server.py')
    account = pwd.getpwnam('omneum-mcp')
    sites = list((root / '.venv/lib').glob('python*/site-packages'))
    assert len(sites) == 1
    hook = sites[0] / '_omneum_verification_probe.pth'
    # Audit records are generated at startup and immediately before imports;
    # successful imports plus an after-import record prove both execute here.
    code = '''import os,sys,builtins
builtins._omneum_verification_events = []
def record(name):
    builtins._omneum_verification_events.append([name, list(os.getresuid()), list(os.getresgid()), os.getgroups()])
record('startup')
def audit(event,args):
    if event == 'import' and (args[0] == 'omneum' or args[0].startswith('omneum_oprf')):
        record(args[0])
sys.addaudithook(audit)
'''
    assert not hook.exists()
    try:
        with hook.open('x') as output:
            output.write('import builtins; exec(' + repr(code) + ', {})\n')
        hook.chmod(0o644)
        result = scope['unprivileged_python']('-c', '''
import os,sys,json,builtins,omneum,omneum_oprf
builtins._omneum_verification_events.append(['after',list(os.getresuid()),list(os.getresgid()),os.getgroups()])
native = [module.__file__ for name,module in sys.modules.items()
          if name.startswith('omneum_oprf') and getattr(module,'__file__','').endswith('.so')]
print(json.dumps({'events':builtins._omneum_verification_events,'status':open('/proc/self/status').read(),
                  'native':native}))
''')
        data = json.loads(result.stdout)
        assert {'startup', 'omneum', 'omneum_oprf', 'after'} <= {row[0] for row in data['events']}
        for name, uids, gids, groups in data['events']:
            assert uids == [account.pw_uid] * 3, (name, uids)
            assert gids == [account.pw_gid] * 3, (name, gids)
            assert groups == [], (name, groups)
        assert len(data['native']) == 1
        status = dict(line.split(':', 1) for line in data['status'].splitlines() if ':' in line)
        assert status['NoNewPrivs'].strip() == '1'
        for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
            assert int(status[key].strip(), 16) == 0
        print('PASS: non-root real/effective/saved IDs at startup/application/native imports; no groups or capabilities')
    finally:
        hook.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
