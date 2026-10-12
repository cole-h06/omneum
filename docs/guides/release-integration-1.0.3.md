# Omneum 1.0.3 integration candidate

This candidate integrates PR #4 at `6bd42b2e66acfecfbda005ddd1226b9507f31cee`
and PR #5 at `ac961571ab5cb699530845c47b05e698fba804be` from current
`main` at `a40b564`. Existing worktrees and unpublished candidates are preserved.
The Linux verification merge retains the explicit callback namespace, diagnostic
error reporting, private persistence, and all credential/capability assertions.

Network fixes come from the offline handoff based on `7176b99272462bce0136a60dd59d0b5b37b539aa`.
The integration patch SHA-256 is
`943a0b21d9b2b33213382483f24d1c7ecb4f2950b16befcf2d15b88fc3cfae35`.
All six source-file checksums in its `activation/INTEGRATION.json` were verified
before integration. The current deployment module already contains the handoff's
Certbot helpers; its newer secure-crypto requirement is retained. The activation
controller checksum matches this integrated module, not the earlier handoff copy.

Auth0 device polling accepts only the documented OAuth error/status combinations
(400, 403, and 429), rejects tokens in error responses, and suppresses provider
error descriptions. Tests cover rollback, exclusive mutation locking, artifact
checksums, preparation isolation, and refusal without explicit authorization.

## Release boundaries

`_PRODUCTION_NETWORK` and `_PRODUCTION_ONBOARDING` remain `None`.
Local installation, evaluation, and SQLite persistence do not require a production
Network. Network contribution and enrollment remain unavailable by default.
No production configuration, public key, pending settings, provider registration,
or activation dependency bundle is fabricated or included in this candidate.

The controller is an offline operator tool. Before any separately authorized
activation, rebuild and independently verify its private `activation` bundle from
this exact integrated source and the pinned PyJWT wheel; do not reuse the old
handoff deployment module. The approved production runtime must contain this
candidate's secure authentication code and declared dependencies, including
`packaging` and the `oauth` extra. Missing prerequisites fail closed. Authorizing
package publication does not authorize Network activation or a pinned Network
variant; either changes the reviewed release inputs and requires renewed testing.

## Verification

CI runs Python 3.11–3.14 tests with a digest-pinned disposable PostgreSQL service,
so Network relational tests execute rather than silently skipping without a DSN.
Network requirements are exported from the frozen lockfile with the OAuth extra,
plus the independent pinned PostgreSQL driver. The namespaced MCP SDK, license,
upstream revision, source hash and reproducible fork checks remain intact.

The nonpublishing workflow dispatch builds wheels and protected daemon assets and
runs fresh public-PyPI dependency installation, runtime MCP discovery/evaluation,
automatic private Context Graph creation, complete source/claim/observation/evaluation
persistence, daemon and process restart recovery, migration upgrade/checksum rejection,
concurrent WAL readers/writers, installer integrity and security auditing on macOS Intel,
macOS ARM and Ubuntu x86_64 for Python 3.11–3.14. This tests unpublished candidate
wheels against public dependencies; anonymous downloads of published 1.0.3 assets
can only be confirmed after separately authorized publication.

The integration PR records exact executed suites, artifact results, run URLs,
remaining skips and blockers. A successful earlier PR run is not acceptance of
this integrated commit. No merge, release tag, publication, production mutation,
key rotation or registry submission is part of integration.
