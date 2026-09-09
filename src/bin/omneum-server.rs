//! Opaque stdio transport. No application protocol or privileged operations.
#[cfg(unix)]
fn main() {
    use std::io::{self, Read, Write};
    use std::net::Shutdown;
    use std::os::unix::net::UnixStream;
    fn forward(mut input: impl Read, mut output: impl Write) -> io::Result<()> {
        let mut buffer = [0; 16384];
        loop {
            let size = match input.read(&mut buffer) {
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                result => result?,
            };
            if size == 0 {
                return Ok(());
            }
            output.write_all(&buffer[..size])?;
            output.flush()?;
        }
    }
    fn run() -> io::Result<()> {
        let mut stream = UnixStream::connect("/run/omneum-server.sock")?;
        let mut input = stream.try_clone()?;
        // Two bounded streaming copies preserve full-duplex backpressure. If the
        // server closes first, main exits without waiting for a blocked stdin.
        std::thread::spawn(move || match forward(io::stdin().lock(), &mut input) {
            Ok(_) => {
                let _ = input.shutdown(Shutdown::Write);
            }
            Err(_) => {
                let _ = input.shutdown(Shutdown::Both);
            }
        });
        forward(&mut stream, io::stdout().lock())?;
        io::stdout().flush()?;
        Ok(())
    }
    if run().is_err() {
        eprintln!("omneum-server: connection failed");
        std::process::exit(1);
    }
}
#[cfg(not(unix))]
fn main() {
    eprintln!("omneum-server: Linux installation required");
    std::process::exit(1);
}
