# Release-day directory and client discovery checklist

Checked against first-party sources on 2026-10-12. These are future manually
authorized actions; no listing, external directory PR, service, package, tag or
DNS change was submitted. Use the common description in
[submissions/common-description.md](submissions/common-description.md) and the
machine-readable [listing.json](listing.json).

## Common gate

Review the additive discovery PR and [PR #2](https://github.com/cole-h06/omneum/pull/2)
separately. Neither is merged. Complete the independent 1.0.3 release acceptance
and ensure the published PyPI description includes `mcp-name: ai.omneum/omneum`.
The exact PyPI 1.0.3 endpoint still returned 404. PR #2's protected official-registry
workflow remains the only prepared official-registry submission path; do not
copy its manifest/workflows or create a second registry identity.

From the reviewed combined checkout:

```bash
python3 tools/check_discovery.py --glama-json glama.json
python3 -m unittest discover -s tools -p 'test_discovery_*.py' -v
python3 tools/registry_readiness.py --version 1.0.3 --pypi
```

On a fresh supported test host, from the normal login account:

```bash
python -m pip install omneum
omneum install
command -v omneum-server
python -c 'import importlib.metadata; print(importlib.metadata.version("omneum"))'
```

Require version 1.0.3 and the independent installer acceptance. Python 3.11–3.14;
macOS arm64/x86_64 or Ubuntu x86_64/systemd; installer administrator approval and
GitHub asset downloads are required. The client runs unprivileged. Do not test
installers on an existing deployment. SDK installation on Windows/Linux arm64 is
not evidence of supported local serving.

## Recommended submission order

| Priority | Channel | Release-day actions and credentials | Remaining blocker |
| --- | --- | --- | --- |
| 1 | Official MCP Registry | Use PR #2's reviewed main-only, environment-approved workflow and its [runbook](../registry/publication-runbook.md). Requires the environment-only domain signing seed and independent reviewer approval. | Public package marker/version acceptance; protected environment/domain authentication. |
| 1 | Glama | GitHub OAuth with repository write/admin access; add/claim [the repository](https://glama.ai/mcp/servers), then supply the dedicated Dockerfile in its admin flow. Follow [sandbox instructions](glama-sandbox.md); confirm the provider's score and listing path. | Provider sandbox build/introspection not performed; predicted listing returns 404. |
| 1 | punkpeye/awesome-mcp-servers | After Glama success, fork the upstream repository using your GitHub account. Insert [the prepared entry](submissions/awesome-entry.md) under Data Science Tools in alphabetical order. Open a PR titled `Add cole-h06/omneum` with [the prepared description](submissions/awesome-pr.md). | A real Glama listing/score, live released installation and duplicate/link checks are required first. |
| 2 | Smithery local stdio | Build/validate/import-test the MCPB, then use authenticated Smithery CLI and your owned namespace. Exact commands below. | Smithery host import and supported-host execution remain untested; daemon setup is not bundled. |
| 2 | PulseMCP | Manually open [Submit](https://www.pulsemcp.com/submit), select the server submission and use the common repository/stdio/setup description. Supply maintainer contact and any account the live form requests. | Automated access to the form returned 403; fields/login requirements require manual inspection. No API submission is invented. |
| 2 | mcpservers.org | Open [Submit](https://mcpservers.org/submit); fill name, suitable category, short description, repository/documentation, optional `ai.omneum/omneum`, and maintainer contact email. Leave remote connections unchecked. Use free review; do not purchase promotion automatically. | Released installation and owner-confirmed email; manual form review. |
| 3 | VS Code/GitHub MCP gallery | The [VS Code gallery](https://code.visualstudio.com/mcp) points to GitHub's MCP Registry. Verify official-registry metadata and inspect whether Omneum appears; indexing is not guaranteed. Share the CLI configuration below after installation. | No self-service public gallery submission API was verified. Gallery admission is separate from protocol support. |
| 3 | Cursor install links / Marketplace | Share the generated install link after daemon setup. The [plugin Marketplace](https://cursor.com/marketplace/publish) accepts a public repository containing a valid locally tested plugin; see its [reference](https://cursor.com/docs/reference/plugins). Requires a Cursor account and repository ownership. | Client GUI launch not tested. No Marketplace plugin was built; publishing there additionally requires a validated plugin and declared configuration variables. |
| 3 | Claude Directory | Current [submission docs](https://claude.com/docs/connectors/building/submission) say standalone local MCPB directory listings are deprecated. Use a tested local plugin via [Plugin bundle submission](https://claude.ai/directory/manage), not the old desktop extension form. Requires eligible paid Claude account/role and connected GitHub account with push access. | No Claude plugin or GUI compatibility test is complete. MCPB schema/protocol tests do not establish Claude Directory eligibility. |

PulseMCP's [first-party API overview](https://www.pulsemcp.com/api) confirms manual
submissions and official-registry ingestion. mcpservers.org's current form accepts
repository submissions with remote support optional. These two are additional
high-value general directories; the ordering above is a recommendation, not a
claim about guaranteed reach or acceptance.

## Smithery: build, validation, then separately authorized submission

The [current publishing guide](https://smithery.ai/docs/build/publish) accepts
MCPB uploads for local stdio. This is a connector to an existing installation,
not a self-contained Omneum/daemon installer. The archive is unsigned; signing
and trust policies must be checked in the chosen host before submitting. Never
self-sign merely to bypass client trust policy.

```bash
# Use a new output directory; builder refuses an existing archive.
python3 tools/build_discovery_bundle.py --output dist/discovery-release
# Install the pinned authoring CLI into a dedicated local tools directory.
npm install --prefix /private/tmp/omneum-mcpb-tools --ignore-scripts \
  --no-audit --no-fund @anthropic-ai/mcpb@2.1.2
/private/tmp/omneum-mcpb-tools/node_modules/.bin/mcpb validate \
  deploy/discovery/mcpb/manifest.json
/private/tmp/omneum-mcpb-tools/node_modules/.bin/mcpb info \
  dist/discovery-release/omneum-local-1.0.3.mcpb
```

Import and run that exact archive on a fresh macOS/Ubuntu installation in the
intended MCPB host. Select the absolute console-script path and call `ping`,
`evaluate_voprf`, and `evaluate_context`; check daemon key denial. The bundle's
`darwin`/`linux` declaration reflects intended OS families, not full tested client
compatibility or support for every CPU/distro. The launcher does not automatically
verify the selected Python environment's package version; check it manually.

Only after those checks and explicit authorization:

```bash
# Authenticate as the namespace owner; do not put tokens in command arguments.
smithery auth login
smithery auth whoami
smithery mcp publish ./dist/discovery-release/omneum-local-1.0.3.mcpb \
  -n YOUR_OWNED_NAMESPACE/omneum
```

These CLI commands are documented in the [Smithery CLI reference](https://smithery.ai/docs/concepts/cli).
OAuth login or an account-managed API credential is required. No API key is
needed to run Omneum locally. Do not change the official MCP identity to match a
Smithery namespace; they are separate directory identifiers.

## Awesome MCP Servers: exact future Git workflow

The current [contribution guide](https://github.com/punkpeye/awesome-mcp-servers/blob/main/CONTRIBUTING.md)
requires an installable public GitHub repository, one concise entry per line,
matching style and alphabetical ordering. Its [actual submission workflow](https://github.com/punkpeye/awesome-mcp-servers/blob/main/.github/workflows/check-glama.yml)
also checks the GitHub `owner/repo` label, allowed emojis, duplicates and a Glama
score badge; it tells authors to configure the Dockerfile directly in Glama.
The agent fast-track title suffix is optional; the prepared title retains normal
maintainer review.

After live Glama/installation checks, in a separate clone (not performed here):

```bash
gh repo fork punkpeye/awesome-mcp-servers --clone
cd awesome-mcp-servers
git switch -c add-omneum
# Insert the exact entry under Data Science Tools, sorted by owner/repo.
# Confirm actual Glama path and no duplicate before staging.
git add README.md
git commit -m 'Add cole-h06/omneum'
git push -u origin add-omneum
# Copy the prepared Omneum PR body to a local file, omitting its first Title line.
gh pr create --repo punkpeye/awesome-mcp-servers --base main \
  --head cole-h06:add-omneum --title 'Add cole-h06/omneum' \
  --body-file /path/to/reviewed-awesome-pr-body.md
```

The account/fork name above assumes `cole-h06`; adjust to the submitting owner.
Do not submit the draft checklist as evidence of completed Glama review.

## Client installation links and commands

These configure a previously installed daemon; they do not install Omneum.
Use `python3 tools/discovery_client_links.py --server-path /absolute/omneum-server`
to produce correctly encoded Cursor and VS Code commands. The Cursor format is
from its [official install-link docs](https://prod.cursor.com/docs/mcp/install-links).
VS Code's [current stdio configuration guide](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
documents `code --add-mcp` and supports local commands. Review configuration and
keep each client's tool-trust prompts enabled. No GUI import, trust approval or
client configuration was performed in this task.

Claude's [plugin submission guide](https://claude.com/docs/plugins/submit) gives
the future route: first build/test a plugin, run `claude plugin validate
./PLUGIN_DIRECTORY`, then choose Plugin bundle in the developer portal with its
repository, plugin folder and tracked branch. Keep automatic publishing disabled
and choose scheduled checks rather than adding repository webhooks without a
separate decision. Do not use the remote MCP connector URL field for local stdio.
