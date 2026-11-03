# Omneum Local Connector

This MCPB connects a client to an **already installed Omneum 1.0.3** stdio server.
It is not a one-click Omneum installation. It contains only the launcher,
manifest, this guide and MIT license; no Python dependencies, daemon, keys,
network credentials or installer. A host-provided Node.js 18+ runtime runs the
launcher; Omneum's Python package does not acquire a Node.js dependency.

Prerequisites on supported macOS or Ubuntu, from your normal login account:

```bash
python -m pip install omneum
omneum install
command -v omneum-server
python -c 'import importlib.metadata; print(importlib.metadata.version("omneum"))'
```

The package must be 1.0.3 for this release. Python 3.11–3.14 is supported;
installation needs administrator approval for machine service files and access
to the matching GitHub release assets. macOS arm64/x86_64 and Ubuntu x86_64 have
release daemon targets. Windows is SDK-only and excluded from this bundle.

Import the bundle in a supported MCPB host, select the **absolute installed
omneum-server executable**, and use the same login account that ran the installer.
A GUI may not inherit your shell PATH, which is why a file selection is required.
The launcher does not run a shell, download code, modify services or elevate
privileges. It forwards stdio unchanged; underlying failures remain failures.
The selected executable is trusted local code; select only your own installation.

Tested protocol execution and host/client compatibility are separate facts.
See docs/discovery/readiness-1.0.3.md in the source repository for the platform
matrix and outstanding Smithery/Claude Desktop GUI import tests.
