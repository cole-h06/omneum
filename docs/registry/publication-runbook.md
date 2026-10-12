# Omneum 1.0.3 registry readiness

Checked 2026-10-11 against current official documentation. Integration branch:
`feat/mcp-registry-readiness-1.0.3`, based on fetched `origin/main` at `a40b564`,
in `/private/tmp/omneum-registry-integration-1.0.3`. Changes were reviewed from
`c7a3a39` and applied without importing unrelated local-main commits.
The active release candidate and original registry branch are untouched; the
integration is prepared for PR review, not merged. No package, listing, tag, DNS record,
service, repository setting, or credential was published or changed.

## Completed locally

- Official identity stays **`ai.omneum/omneum`**; package stays **`omneum==1.0.3`**.
- Installed `mcp-publisher` **1.8.1** accepted both the original and prepared
  `server.json` against `https://registry.modelcontextprotocol.io`. No original
  schema error was reported. Full downloaded JSON Schema validation also passed.
- Manifest now names the stdio executable explicitly through supported runtime
  arguments, adds the official PyPI base URL and installation guide, and states
  the local daemon prerequisite. Intended command:
  `uvx --from omneum==1.0.3 omneum-server`. Clients must honor the executable override;
  running the package's default `omneum` CLI does not start MCP. The documented,
  installed-client command remains `omneum-server` after `omneum install`.
- Added `<!-- mcp-name: ai.omneum/omneum -->` to `README.md`, the
  `pyproject.toml` published-description source. Fresh diagnostic CPython 3.13
  macOS arm64 wheel `METADATA` and sdist `PKG-INFO` both contain the exact marker.
  The ownership requirement comes from the official [PyPI package guide](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx).
- `tools/registry_readiness.py` checks Python/Rust/manifest versions, package and
  repository identifiers, installation URL, source entry points, built metadata,
  and Glama metadata. Public-release mode additionally requires exact-version
  PyPI JSON, the marker, non-yanked files, wheel and sdist availability, trusted
  artifact URLs, SHA-256 digests, artifact metadata, and wheel console scripts.
  It downloads one wheel and the sdist for inspection without installing them.
- Separate manually dispatched read-only registry checks build and inspect distributions.
  Both registry workflows are inert on ordinary push/PR CI. The existing release
  `CI.yml`, dependency files, runtime and security code match origin/main byte for
  byte; README changes consist only of the ownership comment prefix. The
  dispatch-only publishing workflow has no CI-success, tag, release, or push
  publication trigger. It requires main, the canonical repository, exact version,
  identity confirmation, `publish=true`, and the `mcp-registry` environment.
  It checks independent reviewer configuration before and after approval, pins
  both checkouts to the dispatch SHA, explicitly checks the dispatch event,
  disables tracing before signing, and repeats PyPI checks before authentication.
  The signing seed is scoped to the final step, never written to an artifact, and
  the publisher logout cleanup runs on exit. Key preparation refuses all Git
  worktrees, including sibling checkouts. Official publisher downloads are
  version- and SHA-256-pinned. No OIDC or repository write permissions are needed.
- Local validation: **17 registry regression tests**, **42 existing release tests**,
  fresh wheel/sdist metadata checks, official manifest validation, shell syntax,
  and actionlint 1.7.12 for all three repository workflows passed. Full release acceptance and
  end-to-end installed-daemon tests remain with the independent release process.

## Domain verification and manual DNS instructions

`ai.omneum` requires proof of **`omneum.ai`**, using DNS or HTTPS authentication;
GitHub authentication/OIDC grants a different namespace and cannot substitute.
The official [authentication guide](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/authentication.mdx)
requires an Ed25519 public key encoded as base64 of its 32 raw bytes, paired with
an accessible private signing seed. Other documented signing methods exist, but
this prepared workflow deliberately uses Ed25519 DNS authentication.

A read-only `dig +short TXT omneum.ai` returned this existing apex record:

```text
omneum.ai. IN TXT "v=MCPv1; k=ed25519; p=0CmF+RNvW9561gTM/SaH35dPta6a4bK9mEIL3+jSGYk="
```

Reuse it if the corresponding private key is available. **Do not add a duplicate
MCP record.** If a new key is necessary, generate local material outside the repo:

```bash
OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl \
  bash tools/prepare_registry_auth.sh /private/tmp/omneum-registry-private
```

Use a durable private directory for real credentials; the path above is an
example. Linux can omit `OPENSSL` when its default OpenSSL supports Ed25519.
The helper creates a permission-restricted key, 64-character hex private seed,
public HTTPS proof file, and ready-to-copy DNS record. It does not authenticate,
modify DNS, deploy a file, or submit anything. Only disposable test keys were
created during validation and were removed afterward.

For a manual DNS update, use the generated `dns-record.txt`: type **TXT**, zone
**omneum.ai**, host/name **@** (or the provider's apex notation), value
**`v=MCPv1; k=ed25519; p=<generated base64 public key>`**, TTL **300 seconds**
(an operational suggestion, not a protocol requirement). Replace an old MCP
proof if rotating keys; preserve unrelated TXT records. Wait for propagation,
then verify with `dig +short TXT omneum.ai`. Never put the proof under a selector
such as `_mcp-registry.omneum.ai`, and never publish the private key.

HTTPS is an alternative: manually serve the generated `mcp-registry-auth` file
at **`https://omneum.ai/.well-known/mcp-registry-auth`**, containing the same
single public proof line. It needs public DNS, valid TLS and a direct **200**;
redirects are rejected, private addresses are blocked, and the response limit is
4096 bytes. These details are confirmed in the official [HTTP authentication implementation](https://github.com/modelcontextprotocol/registry/blob/v1.8.1/internal/api/handlers/v0/auth/http.go).
The local HTTPS request could not resolve `omneum.ai`; HTTP proof availability
was therefore **not verified**. No endpoint was deployed. For HTTPS auth, use
`login http` in the manual commands below; the prepared workflow uses DNS.

## Discovery services

**Glama:** Root `glama.json` contains only the live schema's supported
`$schema` and `maintainers: ["cole-h06"]`. No runtime dependency was added.
The [live schema](https://glama.ai/mcp/schemas/server.json) currently defines
`maintainers` only, despite broader wording in the FAQ. Supply display name
**Omneum**, repository **https://github.com/cole-h06/omneum**, and the manifest's
short description in the submission UI. Claim/update ownership after the file
is public; the [metadata guide](https://glama.ai/blog/2025-07-08-what-is-glamajson)
describes this flow. Submission requires GitHub OAuth with write/admin access.
Glama imports official registry entries, but search distribution requires a
successful reproducible sandbox build and protocol introspection. See its
[indexing methodology](https://glama.ai/mcp/methodology). Omneum's managed daemon,
service identity and installation privileges make sandbox compatibility a
remaining validation task. No Dockerfile claiming to pass Glama was invented;
no key isolation or installation gate was relaxed to accommodate indexing.

**Smithery:** **Yes, the architecture can stay local stdio.** The current
[publishing guide](https://smithery.ai/docs/build/publish) explicitly supports
prebuilt `.mcpb` bundles; its [release API](https://smithery.ai/docs/api-reference/servers/publish-a-server)
accepts a multipart `bundle` for stdio releases. This is distribution to local
clients, not a requirement to host Omneum over HTTP. A PyPI package or legacy
`smithery.yaml` alone is not the documented local publishing route. No Smithery
runtime dependency or remote service is needed. A tested MCPB artifact remains
necessary: it must preserve the external daemon installation prerequisite,
platform support, pinned native dependencies and privilege separation.
The official [MCPB manifest specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)
defines Python/binary packaging and a newer UV option; Smithery's guide does not
establish support for every MCPB/runtime revision. Confirm the chosen format
with Smithery and test local installation before uploading. No bundle was
submitted and no successful Smithery scan is claimed.

## Remaining blockers and credentials

1. **Public PyPI 1.0.3 is unavailable:** its exact-version JSON returned 404, and
   `--pypi` correctly exited nonzero. Release acceptance proceeds independently.
2. **Earlier local candidate wheels lacked the marker.** Accepted independent
   release artifacts still require verification. This branch's marker
   must reach the published-description source through the separately reviewed
   release process before artifacts are built/published. Diagnostic builds here
   are not release artifacts. Do not submit the registry entry until the live
   description and downloaded metadata pass; do not overwrite published files.
3. Review and merge the integration PR before dispatching from main. The
   environment GET returned **404**; reviewer protection is not verified. Provision the
   `mcp-registry` environment with at least one independent required reviewer,
   prevent self-review, disable administrator bypass, and restrict deployment to
   main. If the repository's plan/visibility cannot support reviewer protection,
   the workflow remains blocked; do not change visibility or weaken the gate.
   GitHub documents availability and the read-only verification API in its
   [environment reference](https://docs.github.com/en/rest/deployments/environments#get-an-environment).
4. Supply the **64-character lowercase hex Ed25519 private seed matching the
   apex TXT public key** as **environment-only** `MCP_REGISTRY_PRIVATE_KEY`.
   Do not create a repository/org secret of that name. DNS authority is needed
   only for a key rotation. The existing DNS record does not prove possession of
   its private key; no authenticated login was attempted.
5. Glama needs a maintainer's GitHub OAuth session and a successful sandbox scan.
   Smithery needs a namespace/account, an API key or authenticated CLI, and a
   validated MCPB artifact. Neither credential is needed for official-registry
   preflight. No listing or external account configuration was changed.

## Exact release-day commands (future authorized actions)

From the reviewed checkout, after independent PyPI release acceptance and the
protected environment are ready:

```bash
python3 tools/registry_readiness.py --version 1.0.3 --pypi
mcp-publisher validate server.json

# Preflight only; cannot publish.
gh workflow run registry-publish.yml --repo cole-h06/omneum --ref main \
  -f version=1.0.3 -f identity=ai.omneum/omneum -f publish=false

# Only when submission is explicitly authorized; approve the environment job.
gh workflow run registry-publish.yml --repo cole-h06/omneum --ref main \
  -f version=1.0.3 -f identity=ai.omneum/omneum -f publish=true
```

Alternatively, for a separately authorized manual submission with the matching
private seed stored securely outside the repository (do not run both routes):

```bash
set +x
python3 tools/registry_readiness.py --version 1.0.3 --pypi
mcp-publisher validate server.json
MCP_REGISTRY_PRIVATE_KEY=$(cat /private/tmp/omneum-registry-private/private-key.hex)
mcp-publisher login dns --domain omneum.ai --private-key "$MCP_REGISTRY_PRIVATE_KEY" \
  --registry https://registry.modelcontextprotocol.io
mcp-publisher publish server.json
mcp-publisher logout
unset MCP_REGISTRY_PRIVATE_KEY
```

For Smithery, **after** a compatible bundle has been built, tested and authorized:
`smithery mcp publish ./server.mcpb -n <owned-namespace>/omneum`.
Glama's current official submission route is its Add MCP Server UI; no
undocumented submission API is included.
