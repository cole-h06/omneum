fn main() {
    // Cargo also builds the cdylib when testing the shared rlib. Python symbols
    // are supplied by the importing interpreter, as in Maturin's macOS build.
    // Limit these flags to the extension cdylib; never weaken daemon linking.
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos")
        && std::env::var_os("CARGO_FEATURE_EXTENSION_MODULE").is_some()
    {
        println!("cargo:rustc-link-arg-cdylib=-undefined");
        println!("cargo:rustc-link-arg-cdylib=dynamic_lookup");
    }
}
