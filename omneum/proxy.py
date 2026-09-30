"""Public stdio entry point: use Linux's existing native managed-session proxy."""
import os
from pathlib import Path
import sys

PROXY = '/usr/local/bin/omneum-server'


def linux_command():
    import grp
    import pwd

    if not Path(PROXY).is_file():
        raise RuntimeError("Managed Omneum server is not installed. Run 'omneum install'.")
    group = grp.getgrnam('omneum-client')
    if group.gr_gid in {*os.getgroups(), os.getgid(), os.getegid()}:
        return [PROXY]
    account = pwd.getpwuid(os.getuid())
    if account.pw_name not in group.gr_mem:
        raise RuntimeError("This account is not authorized for Omneum. Run 'omneum install'.")
    # sg refreshes ONLY the public frontend group for this subprocess, using the
    # system account database. The fixed command contains no caller input.
    # This avoids requiring a logout after usermod and grants no daemon access.
    return ['/usr/bin/sg', 'omneum-client', '-c', 'exec ' + PROXY]


def main():
    if sys.platform == 'linux':
        try:
            command = linux_command()
            os.execv(command[0], command)
        except (OSError, KeyError, RuntimeError) as error:
            sys.exit('omneum-server: ' + str(error))
    else:
        from .server import main as serve
        serve()


if __name__ == '__main__':
    main()
