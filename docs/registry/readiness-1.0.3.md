# Omneum 1.0.3 registry readiness

Integrated 2026-10-11 on `feat/mcp-registry-readiness-1.0.3` from fetched
`origin/main` **`a40b5649d55446dff184db8fb75de4a6b1e0b999`**, in
`/private/tmp/omneum-registry-integration-1.0.3`. Registry source: `c7a3a39`.
A clean branch carries only the registry changes; no rebase or shared-history
rewrite occurred. The original registry worktree and active release candidate
remain unchanged. The five unrelated local-main commits were not imported.
The integration is prepared for review and has not been merged.
No external publication, DNS update, deployment, tag, credential configuration,
or repository visibility change was performed.

| Area | Result |
| --- | --- |
| Official identity | Preserved `ai.omneum/omneum`; PyPI package `omneum`, version `1.0.3`. |
| Manifest | Original and prepared manifests pass `mcp-publisher` 1.8.1; prepared manifest also passes the full official JSON Schema. Added explicit `omneum-server` launch hints and installation guidance. |
| Ownership marker | Added to the README description source; verified in freshly built wheel `METADATA` and sdist `PKG-INFO`. Earlier local candidate wheels lacked it; independent accepted release artifacts still need verification. |
| Automated checks | Version/identity/URLs/entry points, built metadata, public PyPI release files and hashes, and publication failure cases covered. 17 registry tests and 42 existing release tests pass; all three repository workflows pass actionlint. |
| Publishing gate | Manual main-only dispatch, exact version and identity confirmation, `publish=true`, independent environment review, checksum-pinned publisher, and PyPI verification repeated after approval. Both registry workflows are dispatch-only and remain inert on push/PR; CI success cannot trigger publication. |
| Glama | Added schema-supported maintainer metadata only; no dependencies. Discoverability still requires a successful sandbox build and MCP scan. |
| Smithery | Current docs support local stdio through MCPB. Architecture can remain unchanged; a compatible tested bundle and daemon prerequisite handling are still needed. |

The [official PyPI ownership requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx),
[Glama metadata schema](https://glama.ai/mcp/schemas/server.json),
[Glama indexing requirements](https://glama.ai/mcp/methodology), and
[Smithery publishing guide](https://smithery.ai/docs/build/publish) informed these changes.

Remaining blockers:

1. PyPI's exact 1.0.3 endpoint currently returns **404**. Independent release
   acceptance remains authoritative. The reviewed marker change must reach the
   release build source; this worktree's diagnostic artifacts must not be published.
2. Review and merge the integration PR, then configure `mcp-registry` with an independent
   reviewer, prevent self-review/admin bypass, and restrict deployment to main.
   The environment GET returned **404** during integration; reviewer protection
   is not verified. The workflow fails closed if independent review is absent.
3. Supply the matching **64-character lowercase hex Ed25519 seed** as the
   environment-only secret `MCP_REGISTRY_PRIVATE_KEY`. Do not duplicate it as a
   repository or organization secret. No login was attempted.
4. Glama needs maintainer GitHub OAuth and successful sandbox introspection;
   Smithery needs an owned namespace, authenticated CLI/API key, and tested MCPB.
   Omneum's installed local daemon remains required; no security gate was relaxed.

DNS already contains this apex proof:

```text
omneum.ai. IN TXT "v=MCPv1; k=ed25519; p=0CmF+RNvW9561gTM/SaH35dPta6a4bK9mEIL3+jSGYk="
```

Reuse it with its matching private key. For rotation, manually replace only the
MCP TXT value at host **@** with the new public proof; never add a selector or
publish the private key. The [runbook](publication-runbook.md) includes secure
local key preparation, exact DNS fields, HTTPS verification requirements,
credential setup and an alternative manual publishing sequence. DNS was not
modified. The HTTPS endpoint could not be verified because the request could
not resolve the domain.

After the independent release and environment setup, run from the reviewed checkout:

```bash
python3 tools/registry_readiness.py --version 1.0.3 --pypi
mcp-publisher validate server.json

# Optional manually requested metadata/build checks; ordinary CI is inert.
gh workflow run registry-checks.yml --repo cole-h06/omneum --ref main

# Preflight only.
gh workflow run registry-publish.yml --repo cole-h06/omneum --ref main \
  -f version=1.0.3 -f identity=ai.omneum/omneum -f publish=false

# Future explicitly authorized submission; then approve the environment job.
gh workflow run registry-publish.yml --repo cole-h06/omneum --ref main \
  -f version=1.0.3 -f identity=ai.omneum/omneum -f publish=true
```

Changed files (12): `README.md`, `server.json`, `glama.json`;
`.github/workflows/registry-checks.yml`, `.github/workflows/registry-publish.yml`;
`tools/check_registry_environment.py`, `tools/install_mcp_publisher.sh`,
`tools/prepare_registry_auth.sh`, `tools/registry_readiness.py`,
`tools/test_registry_readiness.py`; this report and `publication-runbook.md`.
