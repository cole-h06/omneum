"""Exact-version daemon distribution and installation orchestration.

Provisioning belongs exclusively to the verified release's existing installers.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
from importlib.metadata import version as package_version
import io
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


RELEASE_BASE = "https://github.com/cole-h06/omneum/releases/download"
PLATFORMS = ("linux-x86_64", "macos-aarch64", "macos-x86_64")
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 768 * 1024 * 1024
MAX_MANIFEST = 16 * 1024
ADMIN_DOCS = "https://github.com/cole-h06/omneum/blob/main/deploy/README.md"


class InstallError(Exception):
    """An actionable installation failure, safe to display without a traceback."""


def detect_platform() -> str:
    system, machine = platform.system(), platform.machine().lower()
    mapped = {("Darwin", "arm64"): "macos-aarch64",
              ("Darwin", "aarch64"): "macos-aarch64",
              ("Darwin", "x86_64"): "macos-x86_64",
              ("Linux", "x86_64"): "linux-x86_64"}.get((system, machine))
    if mapped is None:
        raise InstallError(f"Daemon installation is not supported on {system} {machine}. "
                           "Supported: macOS arm64/x86_64 and Linux x86_64.")
    return mapped


def release_assets(version: str, target: str) -> tuple[str, str, str]:
    if not re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]*", version) or target not in PLATFORMS:
        raise InstallError("Invalid installed package version or daemon platform.")
    name = f"omneum-daemon-{version}-{target}.tar.gz"
    base = f"{RELEASE_BASE}/v{version}"
    return name, f"{base}/SHA256SUMS", f"{base}/{name}"


def _https_release_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {
        "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
    } or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise InstallError("Release download redirected outside trusted GitHub HTTPS hosts.")


class ReleaseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https_release_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, limit: int) -> bytes:
    # Only canonical release assets may initiate a request. Redirects are HTTPS-only.
    _https_release_url(url)
    suffix = url.removeprefix(RELEASE_BASE + "/")
    parts = suffix.split("/")
    if len(parts) != 2 or not parts[0].startswith("v"):
        raise InstallError("Only canonical Omneum release assets may be downloaded.")
    allowed = {asset for target in PLATFORMS
               for asset in release_assets(parts[0][1:], target)[1:]}
    if url not in allowed:
        raise InstallError("Only exact-version Omneum release assets may be downloaded.")
    try:
        request = Request(url, headers={"User-Agent": "omneum-installer"})
        with build_opener(ReleaseRedirects()).open(request, timeout=30) as response:
            _https_release_url(response.geturl())
            data = response.read(limit + 1)
        if not data or len(data) > limit:
            raise InstallError("Release asset is empty or exceeds the download size limit.")
        return data
    except HTTPError as error:
        if error.code == 404:
            raise InstallError("No daemon release is available for this exact Omneum version. "
                               "Install a package version with published daemon assets.") from None
        raise InstallError(f"GitHub release download failed (HTTP {error.code}). Try again later.") from None
    except (URLError, OSError, ValueError):
        raise InstallError("Unable to download the release securely. Check your network and HTTPS certificates.") from None


def verify_checksum(manifest: bytes, archive: bytes, version: str, target: str) -> None:
    selected, _, _ = release_assets(version, target)
    expected = {release_assets(version, p)[0] for p in PLATFORMS}
    try:
        text = manifest.decode("ascii")
    except UnicodeDecodeError:
        raise InstallError("Release checksum manifest is malformed.") from None
    entries = {}
    if not text.endswith("\n") or len(manifest) > MAX_MANIFEST:
        raise InstallError("Release checksum manifest is malformed.")
    for line in text.split("\n")[:-1]:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9.!+_-]+\.tar\.gz)", line)
        if match is None:
            raise InstallError("Release checksum manifest is malformed.")
        digest, name = match.groups()
        if name not in expected or name in entries:
            raise InstallError("Release checksum manifest has unexpected or duplicate entries.")
        entries[name] = digest
    if entries.keys() != expected:
        raise InstallError("Release checksum manifest is missing required assets.")
    if not hmac.compare_digest(entries[selected], hashlib.sha256(archive).hexdigest()):
        raise InstallError("Daemon archive checksum mismatch. Nothing was installed; retry the download.")


def bundle_layout(target: str) -> dict[str, int]:
    if target not in PLATFORMS:
        raise InstallError("Unsupported daemon platform.")
    if target == "linux-x86_64":
        return {"omneumd": 0o755, "install.sh": 0o755, "install-foreground.sh": 0o755,
                "systemd": 0o755, "systemd/omneumd.service": 0o644,
                "sysusers.d": 0o755, "sysusers.d/omneum.conf": 0o644,
                "omneum-server": 0o755,
                "install-server.sh": 0o755,
                "install_server.py": 0o644,
                "install-linux.py": 0o644,
                "runtime_bundle.py": 0o644,
                "runtime.tar.gz": 0o644,
                "systemd/omneum-server.socket": 0o644,
                "systemd/omneum-server@.service": 0o644,
                "sysusers.d/omneum-server.conf": 0o644,
                }
    return {"omneumd": 0o755, "install-macos.sh": 0o755,
            "launchd": 0o755, "launchd/ai.omneum.omneumd.plist": 0o644}


def extract_bundle(archive: bytes, destination: Path, target: str, version: str | None = None) -> None:
    """Validate every member before writing; never use tarfile.extract/extractall."""
    expected = bundle_layout(target)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(archive)) as compressed:
            expanded = compressed.read(MAX_EXPANDED + 1)
        if len(expanded) > MAX_EXPANDED:
            raise InstallError("Daemon archive exceeds the extraction size limit.")
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as bundle:
            members = {}
            for member in bundle:
                name = member.name
                directory = name in {"systemd", "sysusers.d", "launchd"}
                if (name not in expected or name in members or member.pax_headers or member.linkname
                        or member.mode != expected[name] or member.uid != 0 or member.gid != 0
                        or (not member.isdir() if directory else not member.isfile())
                        or (directory and member.size != 0)
                        or (not directory and not 0 < member.size <= MAX_EXPANDED)):
                    raise InstallError("Daemon archive violates the expected release layout.")
                members[name] = member
            if members.keys() != expected.keys():
                raise InstallError("Daemon archive is missing required installation assets.")
            if target == "linux-x86_64":
                from .runtime_bundle import unpack
                with bundle.extractfile(members["runtime.tar.gz"]) as runtime:
                    unpack(runtime, version=version)
            destination.mkdir(mode=0o700)  # Must be a new directory in our private temporary tree.
            for name in sorted(members):
                member = members[name]
                output = destination / name
                if member.isdir():
                    output.mkdir(mode=0o700)
                else:
                    with bundle.extractfile(member) as source, output.open("xb") as sink:
                        shutil.copyfileobj(source, sink)
                    output.chmod(expected[name])
    except (tarfile.TarError, OSError, EOFError, ValueError):
        raise InstallError("Unable to safely extract the daemon release archive.") from None


def installer_command(bundle: Path, target: str, uid: int, *, systemd: bool) -> list[str]:
    if target.startswith("macos-") and target in PLATFORMS:
        if uid <= 0:
            raise InstallError("Run 'omneum install' as your normal login user, without sudo.")
        return ["/bin/sh", str(bundle / "install-macos.sh"), str(bundle / "omneumd"), str(uid)]
    if target == "linux-x86_64":
        if not systemd:
            raise InstallError("This Linux host has no running systemd service manager. "
                               "The foreground installer does not start a persistent service. "
                               f"Use an administrator-managed foreground deployment: {ADMIN_DOCS}")
        return ["/bin/sh", str(bundle / "install.sh"), str(bundle / "omneumd")]
    raise InstallError("Unsupported daemon platform.")


def deploy_bundle(bundle: Path, target: str) -> None:
    command = installer_command(bundle, target, os.getuid(), systemd=Path("/run/systemd/system").is_dir())
    if target == "linux-x86_64":
        command = ["/usr/bin/python3", "-I", "-B", str(bundle / "install-linux.py"),
                   str(bundle), str(os.getuid()), package_version("omneum")]
    if not Path("/usr/bin/sudo").is_file():
        raise InstallError("Administrator authorization requires sudo. Ask your administrator to install it.")
    # A cloud/CI account may authorize commands without a password while its
    # sudo verifypw policy still requires one for -v. Probe an innocuous command
    # first; interactive authorization remains necessary when it is denied.
    authorized = subprocess.run(["/usr/bin/sudo", "-n", "--", "/usr/bin/true"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                check=False).returncode == 0
    # Keep the password prompt on the terminal; never capture or handle credentials.
    if not authorized and subprocess.run(["/usr/bin/sudo", "-v"], check=False).returncode:
        raise InstallError("Administrator authorization failed. Retry with an account allowed to use sudo.")
    result = subprocess.run(["/usr/bin/sudo", "-n", "--", *command],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        # Existing installers can emit lengthy service logs; retain a bounded diagnostic.
        diagnostic = next((line for line in result.stderr.splitlines()
                           if line.startswith(("install:", "install-macos:"))), "")
        raise InstallError("Protected daemon installation failed. " +
                           (diagnostic or f"Ask your administrator to inspect the service. See {ADMIN_DOCS}"))


def verify_connection() -> None:
    from .config import load_deployment_state
    from .oprf import VOPRFClient

    state = load_deployment_state()  # Validates the existing pin and OS peer identity.
    client = VOPRFClient(state.voprf_server.public_key)
    probe = b"Omneum installation verification"
    blinded = client.blind(probe)
    evaluation = state.voprf_server.evaluate(blinded.blinded_element)
    client.finalize(input_data=probe, client_state=blinded.client_state, evaluation=evaluation)


def install_release(target: str, progress) -> None:
    """Retrieve, verify and deploy one exact-version bundle, cleaning up on all exits."""
    try:
        version = package_version("omneum")
    except Exception:
        raise InstallError("Cannot determine the installed Omneum version. Reinstall the Python package.") from None
    _, manifest_url, archive_url = release_assets(version, target)
    progress(f"Downloading Omneum daemon {version}...")
    manifest = download(manifest_url, MAX_MANIFEST)
    archive = download(archive_url, MAX_ARCHIVE)
    progress("Verifying release...")
    verify_checksum(manifest, archive, version, target)
    with tempfile.TemporaryDirectory(prefix="omneum-install-") as temporary:
        bundle = Path(temporary) / "bundle"
        extract_bundle(archive, bundle, target, version)
        progress("Installing and initializing protected services..." if target == "linux-x86_64" else "Installing protected daemon...")
        deploy_bundle(bundle, target)


def finish_install(initialize, verify, progress) -> None:
    progress("Initializing Omneum...")
    try:
        initialize()
    except Exception:
        raise InstallError("Daemon deployed, but Omneum initialization failed. "
                           "Check daemon access and the existing configuration; its key pin was not replaced.") from None
    progress("Verifying connection...")
    try:
        verify()
    except Exception:
        raise InstallError("Daemon deployed, but connection verification failed. "
                           "Check service status and the existing daemon key pin before retrying.") from None
    progress("Omneum is ready.")


def run_install(progress) -> None:
    from .initialization import initialize

    target = detect_platform()
    label = {"macos-aarch64": "macOS arm64", "macos-x86_64": "macOS x86_64",
             "linux-x86_64": "Linux x86_64"}[target]
    progress(f"Detecting platform... {label}")
    if target == "linux-x86_64" and not Path("/run/systemd/system").is_dir():
        installer_command(Path("."), target, os.getuid(), systemd=False)
    if os.geteuid() == 0:
        raise InstallError("Run 'omneum install' as your normal login user, without sudo. "
                           "Omneum will request administrator authorization when needed.")
    if any(name in os.environ for name in ("OMNEUM_DAEMON_UID", "OMNEUM_DAEMON_SOCKET")):
        raise InstallError("Unset OMNEUM_DAEMON_UID and OMNEUM_DAEMON_SOCKET before installing. "
                           "Installation verifies the protected system daemon.")
    install_release(target, progress)
    if target == "linux-x86_64":
        # The Linux installer already ran init as omneum-mcp.
        progress("Verifying connection...")
        try:
            verify_managed_connection()
        except Exception:
            raise InstallError("Managed server installed, but end-user verification failed. "
                               "Check the public configuration pin and managed service status before retrying.") from None
        progress("Omneum is ready.")
    else:
        finish_install(initialize, verify_connection, progress)


def verify_managed_connection() -> None:
    """Exercise the same public proxy and proof-verifying SDK that applications use."""
    import asyncio
    from omneum.mcp import StdioServerParameters
    from .client import OmneumClientConfig, open_stdio_client
    from .proxy import linux_command

    async def probe():
        command = linux_command()
        config = OmneumClientConfig.from_local_deployment()
        async with open_stdio_client(config, StdioServerParameters(command=command[0], args=command[1:])) as client:
            await client.link_claim('service', 'omneum', 'connection', 'verified')
    async def bounded():
        await asyncio.wait_for(probe(), timeout=30)
    asyncio.run(bounded())
