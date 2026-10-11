# Fresh-user macOS acceptance attempt — 2026-10-11

**BLOCKED — fresh installation not tested; launch readiness not established.**

The available machine is the existing Darwin arm64 host. No accessible clean
macOS guest or disposable macOS runner was identified. Docker and QEMU binaries
are present, but no ready macOS guest, clean image, or guest access was found in
the checked locations. These checks do not prove that no VM exists elsewhere;
they establish that this session has no identified usable isolated macOS target.
A Python virtual environment, separate host login, or Linux container would not
isolate macOS machine-level services and does not satisfy this acceptance test.

Reviewed checkout: `4f17cb85b747d00e81d68d03d59c9bfa3da3bc50`, with pre-existing
working-tree changes. No published package was installed or executed. No host
Omneum command, daemon connection, launchctl operation, administrator prompt,
configuration write, key access, Auth0 request, or contribution was performed.
The only task-created artifact is this report. Existing changes were preserved.

## Acceptance status

| Required check | Status | Evidence still required |
| --- | --- | --- |
| Clean macOS environment that has never installed Omneum | Blocked | Disposable guest/runner and documented pristine baseline |
| PyPI `omneum==1.0.3`, Python 3.11–3.14 | Not run | Python version, public index resolution, installed wheel/dependencies and command transcript |
| `omneum install` from normal login | Not run | Real user session, complete installer output and exit status |
| Release download and SHA-256 validation | Not run | Exact v1.0.3 asset URLs, archive/manifest digests and verification output |
| Administrator authorization | Not run | Prompt occurrence/order and outcome; never record passwords |
| Daemon install and launchd startup | Not run | Installed paths, service identity, ownership/modes and launchd state |
| Protected VOPRF verification | Not run | Installer verification and proof validation through protected daemon; key-read denial by login/MCP identity |
| README `omneum-server` MCP configuration | Not run | Actual MCP client configuration, initialization and tool discovery |
| `ping` and assertion evaluation | Not run | Tool requests/responses and README evaluation example result |
| Local Context Graph persistence after process restarts | Not run | Saved observation IDs/rows before and after closing/reopening MCP/SDK processes |
| Network disabled by default | Not run | Runtime evaluation succeeds locally without enrollment and produces no contribution requests |
| Opt-in, Auth0, consent, enrollment, contribution | Deferred | Hosted production acceptance first, then real-provider end-to-end transcript |
| Blocker fixes and clean rerun | Not run | Reproduce on published artifacts, fix confirmed defect, publish corrected artifacts as needed, restore pristine guest and rerun |

Source inspection is not runtime acceptance. The existing
`tests/security/macos_install.py` harness explicitly requires a disposable host,
runs as root with repository dependencies, invokes `deploy/install-macos.sh`
directly, and writes production daemon paths. It cannot substitute for this
normal-login, public-PyPI acceptance flow and was not executed.

The prior [production security review](production-security-2026-10-11.md)
records a public PyPI installation failure, public package/release 404 responses,
and incomplete hosted production acceptance. Those are prior findings, not
fresh probes from this attempt. Current source inspection confirms both
`_PRODUCTION_NETWORK` and `_PRODUCTION_ONBOARDING` remain `None`. No values were
invented or injected to bypass provisioning. No new installation defect was
reproduced, and no installer fix or release publication was performed.

## Resume conditions and evidence

Provide an accessible disposable macOS VM/runner with a pristine snapshot and
normal login user able to authorize administration. Before installation, record
OS/architecture, Python version, absence of Omneum package, daemon, service
account, service files, configuration, database and VOPRF key directories. Keep
the existing host entirely outside the test target. Use a supported Python in
the guest; a full compatibility claim requires additional 3.11–3.14 runs.

Start terminal recording inside the guest before `python -m pip install
--index-url https://pypi.org/simple omneum==1.0.3`, then run `omneum install`
without sudo. Capture each command, prompt (without secrets), exit code, failure
and manual action. Configure an actual MCP client with the README's
`omneum-server` command and execute its documented evaluation example. Record
database evidence across separate process lifetimes. Verify default opt-out
with runtime request observation, rather than inferring it solely from source.

After hosted production acceptance is documented, run `omneum network enroll`
with a dedicated real Auth0 test identity and record consent/authentication and
enrollment outcomes. Use the documented `omneum-contributor` configuration with
explicit `OMNEUM_NETWORK_CONTRIBUTION=true`, reconnect MCP, submit a synthetic
new observation and verify accepted ingestion/persistence. Redact credentials,
account tokens and device codes. Record consent denial and subsequent opt-out
behavior as well. Restore the pristine guest for each required clean rerun.

## Command and intervention log

All commands below ran in `/Users/colehoke/Development/omneum` on the existing
host for read-only discovery. No interactive prompts occurred. Outputs are
summarized; failures and partial commands are retained. The tool-name metadata
was also inspected for remote-machine/environment capabilities; no such runner
was exposed. No manual intervention was made beyond replacing a failed zsh glob
check with the read-only Python directory check below.

1. Exit 0; repository path and relevant files listed:

   ```sh
   pwd && rg --files -g 'AGENTS.md' -g 'README.md' -g '*acceptance*' -g '*install*' -g '*release*' -g 'pyproject.toml' -g '*network*' -g '*launch*'
   ```

2. Exit 0; existing modifications in deploy requirements, installation/configuration/deployment docs, Network deployment code/tests, contributor/enrollment tests and uv.lock; untracked production audit, reviews and provenance explorer:

   ```sh
   git status --short
   ```

3. Exit 0 overall; Darwin 25.6.0 arm64. Docker, both QEMU binaries and Python found; tart, prlctl, VBoxManage and limactl not found:

   ```sh
   uname -a; command -v tart; command -v prlctl; command -v VBoxManage; command -v limactl; command -v docker; command -v qemu-system-aarch64; command -v qemu-system-x86_64; command -v python3
   ```

4. Exit 2; no ancestor AGENTS.md content found. Missing `.agents` and `.codex` produced rg errors. Found macOS/Linux security harness files:

   ```sh
   for p in /AGENTS.md /Users/AGENTS.md /Users/colehoke/AGENTS.md /Users/colehoke/Development/AGENTS.md /Users/colehoke/Development/omneum/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done; rg --files -g 'AGENTS.md' -g '*vm*' -g '*macos*' -g '*audit*' docs tests tools .agents .codex
   ```

5. Exit 1; README and harness read successfully. Application inventory did not run: zsh reported `no matches found: /Applications/*Parallels*`:

   ```sh
   cat README.md; sed -n '1,240p' tests/security/macos_install.py; ls -ld /Applications/*Parallels* /Applications/*VMware* /Applications/*UTM* /Applications/*VirtualBox* /Users/colehoke/.tart /Users/colehoke/.lima /Users/colehoke/Virtual\ Machines.localized /Users/colehoke/Library/Containers/com.utmapp.UTM 2>/dev/null
   ```

6. Exit 0; prior review and relevant readiness references located:

   ```sh
   ls docs/reviews; rg -n 'production acceptance|PASS|FAIL|macOS|fresh|Auth0|1.0.3' docs/reviews pyproject.toml docs/network-contribution.md docs/guides/installation.md
   ```

7. Exit 0; no matching virtualization app reported. All six checked VM inventory locations absent:

   ```sh
   python3 - <<'PY'
   from pathlib import Path
   apps = Path('/Applications')
   for p in sorted(apps.iterdir()):
       if any(x in p.name.lower() for x in ('tart','parallels','vmware','utm','virtualbox','virtualbuddy','orchard')):
           print('virtualization_app:', p)
   for name in ('.tart', '.lima', 'Virtual Machines.localized', 'Virtual Machines', 'Library/Containers/com.utmapp.UTM', 'Library/Application Support/VirtualBuddy'):
       p = Path('/Users/colehoke') / name
       print(str(p) + ': ' + ('present' if p.exists() else 'absent'))
       if p.is_dir():
           print('entries:', ', '.join(c.name for c in list(p.iterdir())[:20]))
   PY
   ```

8. Exit 0; prior review, installer and configuration docs read. Tool output was truncated at 9,500 tokens; relevant pin/installer sections were subsequently read separately:

   ```sh
   cat docs/reviews/production-security-2026-10-11.md; sed -n '1,240p' omneum/installation.py; sed -n '1,180p' docs/guides/configuration.md
   ```

9. Exit 0; recorded revision, installer checksum/deploy sequence and unprovisioned source pins:

   ```sh
   git rev-parse HEAD; sed -n '237,275p' omneum/installation.py; sed -n '1,100p' omneum/network_release.py; sed -n '1,90p' omneum/onboarding.py; sed -n '60,120p' omneum/contribution/network.py
   ```

10. `apply_patch` created this report. No application code or host installation changed.

11. Report-only verification command; checks whitespace and displays the new report status:

    ```sh
    git diff --check -- docs/reviews/fresh-user-macos-2026-10-11.md; git status --short -- docs/reviews/fresh-user-macos-2026-10-11.md
    ```

    Exit 0; report is untracked. `git diff --check` does not inspect untracked
    contents, so it provides no content validation of this new file.
