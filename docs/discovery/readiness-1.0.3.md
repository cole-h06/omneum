# Omneum 1.0.3 directory preparation

Prepared 2026-10-12 on `feat/mcp-directory-preparation-1.0.3`, from fetched
`origin/main` at `a40b564`, in `/private/tmp/omneum-directory-1.0.3`.
This is additive to [draft PR #2](https://github.com/cole-h06/omneum/pull/2) at
`f114f85`: none of its files or commits are duplicated or overwritten. Root
README, Dockerfile, dependencies, release CI and production/security code are
unchanged. The active release candidate and earlier registry worktrees remain
untouched. No package, listing, external directory PR, tag, service, DNS record
or visibility setting was published or changed.

## Prepared and tested

| Deliverable | Evidence | Practical limit |
| --- | --- | --- |
| MCPB connector | Built `dist/discovery/omneum-local-1.0.3.mcpb`; official CLI 2.1.2 validates the v0.3 manifest, unpacks it and repacks its four-file closure. ZIP output is reproducible and contains no keys/installers. | Connects an existing Omneum installation; unsigned. Smithery import and GUI/client execution not tested. |
| Real MCP execution | Manifest-derived launcher ran initialization, all three tool listings, `ping`, and a mapped context evaluation with verified VOPRF in network-disabled Linux arm64 Docker. MCP private-key reads were denied; root launcher rejected. | Uses the existing protected foreground-daemon path on Debian arm64, not a supported released installer target or production Ubuntu dynamic-user path. |
| Glama | PR #2's actual `glama.json` passes the current live schema. Dedicated digest-pinned Dockerfile builds from locked sources; default stdio image passes initialization/tools/resources/prompts/ping. No Node dependency in the default image. | Provider Firecracker/kernel/privilege policy and indexing have not been tested. The predicted listing URL returns 404. |
| Awesome MCP Servers | Exact one-line entry and PR body prepared; current contribution guide and actual Glama/emoji/name/duplicate workflow inspected. | Glama score and live installation evidence are prerequisites; no external PR was created. |
| Other discovery | Ranked first-party directory routes, shared descriptions, Cursor link and VS Code CLI generators prepared. Link encoding and shell quoting round-trip tested. | Client GUI trust/launch and Marketplace admission remain manual; configuration links do not install the package/daemon. |

[Sanitized test evidence and bundle hash](local-test-evidence.json) record the
scope precisely. **8 discovery tests and 42 existing release tests pass**;
PR #2 source composition and all 17 registry tests also pass in a temporary
combined tree; no shared branch was changed. Node/shell syntax and existing
workflow lint pass. No production service,
`test-daemon` feature, host mount or security-check bypass was used.

The bundle is a self-contained Node launcher with no npm dependencies, but it
requires host Node.js plus an installed Python environment and protected daemon.
It does not carry Python, native wheels or daemon release archives. The absolute
installed console-script path is selected by the user; its package version must
be checked manually. Linux/macOS are the manifest's intended OS families. No
actual macOS or Ubuntu x86_64 MCPB host compatibility is claimed. A local cached
amd64 image could not execute on this Docker engine; no privileged emulation
setup or host service changes were made to force a result.

## Remaining actions

1. Review both Omneum PRs separately; complete independent PyPI/daemon release
   acceptance. Public PyPI 1.0.3 still returns **404**. Preserve PR #2's marker and
   official identity `ai.omneum/omneum` in published metadata.
2. Test the exact bundle on fresh macOS arm64/x86_64 and Ubuntu x86_64 installations,
   including GUI executable selection, permissions, shutdown and real tools.
   Then test Smithery's actual import/download path and any signature requirements.
   There is **no genuine one-click installation** until Python/package installation,
   privileged daemon setup, version pinning and client executable discovery are solved.
3. Submit/claim Glama manually and run the provider's sandbox build with
   [the prepared recipe](glama-sandbox.md). Verify its actual listing/score before
   using the prepared Awesome entry. Do not weaken isolation if provider policy refuses it.
4. Supply maintainer contact/account credentials and review the directory-specific
   forms. Complete missing client/plugin validation before Marketplace submission.
   Claude's current Directory docs deprecate standalone MCPB listings and require
   a plugin for local servers; the old extension form must not be relied upon.

The [publication checklist](submission-checklist.md) contains the exact future
commands, submission links, credentials and blockers for Smithery, Glama, Awesome
MCP Servers, PulseMCP, mcpservers.org, VS Code/GitHub, Cursor and Claude. The
common two-stage setup remains `pip install omneum`, then `omneum install` as the
normal login account, with administrator approval during installation.
Supported daemon release targets remain macOS arm64/x86_64 and Ubuntu x86_64;
Windows is SDK-only, and Linux arm64 has no public installer target.

This report does not claim provider approval, production platform acceptance,
a published listing, one-click setup or official client certification.
