//! Local, one-key VOPRF evaluator. No Python, network protocols, or plaintext inputs.
pub mod os;
use crate::voprf_core::*;
use rand::rngs::OsRng;
use std::fs::File;
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};
use voprf::{Group, Ristretto255, VoprfServer};
use zeroize::Zeroizing;

pub const VERSION: u8 = 1;
pub const GET_PUBLIC_KEY: u8 = 1;
pub const BLIND_EVALUATE: u8 = 2;
pub const HEADER: usize = 4;
pub const MAX_REQUEST: usize = HEADER + ELEMENT_LENGTH;
pub const MAX_RESPONSE: usize = HEADER + ELEMENT_LENGTH + PROOF_LENGTH;
pub const SUCCESS: u8 = 0;
pub const INVALID_REQUEST: u8 = 1;
pub const INVALID_ELEMENT: u8 = 2;
pub const BUSY: u8 = 3;
pub const INTERNAL_ERROR: u8 = 4;
static STOP: AtomicBool = AtomicBool::new(false);
extern "C" fn stop(_: i32) {
    STOP.store(true, Ordering::Relaxed);
}

pub struct Settings {
    pub key_dir: PathBuf,
    pub socket: PathBuf,
    pub client_uid: u32,
    pub session_gid: Option<u32>,
    pub connections: usize,
    pub rate: u32,
    pub burst: u32,
    pub frame_ms: u64,
    pub idle_ms: u64,
    pub write_ms: u64,
    pub test_mode: bool,
}
impl Settings {
    fn parse(args: &[String]) -> io::Result<Self> {
        #[cfg(target_os = "linux")]
        let (key, socket) = ("/var/lib/omneumd", "/run/omneumd/eval.sock");
        #[cfg(target_os = "macos")]
        let (key, socket) = (
            "/Library/Application Support/OmneumCrypto",
            "/Library/Application Support/OmneumIPC/eval.sock",
        );
        let mut s = Self {
            key_dir: key.into(),
            socket: socket.into(),
            client_uid: u32::MAX,
            session_gid: None,
            connections: 32,
            rate: 128,
            burst: 64,
            frame_ms: 250,
            idle_ms: 1000,
            write_ms: 250,
            test_mode: false,
        };
        let mut args = args.iter();
        while let Some(name) = args.next() {
            if name == "--test-mode" {
                if !cfg!(feature = "test-daemon") {
                    return Err(os::denied());
                }
                s.test_mode = true;
                continue;
            }
            let value = args.next().ok_or_else(os::denied)?;
            match name.as_str() {
                "--key-dir" => s.key_dir = value.into(),
                "--socket" => s.socket = value.into(),
                "--client-uid" => s.client_uid = value.parse().map_err(|_| os::denied())?,
                #[cfg(target_os = "linux")]
                "--session-gid" => s.session_gid = Some(value.parse().map_err(|_| os::denied())?),
                "--connections" => s.connections = value.parse().map_err(|_| os::denied())?,
                "--rate" => s.rate = value.parse().map_err(|_| os::denied())?,
                "--burst" => s.burst = value.parse().map_err(|_| os::denied())?,
                "--frame-ms" => s.frame_ms = value.parse().map_err(|_| os::denied())?,
                "--idle-ms" => s.idle_ms = value.parse().map_err(|_| os::denied())?,
                "--write-ms" => s.write_ms = value.parse().map_err(|_| os::denied())?,
                _ => return Err(os::denied()),
            }
        }
        if !(1..=128).contains(&s.connections)
            || !(1..=100_000).contains(&s.rate)
            || !(1..=100_000).contains(&s.burst)
            || [s.frame_ms, s.idle_ms, s.write_ms]
                .iter()
                .any(|n| !(1..=60_000).contains(n))
        {
            return Err(os::denied());
        }
        Ok(s)
    }

    fn authorizes(&self, peer: &os::Peer) -> bool {
        // Preserve the static administrative identity. Linux managed sessions
        // have distinct UIDs and a reserved, administrator-assigned primary GID.
        // Supplementary membership (including omneum-ipc) is never sufficient.
        peer.uid == self.client_uid
            || (peer.uid != 0 && peer.uid != os::uid() && self.session_gid == Some(peer.gid))
    }
}

pub fn main_entry() -> io::Result<()> {
    let args: Vec<_> = std::env::args_os()
        .skip(1)
        .map(|arg| arg.into_string().map_err(|_| os::denied()))
        .collect::<io::Result<_>>()?;
    let command = args.first().ok_or_else(os::denied)?;
    let settings = Settings::parse(&args[1..])?;
    os::harden(settings.test_mode)?;
    // No socket activation or inherited IPC is supported. Close descriptors before key access.
    let max_fd = unsafe { libc::sysconf(libc::_SC_OPEN_MAX) };
    if max_fd < 0 {
        return Err(os::denied());
    }
    for fd in 3..max_fd.min(i32::MAX as i64) as i32 {
        unsafe {
            libc::close(fd);
        }
    }
    let limits = libc::rlimit {
        rlim_cur: 256,
        rlim_max: 256,
    };
    if unsafe { libc::setrlimit(libc::RLIMIT_NOFILE, &limits) } != 0 {
        return Err(io::Error::last_os_error());
    }
    match command.as_str() {
        "provision" => provision(&settings),
        "serve" => {
            if settings
                .session_gid
                .is_some_and(|gid| gid == 0 || gid == u32::MAX || gid == unsafe { libc::getegid() })
            {
                return Err(os::denied());
            }
            if settings.client_uid == u32::MAX
                || (!settings.test_mode
                    && (settings.client_uid == 0 || settings.client_uid == os::uid()))
            {
                return Err(os::denied());
            }
            let dir = os::private_directory(&settings.key_dir, settings.test_mode)?;
            let server = server_from_reader(os::key_file(&dir)?).map_err(|_| os::denied())?;
            drop(dir);
            serve(settings, server)
        }
        _ => Err(os::denied()),
    }
}
fn provision(s: &Settings) -> io::Result<()> {
    let dir = os::private_directory(&s.key_dir, s.test_mode)?;
    let scalar = Zeroizing::new(<Ristretto255 as voprf::CipherSuite>::Group::random_scalar(
        &mut OsRng,
    ));
    let bytes =
        Zeroizing::new(<Ristretto255 as voprf::CipherSuite>::Group::serialize_scalar(*scalar));
    let server = server_from_key(&bytes).map_err(|_| os::denied())?;
    let mut file = os::open_child(
        &dir,
        std::ffi::OsStr::new("voprf.key"),
        libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_CLOEXEC | libc::O_NOFOLLOW,
        0o600,
    )?;
    // Never silently recover a partial write: operator must inspect/remove it before retrying.
    file.write_all(&bytes)?;
    file.sync_all()?;
    dir.sync_all()?;
    let mut output = io::stdout().lock();
    for byte in public_key(&server) {
        write!(output, "{byte:02x}")?;
    }
    writeln!(output)?;
    Ok(())
}
fn public_key(server: &VoprfServer<Ristretto255>) -> Vec<u8> {
    <Ristretto255 as voprf::CipherSuite>::Group::serialize_elem(server.get_public_key()).to_vec()
}

struct SocketGuard {
    path: PathBuf,
    device: u64,
    inode: u64,
    _lock: File,
    _dir: File,
}
impl Drop for SocketGuard {
    fn drop(&mut self) {
        if let Ok(m) = std::fs::symlink_metadata(&self.path) {
            if m.dev() == self.device && m.ino() == self.inode {
                let _ = std::fs::remove_file(&self.path);
            }
        }
    }
}
fn bind(s: &Settings) -> io::Result<(UnixListener, SocketGuard)> {
    let parent = s.socket.parent().ok_or_else(os::denied)?;
    let dir = os::directory(parent, s.test_mode)?;
    let m = dir.metadata()?;
    if m.uid() != os::uid() || (!s.test_mode && m.mode() & 0o7777 != 0o750) {
        return Err(os::denied());
    }
    let name = s.socket.file_name().ok_or_else(os::denied)?;
    if name != "eval.sock" {
        return Err(os::denied());
    }
    let lock = os::open_child(
        &dir,
        std::ffi::OsStr::new("daemon.lock"),
        libc::O_RDWR | libc::O_CREAT | libc::O_NOFOLLOW | libc::O_CLOEXEC,
        0o600,
    )?;
    let m = lock.metadata()?;
    if !m.is_file() || m.uid() != os::uid() || m.nlink() != 1 || m.mode() & 0o7777 != 0o600 {
        return Err(os::denied());
    }
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err(os::denied());
    }
    if let Ok(m) = std::fs::symlink_metadata(&s.socket) {
        use std::os::unix::fs::FileTypeExt;
        if !m.file_type().is_socket() || m.uid() != os::uid() {
            return Err(os::denied());
        }
        // Lock excludes compliant active daemons; never unlink another live listener.
        match UnixStream::connect(&s.socket) {
            Ok(_) => return Err(os::denied()),
            Err(e) if e.raw_os_error() == Some(libc::ECONNREFUSED) => {
                std::fs::remove_file(&s.socket)?
            }
            Err(e) => return Err(e),
        }
    }
    // Path ancestors are non-writable by the caller UID; privileged admin races are out of scope.
    let listener = UnixListener::bind(&s.socket)?;
    let m = std::fs::symlink_metadata(&s.socket)?;
    let guard = SocketGuard {
        path: s.socket.clone(),
        device: m.dev(),
        inode: m.ino(),
        _lock: lock,
        _dir: dir,
    };
    std::fs::set_permissions(&s.socket, std::fs::Permissions::from_mode(0o660))?;
    if unsafe { libc::listen(listener.as_raw_fd(), s.connections as i32) } != 0 {
        return Err(io::Error::last_os_error());
    }
    listener.set_nonblocking(true)?;
    Ok((listener, guard))
}

struct Bucket {
    tokens: f64,
    last: Instant,
    rate: f64,
    burst: f64,
}
impl Bucket {
    fn take(&mut self, now: Instant) -> bool {
        self.tokens =
            (self.tokens + now.duration_since(self.last).as_secs_f64() * self.rate).min(self.burst);
        self.last = now;
        if self.tokens < 1.0 {
            false
        } else {
            self.tokens -= 1.0;
            true
        }
    }
}
struct Connection {
    stream: UnixStream,
    input: [u8; MAX_REQUEST],
    used: usize,
    needed: usize,
    output: [u8; MAX_RESPONSE],
    out_len: usize,
    sent: usize,
    deadline: Instant,
    close_after_write: bool,
}
impl Connection {
    fn new(stream: UnixStream, s: &Settings) -> io::Result<Self> {
        stream.set_nonblocking(true)?;
        Ok(Self {
            stream,
            input: [0; MAX_REQUEST],
            used: 0,
            needed: HEADER,
            output: [0; MAX_RESPONSE],
            out_len: 0,
            sent: 0,
            deadline: Instant::now() + Duration::from_millis(s.idle_ms),
            close_after_write: false,
        })
    }
    fn respond(&mut self, status: u8, payload: &[u8], s: &Settings, close: bool) {
        self.output[..HEADER].copy_from_slice(&[
            VERSION,
            status,
            (payload.len() >> 8) as u8,
            payload.len() as u8,
        ]);
        self.output[HEADER..HEADER + payload.len()].copy_from_slice(payload);
        self.out_len = HEADER + payload.len();
        self.sent = 0;
        self.close_after_write = close;
        self.deadline = Instant::now() + Duration::from_millis(s.write_ms);
    }
    fn step(
        &mut self,
        s: &Settings,
        server: &VoprfServer<Ristretto255>,
        bucket: &mut Bucket,
    ) -> io::Result<bool> {
        if Instant::now() >= self.deadline {
            return Ok(false);
        }
        if self.out_len > 0 {
            match self.stream.write(&self.output[self.sent..self.out_len]) {
                Ok(0) => return Ok(false),
                Ok(n) => self.sent += n,
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Ok(true),
                Err(e) => return Err(e),
            }
            if self.sent == self.out_len {
                if self.close_after_write {
                    return Ok(false);
                }
                self.used = 0;
                self.needed = HEADER;
                self.out_len = 0;
                self.deadline = Instant::now() + Duration::from_millis(s.idle_ms);
            }
            return Ok(true);
        }
        match self.stream.read(&mut self.input[self.used..self.needed]) {
            Ok(0) => return Ok(false),
            Ok(n) => {
                if self.used == 0 {
                    self.deadline = Instant::now() + Duration::from_millis(s.frame_ms);
                }
                self.used += n;
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Ok(true),
            Err(e) => return Err(e),
        }
        if self.used < self.needed {
            return Ok(true);
        }
        if self.needed == HEADER {
            // Charge every completed authenticated header, including invalid requests and public-key requests.
            if !bucket.take(Instant::now()) {
                self.respond(BUSY, &[], s, true);
                return Ok(true);
            }
            let length = u16::from_be_bytes([self.input[2], self.input[3]]) as usize;
            let expected = match self.input[1] {
                GET_PUBLIC_KEY => 0,
                BLIND_EVALUATE => ELEMENT_LENGTH,
                _ => {
                    self.respond(INVALID_REQUEST, &[], s, true);
                    return Ok(true);
                }
            };
            if self.input[0] != VERSION || length != expected {
                self.respond(INVALID_REQUEST, &[], s, true);
                return Ok(true);
            }
            self.needed = HEADER + expected;
            if expected > 0 {
                return Ok(true);
            }
        }
        if self.input[1] == GET_PUBLIC_KEY {
            self.respond(SUCCESS, &public_key(server), s, false);
        } else {
            // Synchronous execution: at most one active scalar multiplication. Disconnects
            // cannot release capacity early; this call must return before another can run.
            match evaluate_with_server(server, &self.input[HEADER..self.needed]) {
                Ok((element, proof)) => {
                    let mut payload = [0; ELEMENT_LENGTH + PROOF_LENGTH];
                    payload[..ELEMENT_LENGTH].copy_from_slice(&element);
                    payload[ELEMENT_LENGTH..].copy_from_slice(&proof);
                    self.respond(SUCCESS, &payload, s, false);
                }
                Err(OprfError::BlindedElement(_)) => self.respond(INVALID_ELEMENT, &[], s, false),
                Err(_) => self.respond(INTERNAL_ERROR, &[], s, true),
            }
        }
        Ok(true)
    }
}
fn serve(s: Settings, server: VoprfServer<Ristretto255>) -> io::Result<()> {
    let (listener, _guard) = bind(&s)?;
    // Handler only stores an atomic flag. No allocation, logging, or key access in signals.
    unsafe {
        if libc::signal(libc::SIGTERM, stop as *const () as libc::sighandler_t) == libc::SIG_ERR
            || libc::signal(libc::SIGINT, stop as *const () as libc::sighandler_t) == libc::SIG_ERR
            || libc::signal(libc::SIGPIPE, libc::SIG_IGN) == libc::SIG_ERR
        {
            return Err(io::Error::last_os_error());
        }
    }
    let mut clients = Vec::with_capacity(s.connections);
    let mut bucket = Bucket {
        tokens: s.burst as f64,
        last: Instant::now(),
        rate: s.rate as f64,
        burst: s.burst as f64,
    };
    while !STOP.load(Ordering::Relaxed) {
        // Bounded accept loop: an unauthenticated flood cannot starve existing clients.
        for _ in 0..s.connections {
            match listener.accept() {
                Ok((stream, _)) => {
                    if os::peer(&stream).map(|p| s.authorizes(&p)).unwrap_or(false)
                        && clients.len() < s.connections
                    {
                        clients.push(Connection::new(stream, &s)?);
                    }
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e),
            }
        }
        let mut index = 0;
        while index < clients.len() {
            let started = Instant::now();
            let keep = clients[index]
                .step(&s, &server, &mut bucket)
                .unwrap_or(false);
            let elapsed = started.elapsed();

            for (other, client) in clients.iter_mut().enumerate() {
                if other != index {
                    client.deadline += elapsed;
                }
            }

            if keep {
                index += 1;
            } else {
                clients.swap_remove(index);
            }
        }
        // poll avoids busy-spinning; readiness wakes immediately, deadlines are checked above.
        let mut pollfds = Vec::with_capacity(clients.len() + 1);
        pollfds.push(libc::pollfd {
            fd: listener.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        });
        for c in &clients {
            pollfds.push(libc::pollfd {
                fd: c.stream.as_raw_fd(),
                events: if c.out_len > 0 {
                    libc::POLLOUT
                } else {
                    libc::POLLIN
                },
                revents: 0,
            });
        }
        let result = unsafe { libc::poll(pollfds.as_mut_ptr(), pollfds.len() as libc::nfds_t, 10) };
        if result < 0 && io::Error::last_os_error().kind() != io::ErrorKind::Interrupted {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ipc_matches_original_core_for_same_key_and_blind() {
        let mut key = [0; ELEMENT_LENGTH];
        key[0] = 1;
        let server = server_from_key(&key).map_err(|e| e.to_string()).unwrap();
        let settings = Settings::parse(&[]).unwrap();
        let (mut client, socket) = UnixStream::pair().unwrap();
        client
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let mut connection = Connection::new(socket, &settings).unwrap();
        let mut bucket = Bucket {
            tokens: 1000.,
            last: Instant::now(),
            rate: 1000.,
            burst: 1000.,
        };
        let mut exchange = |opcode: u8, payload: &[u8], expected: usize| {
            client
                .write_all(&[VERSION, opcode, 0, payload.len() as u8])
                .unwrap();
            client.write_all(payload).unwrap();
            while connection.out_len == 0 {
                assert!(connection.step(&settings, &server, &mut bucket).unwrap());
            }
            assert!(connection.step(&settings, &server, &mut bucket).unwrap());
            let mut output = vec![0; HEADER + expected];
            client.read_exact(&mut output).unwrap();
            assert_eq!(&output[..HEADER], &[VERSION, SUCCESS, 0, expected as u8]);
            output[HEADER..].to_vec()
        };
        let public = exchange(GET_PUBLIC_KEY, &[], ELEMENT_LENGTH);
        assert_eq!(
            public,
            derive_public_key_inner(&key)
                .map_err(|e| e.to_string())
                .unwrap()
        );
        for input in [b"source".as_slice(), b"assertion", b"\0\xff"] {
            let (blind, state) = blind_inner(input).map_err(|e| e.to_string()).unwrap();
            let (old_element, old_proof) = evaluate_inner(&key, &blind)
                .map_err(|e| e.to_string())
                .unwrap();
            let new = exchange(BLIND_EVALUATE, &blind, ELEMENT_LENGTH + PROOF_LENGTH);
            assert_eq!(&new[..ELEMENT_LENGTH], old_element.as_slice());
            let old = finalize_inner(input, &state, &old_element, &old_proof, &public)
                .map_err(|e| e.to_string())
                .unwrap();
            let new = finalize_inner(
                input,
                &state,
                &new[..ELEMENT_LENGTH],
                &new[ELEMENT_LENGTH..],
                &public,
            )
            .map_err(|e| e.to_string())
            .unwrap();
            assert_eq!(old, new);
        }
    }
    #[test]
    fn rate_is_shared_and_refills() {
        let now = Instant::now();
        let mut b = Bucket {
            tokens: 2.,
            last: now,
            rate: 2.,
            burst: 2.,
        };
        assert!(b.take(now));
        assert!(b.take(now));
        assert!(!b.take(now));
        assert!(b.take(now + Duration::from_millis(500)));
        assert!(!b.take(now + Duration::from_millis(500)));
    }
    #[test]
    fn reserved_primary_group_only() {
        let client_uid = os::uid() + 1;
        let mut settings =
            Settings::parse(&["--client-uid".into(), client_uid.to_string()]).unwrap();
        let peer = |uid, gid| os::Peer {
            uid,
            gid,
            pid: Some(1),
        };
        assert!(settings.authorizes(&peer(client_uid, 2000)));
        assert!(!settings.authorizes(&peer(62000, 2001)));
        settings.session_gid = Some(2001);
        assert!(settings.authorizes(&peer(62000, 2001)));
        assert!(!settings.authorizes(&peer(62000, 2000)));
        assert!(!settings.authorizes(&peer(0, 2001)));
        assert!(!settings.authorizes(&peer(os::uid(), 2001)));
    }
    #[test]
    fn native_peer_credentials() {
        let (a, _b) = UnixStream::pair().unwrap();
        assert_eq!(os::peer(&a).unwrap().uid, os::uid());
    }
    #[test]
    fn header_sizes() {
        assert_eq!(MAX_REQUEST, 36);
        assert_eq!(MAX_RESPONSE, 100);
    }
}
