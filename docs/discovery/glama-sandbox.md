# Glama indexing preparation

The existing `glama.json` lives in [draft PR #2](https://github.com/cole-h06/omneum/pull/2).
Its maintainer-only metadata passes the current [official schema](https://glama.ai/mcp/schemas/server.json).
This additive branch does not duplicate or modify that file. After PR #2 is
reviewed and integrated, verify it on the same commit submitted to Glama:

```bash
python3 tools/check_discovery.py --glama-json glama.json
```

Glama builds and introspects its own sandbox according to its [methodology](https://glama.ai/mcp/methodology).
The root Dockerfile serves the optional network API and is deliberately unchanged.
Use **deploy/discovery/Dockerfile** with repository root as the build context and
its companion `Dockerfile.dockerignore`. The default final target is `glama`.
Only locked Python/Rust source inputs enter the build; base images are pinned by
digest. The runtime contains no Node.js, API server, exposed port or credential.
Debian package updates are still resolved from the Debian repositories at build
time; this is not an immutable full OS snapshot.

```bash
docker build -f deploy/discovery/Dockerfile -t omneum-glama:1.0.3 .
python tools/discovery_stdio_probe.py --image omneum-glama:1.0.3
```

Run the Python command with a development environment containing the existing
`mcp` dependency and Docker access. It starts a disposable `--network none`
container with no host mounts, initializes MCP, lists tools/resources/prompts,
and calls `ping`. Linux arm64 execution passed locally. This architecture is a
sandbox build target, **not** a new supported public daemon release target.

For the connector's real protected VOPRF/context evaluation probe:

```bash
docker build -f deploy/discovery/Dockerfile --target probe \
  -t omneum-discovery-probe:1.0.3 .
docker run --rm --network none omneum-discovery-probe:1.0.3 probe
```

The probe-only stage includes Node.js to test the manifest's launcher. It is not
the default Glama image. Both stages use the production Rust daemon feature,
never `test-daemon` or `--test-mode`. Bootstrap requires the explicit sandbox marker set by the image; direct host
invocation without that marker fails closed. Root bootstraps fixed service accounts using
the existing foreground installer. The daemon runs as `omneum-crypto`; the MCP
server runs as `omneum-mcp`, an explicitly authorized foreground service principal,
with no privilege escalation. The key is created at container start, owned by
the crypto identity at mode 0600 behind a 0700 directory, never baked into an
image or bundle. Stdio remains free of bootstrap logs. The probe verifies that
the MCP process cannot read the key. The container is removed when the session ends.

This is the documented foreground-daemon path, not Ubuntu's production systemd
socket-activated dynamic-user path. It does not establish the production Linux
per-session isolation guarantees. Production installation acceptance remains
independent and mandatory; this recipe neither changes nor substitutes for it.

Release-day operator actions (not performed): authenticate to [Glama](https://glama.ai/mcp/servers)
with a GitHub account that controls the repository; add/claim the repository;
provide the dedicated Dockerfile directly in the listing's Dockerfile admin
flow, retaining its constrained build context; set the stdio startup command
to the image's default entrypoint with no extra arguments. Use no API keys,
production credentials or remote connector URL. Observe provider build and
introspection output and confirm the actual score badge. The predicted
`https://glama.ai/mcp/servers/cole-h06/omneum` returned 404 during preparation;
use the path Glama actually assigns before submitting dependent directory entries.

Provider-specific kernel, root-bootstrap, network and filesystem policies remain
unverified. If the protected daemon is refused, stop and coordinate with Glama;
do not relax ownership checks, daemon capabilities, UID separation or release gates.
