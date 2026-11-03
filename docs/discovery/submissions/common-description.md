Name: Omneum

Repository: https://github.com/cole-h06/omneum

Official identity: ai.omneum/omneum

Description: Local provenance-aware context evaluator for AI agents. Evaluates
opaque assertions and source-dependency metadata over stdio, without interpreting
the semantic meaning of context. Requires `pip install omneum` followed by
`omneum install` from the normal login account.

Setup: Python 3.11–3.14; macOS arm64/x86_64 or Ubuntu x86_64 with systemd.
The installer downloads matching, checksum-verified GitHub release assets and
requests administrator approval for isolated machine service files. It does
not require a remote MCP endpoint or an API key for local evaluation.

MCP command: the absolute `omneum-server` path from `command -v omneum-server`.
Use the same account that completed installation. Do not run the client with sudo.
Windows and Linux arm64 do not have supported daemon release targets. The SDK
may install there; that does not imply local MCP serving support.

Optional Omneum Network contribution is disabled by default. Local context
persistence and optional Network contribution have separate configuration.
Never describe this as automatic one-click installation.

Release-day contact: supply a maintainer-controlled email in each form; this
material does not invent one or consent to directory terms on the maintainer's behalf.
