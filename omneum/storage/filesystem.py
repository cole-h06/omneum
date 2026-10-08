"""Reject recognizable remote mounts before opening the local SQLite graph."""
import os
from pathlib import Path
import re
import sys


_NETWORK_FILESYSTEMS = frozenset({
    'nfs', 'nfs4', 'cifs', 'smbfs', 'smb3', 'afpfs', 'afs', 'ceph',
    'glusterfs', 'davfs', 'fuse.sshfs', 'fuse.glusterfs', 'fuse.ceph', 'fuse.davfs',
})


def _linux_filesystem_type(path):
    try:
        mounts = Path('/proc/self/mountinfo').read_text(encoding='utf-8', errors='surrogateescape')
    except OSError:
        # /proc may be unavailable in a restricted environment. There is no
        # portable proof that an arbitrary filesystem supplies correct WAL locks.
        return None
    selected, depth = None, -1
    for line in mounts.splitlines():
        left, separator, right = line.partition(' - ')
        fields, filesystem = left.split(), right.split()
        if not separator or len(fields) < 6 or not filesystem:
            continue
        mount = Path(re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4]))
        if path.is_relative_to(mount) and len(mount.parts) >= depth:
            selected, depth = filesystem[0], len(mount.parts)
    return selected


def _darwin_is_local(path):
    # Darwin's statvfs omits MNT_LOCAL; use the native statfs64 layout instead.
    # Layout and flag are defined by the platform's <sys/mount.h>.
    import ctypes

    class StatFS64(ctypes.Structure):
        _fields_ = [
            ('bsize', ctypes.c_uint32), ('iosize', ctypes.c_int32),
            ('blocks', ctypes.c_uint64), ('bfree', ctypes.c_uint64),
            ('bavail', ctypes.c_uint64), ('files', ctypes.c_uint64),
            ('ffree', ctypes.c_uint64), ('fsid', ctypes.c_int32 * 2),
            ('owner', ctypes.c_uint32), ('type', ctypes.c_uint32),
            ('flags', ctypes.c_uint32), ('subtype', ctypes.c_uint32),
            ('type_name', ctypes.c_char * 16), ('mount_name', ctypes.c_char * 1024),
            ('mount_source', ctypes.c_char * 1024), ('reserved', ctypes.c_uint32 * 8),
        ]

    statfs = ctypes.CDLL(None, use_errno=True).statfs64
    statfs.argtypes = [ctypes.c_char_p, ctypes.POINTER(StatFS64)]
    statfs.restype = ctypes.c_int
    info = StatFS64()
    if statfs(os.fsencode(path), ctypes.byref(info)) != 0:
        raise OSError(ctypes.get_errno(), 'cannot determine SQLite filesystem type')
    return bool(info.flags & 0x00001000)  # MNT_LOCAL


def _windows_drive_type(root):
    import ctypes

    drive_type = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
    drive_type.argtypes = [ctypes.c_wchar_p]
    drive_type.restype = ctypes.c_uint
    return drive_type(root)


def require_local_filesystem(path):
    if sys.platform == 'linux':
        remote = _linux_filesystem_type(path) in _NETWORK_FILESYSTEMS
    elif sys.platform == 'darwin':
        remote = not _darwin_is_local(path)
    elif sys.platform == 'win32':
        remote = _windows_drive_type(path.anchor) == 4  # DRIVE_REMOTE, including mapped drives
    else:
        remote = False
    if remote:
        raise ValueError('SQLite requires a local filesystem; network mounts are unsupported')
