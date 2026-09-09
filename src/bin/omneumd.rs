#[cfg(any(target_os = "linux", target_os = "macos"))]
fn main() {
    use std::io::Write;
    // Do not let an unexpected library panic dump arguments or crypto state.
    std::panic::set_hook(Box::new(|_| {
        let _ = writeln!(std::io::stderr(), "omneumd: internal failure");
    }));
    if omneum_oprf::daemon::main_entry().is_err() {
        let _ = writeln!(std::io::stderr(), "omneumd: startup or service failure");
        std::process::exit(1);
    }
}
#[cfg(not(any(target_os = "linux", target_os = "macos")))]
fn main() {
    eprintln!("omneumd: protected serving requires Linux or macOS");
    std::process::exit(1);
}
