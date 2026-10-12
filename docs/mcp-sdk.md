# Bundled MCP SDK and optional asymmetric authentication

Omneum includes an upstream-compatible MCP Python SDK fork as `omneum.mcp`.
The local installation remains:

```bash
pip install omneum
omneum install
```

For Python stdio client parameters, use:

```python
from omneum.mcp import StdioServerParameters
```

The SDK retains initialization, capability negotiation, sessions, protocol
models, tool discovery/invocation, structured results, FastMCP and stdio. Omneum
still bounds incoming frames, suppresses protocol logs, validates the pinned
deployment and verifies VOPRF transcripts. Independent official SDK clients can
communicate with its server; their compatible `StdioServerParameters` objects
also work with `open_stdio_client`.

## Architecture decision

A separate PyPI SDK fork would require a second public release and, if it kept
the `mcp` import namespace, could collide with the official distribution. A
namespaced separate fork avoids that collision but still adds a release
dependency. A hand-written or selectively copied stdio implementation would
require maintaining protocol behavior and an evolving import closure.

The selected approach bundles the namespaced upstream fork in Omneum's own
wheel and sdist. It has the same small reproducible patch as a separate fork,
without a second distribution or protocol reimplementation. The entire released
SDK source is retained (110 Python files, approximately 20,861 lines), including
modules not used by Omneum's stdio path. This trades package size and security
update responsibility for a straightforward, auditable upstream refresh. It is
not a new implementation of the protocol.

All external core requirements resolve from public PyPI. The SDK source is
already in the Omneum artifact; end users never download a source archive,
install another SDK wheel, use a private index or compile dependencies. The
normal Omneum release must still publish its native platform/Python wheel matrix
and exact-version daemon assets before the two-command contract is public.

## Crypto boundary

Local MCP stdio/VOPRF operation does not require Python cryptography. The base
installation retains secure pure-Python `PyJWT>=2.15.0,<3`. Asymmetric SDK OAuth
and operator account enrollment require:

```bash
pip install 'omneum[oauth]'
```

That extra requires `PyJWT[crypto]>=2.15.0,<3` and `cryptography>=50.0.1`.
The backend is currently installable from public wheels on macOS arm64 and
Linux x86_64. Public patched cryptography wheels are unavailable on macOS Intel;
asymmetric OAuth/account authentication is consequently unavailable there
without changing that upstream distribution situation. This does not affect
the local stdio contract. Omneum's account enrollment service is an operator
Linux deployment, with its own pinned secure requirements.

Both SDK asymmetric signing APIs, `OIDCAuthenticator` construction and operator
JWKS validation raise `CryptoDependencyError` when the backend is missing or
below the security minimum. No signature validation, algorithm selection,
issuer/audience checks or VOPRF operation is bypassed. Prebuilt OAuth assertions
and existing non-asymmetric OAuth behavior retain their upstream semantics.
The WebSocket SDK extra, when needed, is `omneum[mcp-ws]`.

## Exact source and patch

- Repository: <https://github.com/modelcontextprotocol/python-sdk>
- Release: `v1.28.1`, matching the original Omneum candidate lockfile.
- Commit: `777b8d06710c140e3606b0d4598e2aa48546c266`.
- Public source archive: URL in `omneum/mcp/UPSTREAM.json`.
- Source SHA256: `d51e36a5f5644faea4f85ea649bfffa6bc6c26770d42798ad6a3de3d2ba69683`.
- Original MIT license: `omneum/mcp/LICENSE`, also included in distribution
  license metadata. Original dependency metadata: `UPSTREAM-PYPROJECT.toml`,
  with upstream hosted-runner coverage aliases normalized to `/build/upstream`.

`tools/vendor_mcp.py:patch` contains the complete changes:

1. Rewrite absolute SDK imports from `mcp` to `omneum.mcp`, retaining local
   aliases, and normalize trailing source whitespace. Protocol names, models
   and wire literals are unchanged.
2. Replace four distribution-version lookups with the pinned upstream version;
   there is no `mcp.dist-info` in a core install.
3. Guard the two asymmetric signing paths with Omneum's secure backend check.
   PyJWT performs the same signing operation after that check.
4. Normalize the upstream coverage configuration's two hosted-runner aliases
   in the metadata snapshot. The artifact privacy guard remains unchanged.

Dependency separation is expressed in Omneum metadata: upstream non-crypto
requirements are declared directly, with the existing Omneum security floors
and SDK Python-version requirements retained. Core has no `mcp` or cryptography
requirement. The lockfile retains the official SDK for optional third-party
framework examples, but its exported core graph contains neither package.
Those framework groups have their own dependency contracts and are not part of
the two-command local installation.

## Reproduction and updates

Use a development machine, not an end-user installation:

```bash
curl --fail --location --proto '=https' --proto-redir '=https' \
  https://files.pythonhosted.org/packages/6e/77/9450b8f251a13affb6281997d0523c4615f8a8b35d0b21ff30db3a5aac9d/mcp-1.28.1.tar.gz \
  --output /tmp/mcp-1.28.1.tar.gz
python3 tools/vendor_mcp.py /tmp/mcp-1.28.1.tar.gz --check
uv lock --check
uv sync --locked --group auth-test
uv run --locked --group auth-test --group langgraph pytest
maturin build --locked --release --out dist --interpreter python3
python3 tools/release_wheels.py sanitize --wheels dist
python3 tools/check_mcp_bundle.py 'dist/*.whl'
maturin sdist --out source-dist
python3 tools/check_mcp_bundle.py 'source-dist/*.tar.gz'
```

The generator verifies the source hash before reading it. Without `--check` it
regenerates all source files and the per-file manifest deterministically. The
checker verifies every SDK byte in the built wheel/sdist. CI checks the source
against the pinned public archive and retains all twelve real installation
acceptance cells. Native builds must also use the existing path-remapping
settings and pinned Rust/maturin toolchains from the release workflow.

Before every Omneum release, check upstream v1 security advisories and releases.
Apply critical security fixes promptly; bundling makes this Omneum's
responsibility. To upgrade, explicitly change the source version, tag commit,
archive URL and SHA in the generator, review upstream release/dependency changes,
regenerate and compare the complete diff. Patch-context checks intentionally
fail when the signed JWT APIs or version lookups change. Refresh the dependency
metadata/lockfile and run crypto-boundary, independent-peer, stdio/VOPRF,
artifact and twelve-target fresh-host tests again. Never edit generated SDK
files by hand. The CI source check rejects such drift.

If a released supported upstream SDK later makes crypto optional, evaluate
returning to it while retaining the `omneum.mcp` public compatibility surface.
No upstream release is assumed in the present implementation.
