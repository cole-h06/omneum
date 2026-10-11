"""Reject recognizable remote mounts before opening the local SQLite graph."""
import os
from pathlib import Path
import re
import sys
import stat
from contextlib import contextmanager


@contextmanager
def private_directory(path, *, create=False, ancestor=False):
    """Walk and validate before mutation; never follow caller-owned symlinks.

    Keep the directory descriptor alive during file validation/opening. Other UIDs
    cannot replace validated non-writable ancestors. This is not a sandbox
    against another process with the same UID (including SQLite's path VFS).
    """
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('private directory path must not contain traversal')
    if path == Path(path.anchor):
        raise ValueError('private directory cannot be a filesystem root')
    # Only these root-owned Darwin platform aliases may be resolved.
    if sys.platform == 'darwin' and path.parts[1:2] in (('tmp',), ('var',), ('etc',)):
        path = Path('/' + path.parts[1]).resolve(strict=True).joinpath(*path.parts[2:])
    if os.name != 'posix':
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise ValueError('private directory must not be a symlink')
        yield path, None
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        root = os.fstat(fd)
        if root.st_uid != 0 or root.st_mode & 0o022:
            raise ValueError('SQLite directory has an unsafe root ancestor')
        require_safe_acl(fd, ancestor=True)
        for index, name in enumerate(path.parts[1:]):
            try:
                child = os.open(name, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass  # Concurrent creator is validated below.
                child = os.open(name, flags, dir_fd=fd)
            except OSError:
                raise ValueError('private directory must not contain symlinks') from None
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            final = index == len(path.parts) - 2 and not ancestor
            if final:
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError('SQLite directory must be owner-only (0700)')
                require_safe_acl(fd)
            else:
                if (info.st_uid not in (0, os.getuid())
                        or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                    raise ValueError('SQLite directory has an unsafe ancestor')
                require_safe_acl(fd, ancestor=True)
        yield path, fd
    finally:
        os.close(fd)


def require_safe_acl(fd, *, ancestor=False):
    """Darwin ACL grants are independent of chmod's POSIX mode bits.

    Deny entries (including the standard home-directory deny-delete entry)
    remain valid. Reject grants on private objects and mutation grants on
    ancestors. Linux ACL access masks are already bounded by the mode checks.
    """
    if sys.platform != 'darwin':
        return
    import ctypes
    import errno

    libc = ctypes.CDLL(None, use_errno=True)
    pointer = ctypes.c_void_p
    signatures = {
        'acl_get_fd_np': ([ctypes.c_int, ctypes.c_int], pointer),
        'acl_get_entry': ([pointer, ctypes.c_int, ctypes.POINTER(pointer)], ctypes.c_int),
        'acl_get_tag_type': ([pointer, ctypes.POINTER(ctypes.c_int)], ctypes.c_int),
        'acl_get_permset': ([pointer, ctypes.POINTER(pointer)], ctypes.c_int),
        'acl_get_perm_np': ([pointer, ctypes.c_uint32], ctypes.c_int),
        'acl_free': ([pointer], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(libc, name)
        function.argtypes, function.restype = arguments, result
    acl = libc.acl_get_fd_np(fd, 0x100)  # ACL_TYPE_EXTENDED
    if not acl:
        error = ctypes.get_errno()
        if error == errno.ENOENT:
            return
        raise OSError(error, 'cannot inspect SQLite ACL')
    try:
        entry, selector = pointer(), 0  # ACL_FIRST_ENTRY
        while True:
            result = libc.acl_get_entry(acl, selector, ctypes.byref(entry))
            if result == -1 and ctypes.get_errno() == errno.EINVAL:
                return  # Darwin end-of-entries convention
            if result != 0:
                raise OSError(ctypes.get_errno(), 'cannot inspect SQLite ACL')
            selector = -1  # ACL_NEXT_ENTRY
            tag = ctypes.c_int()
            if libc.acl_get_tag_type(entry, ctypes.byref(tag)) != 0:
                raise OSError(ctypes.get_errno(), 'cannot inspect SQLite ACL')
            if tag.value == 2:  # ACL_EXTENDED_DENY
                continue
            if tag.value != 1 or not ancestor:  # ACL_EXTENDED_ALLOW
                raise ValueError('SQLite private objects must not have ACL grants')
            permissions = pointer()
            if libc.acl_get_permset(entry, ctypes.byref(permissions)) != 0:
                raise OSError(ctypes.get_errno(), 'cannot inspect SQLite ACL')
            for bit in (2, 4, 5, 6, 8, 10, 12, 13):
                allowed = libc.acl_get_perm_np(permissions, 1 << bit)
                if allowed < 0:
                    raise OSError(ctypes.get_errno(), 'cannot inspect SQLite ACL')
                if allowed:
                    raise ValueError('SQLite directory has an unsafe ancestor ACL')
    finally:
        libc.acl_free(acl)


def require_safe_directory_acl(path, *, ancestor=False):
    if sys.platform != 'darwin':
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require_safe_acl(fd, ancestor=ancestor)
    finally:
        os.close(fd)


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
