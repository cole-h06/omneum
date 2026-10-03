import os
from pathlib import Path
import tomllib

import pytest

from omneum import OmneumClientConfig
from omneum.daemon import DaemonKeyMismatchError, DaemonServerContext

from . import deployment
from .run_suite import CASES, run_omneum


def test_temporary_deployment(monkeypatch, tmp_path):
    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path / "installed"))
    monkeypatch.setenv("OMNEUM_DAEMON_SOCKET", "/nonexistent/installed.sock")
    monkeypatch.setenv("OMNEUM_DAEMON_UID", "invalid")
    monkeypatch.setenv("OMNEUM_VOPRF_PUBLIC_KEY", "invalid")
    original_environment = dict(os.environ)

    with deployment.benchmark_deployment() as (config, server):
        directory = Path(server.env["OMNEUM_CONFIG_DIR"])
        socket_path = Path(server.env["OMNEUM_DAEMON_SOCKET"])
        saved = tomllib.loads((directory / "config.toml").read_text())
        assert saved["deployment_id"] == config.deployment_id
        assert "OMNEUM_VOPRF_PUBLIC_KEY" not in server.env
        assert DaemonServerContext(
            socket_path, os.getuid(), config.voprf_public_key,
        ).public_key == config.voprf_public_key
        # A different valid public-key pin must still be rejected.
        wrong_key = bytes.fromhex(
            "e2f2ae0a6abc4e71a884a961c500515f"
            "58e30b6aa582dd8db6a65945e08d2d76"
        )
        with pytest.raises(DaemonKeyMismatchError):
            DaemonServerContext(socket_path, os.getuid(), wrong_key)

    assert not directory.parent.exists()
    assert not (tmp_path / "installed").exists()
    assert dict(os.environ) == original_environment
    with deployment.benchmark_deployment() as (second, _):
        assert second == config


@pytest.mark.anyio
async def test_run_omneum_ignores_installed_deployment(monkeypatch, tmp_path):
    def forbidden():
        pytest.fail("Benchmark read the installed deployment")

    monkeypatch.setattr(OmneumClientConfig, "from_local_deployment", forbidden)
    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path / "installed"))
    monkeypatch.setenv("OMNEUM_DAEMON_SOCKET", "/nonexistent/installed.sock")
    monkeypatch.setenv("OMNEUM_DAEMON_UID", "invalid")
    result = await run_omneum(CASES[0])
    assert set(result) == {"result", "latency_ms"}
    assert result["result"].claim_support
    assert result["latency_ms"] > 0
    assert not (tmp_path / "installed").exists()


@pytest.mark.parametrize("startup_failure", [False, True])
def test_cleanup_on_failure(monkeypatch, startup_failure):
    processes = []
    popen = deployment.subprocess.Popen

    def record_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(deployment.subprocess, "Popen", record_process)
    if startup_failure:
        def fail(*args):
            raise RuntimeError("startup failure")
        monkeypatch.setattr(deployment, "_public_key", fail)

    with pytest.raises(RuntimeError):
        with deployment.benchmark_deployment():
            raise RuntimeError("evaluation failure")

    assert len(processes) == 1
    process = processes[0]
    assert process.poll() is not None
    key_dir = Path(process.args[process.args.index("--key-dir") + 1])
    assert not key_dir.parent.exists()
