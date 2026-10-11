//! Small stable-Rust OS boundary. Every unsafe call documents descriptor ownership.
use std::ffi::CString;
use std::fs::File;
use std::io;
use std::os::fd::{AsRawFd, FromRawFd, RawFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::path::{Component, Path};

pub fn denied() -> io::Error {
    io::Error::from(io::ErrorKind::PermissionDenied)
}
pub fn uid() -> u32 {
    unsafe { libc::geteuid() }
}

pub fn close_inherited_descriptors() -> io::Result<()> {
    // _SC_OPEN_MAX is the current limit, not the highest inherited descriptor:
    // a launcher can lower RLIMIT_NOFILE after opening a higher-numbered fd.
    // No threads or key files exist yet. Preserve only stdin/stdout/stderr.
    #[cfg(target_os = "linux")]
    {
        if unsafe { libc::syscall(libc::SYS_close_range, 3u32, u32::MAX, 0u32) } == 0 {
            return Ok(());
        }
        let error = io::Error::last_os_error();
        if !matches!(error.raw_os_error(), Some(libc::ENOSYS) | Some(libc::EPERM)) {
            return Err(error);
        }
    }
    #[cfg(target_os = "linux")]
    let directory = "/proc/self/fd";
    #[cfg(target_os = "macos")]
    let directory = "/dev/fd";
    // Collect first, dropping the directory iterator before closing its fd.
    // If the OS descriptor directory is unavailable, fail before key access.
    let descriptors = std::fs::read_dir(directory)?
        .map(|entry| {
            let entry = entry?;
            entry
                .file_name()
                .to_str()
                .ok_or_else(denied)?
                .parse::<i32>()
                .map_err(|_| denied())
        })
        .collect::<io::Result<Vec<_>>>()?;
    for fd in descriptors.into_iter().filter(|fd| *fd >= 3) {
        // These are inherited descriptors or the already closed iterator fd.
        unsafe {
            libc::close(fd);
        }
    }
    Ok(())
}

#[derive(Debug)]
pub struct Peer {
    pub uid: u32,
    pub gid: u32,
    pub pid: Option<i32>,
}

#[cfg(target_os = "linux")]
pub fn peer(stream: &UnixStream) -> io::Result<Peer> {
    let mut cred: libc::ucred = unsafe { std::mem::zeroed() };
    let mut size = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    // The live stream owns fd; cred and size are valid writable outputs.
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut cred as *mut libc::ucred).cast(),
            &mut size,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    if size as usize != std::mem::size_of::<libc::ucred>() {
        return Err(denied());
    }
    Ok(Peer {
        uid: cred.uid,
        gid: cred.gid,
        pid: Some(cred.pid),
    })
}

#[cfg(target_os = "macos")]
pub fn peer(stream: &UnixStream) -> io::Result<Peer> {
    let (mut uid, mut gid) = (0, 0);
    // getpeereid returns effective credentials established at connect/listen.
    if unsafe { libc::getpeereid(stream.as_raw_fd(), &mut uid, &mut gid) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(Peer {
        uid,
        gid,
        pid: None,
    })
}

fn owned_fd(fd: RawFd) -> io::Result<File> {
    if fd < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(unsafe { File::from_raw_fd(fd) })
    } // newly opened descriptor, owned once
}

pub fn open_child(
    parent: &File,
    name: &std::ffi::OsStr,
    flags: i32,
    mode: u32,
) -> io::Result<File> {
    let name = CString::new(name.as_bytes()).map_err(|_| denied())?;
    // Both mechanisms receive exactly one normal component.
    if name.as_bytes().contains(&b'/') || name.as_bytes() == b".." || name.as_bytes() == b"." {
        return Err(denied());
    }
    #[cfg(target_os = "linux")]
    {
        #[repr(C)]
        struct OpenHow {
            flags: u64,
            mode: u64,
            resolve: u64,
        }
        // Linux UAPI: BENEATH=0x08, NO_SYMLINKS=0x04 (also excludes magic links).
        // NO_XDEV is deliberately omitted: admin bind mounts are supported.
        let how = OpenHow {
            flags: flags as u64,
            mode: mode as u64,
            resolve: 0x08 | 0x04,
        };
        let fd = unsafe {
            libc::syscall(
                libc::SYS_openat2,
                parent.as_raw_fd(),
                name.as_ptr(),
                &how,
                std::mem::size_of::<OpenHow>(),
            )
        } as i32;
        if fd >= 0 {
            return owned_fd(fd);
        }
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(libc::ENOSYS) {
            return Err(error);
        }
    }
    owned_fd(unsafe {
        libc::openat(
            parent.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_NOFOLLOW,
            mode as libc::c_uint,
        )
    })
}

pub fn directory(path: &Path, test_mode: bool) -> io::Result<File> {
    if !path.is_absolute() {
        return Err(denied());
    }
    let mut dir = owned_fd(unsafe {
        libc::open(
            c"/".as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC,
        )
    })?;
    validate_ancestor(&dir, test_mode)?;
    for component in path.components() {
        match component {
            Component::RootDir => (),
            Component::Normal(name) => {
                dir = open_child(
                    &dir,
                    name,
                    libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
                    0,
                )?;
                validate_ancestor(&dir, test_mode)?;
            }
            _ => return Err(denied()),
        }
    }
    Ok(dir)
}
fn validate_ancestor(file: &File, test_mode: bool) -> io::Result<()> {
    let m = file.metadata()?;
    if !m.is_dir() || (m.uid() != 0 && m.uid() != uid()) {
        return Err(denied());
    }
    if m.mode() & 0o022 != 0 && !(test_mode && m.mode() & 0o1000 != 0) {
        return Err(denied());
    }
    if !test_mode {
        no_acl(file)?;
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn no_acl(file: &File) -> io::Result<()> {
    for name in [c"system.posix_acl_access", c"system.posix_acl_default"] {
        let n =
            unsafe { libc::fgetxattr(file.as_raw_fd(), name.as_ptr(), std::ptr::null_mut(), 0) };
        if n >= 0 {
            return Err(denied());
        }
        let e = io::Error::last_os_error();
        if !matches!(e.raw_os_error(), Some(libc::ENODATA) | Some(libc::ENOTSUP)) {
            return Err(e);
        }
    }
    Ok(())
}
#[cfg(target_os = "macos")]
fn no_acl(file: &File) -> io::Result<()> {
    // Darwin sys/acl.h: ACL_TYPE_EXTENDED=0x100, ACL_FIRST_ENTRY=0.
    unsafe extern "C" {
        fn acl_get_fd_np(fd: i32, kind: i32) -> *mut libc::c_void;
        fn acl_get_entry(acl: *mut libc::c_void, entry: i32, out: *mut *mut libc::c_void) -> i32;
        fn acl_free(acl: *mut libc::c_void) -> i32;
    }
    let acl = unsafe { acl_get_fd_np(file.as_raw_fd(), 0x100) };
    if acl.is_null() {
        // Darwin reports ENOENT when a valid open object has no extended ACL.
        let error = io::Error::last_os_error();
        return if error.raw_os_error() == Some(libc::ENOENT) {
            Ok(())
        } else {
            Err(error)
        };
    }
    let mut entry = std::ptr::null_mut();
    let result = unsafe { acl_get_entry(acl, 0, &mut entry) };
    let error = io::Error::last_os_error();
    unsafe {
        acl_free(acl);
    }
    // Darwin returns 0 for an entry, -1/EINVAL when there are no entries.
    if result == -1 && error.raw_os_error() == Some(libc::EINVAL) {
        Ok(())
    } else {
        Err(denied())
    }
}

pub fn private_directory(path: &Path, test_mode: bool) -> io::Result<File> {
    let dir = directory(path, test_mode)?;
    let m = dir.metadata()?;
    if m.uid() != uid() || m.mode() & 0o7777 != 0o700 {
        return Err(denied());
    }
    no_acl(&dir)?;
    Ok(dir)
}
pub fn key_file(dir: &File) -> io::Result<File> {
    let file = open_child(
        dir,
        std::ffi::OsStr::new("voprf.key"),
        libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
        0,
    )?;
    let m = file.metadata()?;
    if !m.is_file() || m.uid() != uid() || m.mode() & 0o7777 != 0o600 || m.nlink() != 1 {
        return Err(denied());
    }
    no_acl(&file)?;
    Ok(file)
}

pub fn harden(test_mode: bool) -> io::Result<()> {
    if uid() == 0 && !test_mode {
        return Err(denied());
    }
    unsafe {
        libc::umask(0o077);
    }
    let zero = libc::rlimit {
        rlim_cur: 0,
        rlim_max: 0,
    };
    if unsafe { libc::setrlimit(libc::RLIMIT_CORE, &zero) } != 0 {
        return Err(io::Error::last_os_error());
    }
    #[cfg(target_os = "linux")]
    {
        if unsafe { libc::prctl(libc::PR_SET_DUMPABLE, 0, 0, 0, 0) } != 0
            || unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } != 0
        {
            return Err(io::Error::last_os_error());
        }
        // Service must arrive without effective/permitted capabilities.
        #[repr(C)]
        struct Header {
            version: u32,
            pid: i32,
        }
        #[repr(C)]
        #[derive(Default, Copy, Clone)]
        struct Data {
            effective: u32,
            permitted: u32,
            inheritable: u32,
        }
        let header = Header {
            version: 0x20080522,
            pid: 0,
        };
        let mut data = [Data::default(); 2];
        if unsafe { libc::syscall(libc::SYS_capget, &header, data.as_mut_ptr()) } != 0 {
            return Err(io::Error::last_os_error());
        }
        if !test_mode
            && data
                .iter()
                .any(|d| d.effective != 0 || d.permitted != 0 || d.inheritable != 0)
        {
            return Err(denied());
        }
    }
    Ok(())
}
