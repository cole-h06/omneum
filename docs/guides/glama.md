# Glama listing and MCP inspection

The existing listing is [cole-h06/omneum on Glama](https://glama.ai/mcp/servers/cole-h06/omneum). Keep that identity when changing metadata or rebuilding its inspection image.

## Claim and metadata

The root [glama.json](../../glama.json) declares the GitHub maintainer. Its official [schema](https://glama.ai/mcp/schemas/server.json) documents `maintainers`; it does not document category, description, or keyword properties. Configure listing metadata through the claimed listing instead of adding arbitrary fields to this file.

1. Open the existing listing, choose **Claim**, and authenticate with the GitHub account `cole-h06`. Glama documents that adding or updating `glama.json` requires repeating the claim flow to sync it.
2. Use a concise listing title such as **Omneum: Context Selection for AI Agents**.
3. Suggested description: **Text-blind context evaluation for coding agents, research workflows, multi-agent systems, and RAG pipelines. Assess source reliability, dependent evidence, and conflicting claims to guide context selection.**
4. Keep **RAG Systems** and **Agent Orchestration**. Prefer **Research & Data** over the broader **AI & Machine Learning** category if only three categories are allowed. **Developer Tools** is also relevant if another category is supported.

These are application workflows for the same evaluator, not separate code-analysis, retrieval, or fact-checking products. The caller supplies structured observations and decides how to filter or rank context. Existing benchmark results and tool descriptions remain authoritative.

## Dedicated MCP build

The repository's root `Dockerfile` and `compose.yaml` serve the optional hosted Network API. They are not a stdio MCP launch recipe. Do not change them to fix catalog introspection.

The separate [Dockerfile](../../deploy/glama/Dockerfile) builds the Python package and evaluator from the same repository sources with locked Rust dependencies and the pinned project toolchain. It uses the existing foreground installer at startup. The evaluator and MCP server run as different service users, with the private key readable only by the evaluator. A fresh key is provisioned at runtime, not stored in the image. No test daemon or same-UID fallback is used.

Build and inspect using Docker's native Linux architecture:

```sh
docker build -f deploy/glama/Dockerfile -t omneum-glama:1.1.3 .
docker run --rm -i omneum-glama:1.1.3
```

Run `python tools/check_glama_container.py --image omneum-glama:1.1.3` from an environment with Omneum installed to check the actual stdio exchange, VOPRF proof verification, private-key denial, and that no key is baked into the image. An optional `--expected-tools` JSON array compares complete definitions against a prior real `tools/list` capture.

The process speaks MCP over stdio; startup diagnostics go to stderr. No environment variables, credentials, or Network enrollment are required. The source build permits native container validation; it does not change the supported platforms of the public standalone installer. The container starts as root only to install the existing foreground service layout and drop credentials to the two service users. Keep that separation in the Glama build configuration.

After claiming, open the existing [Dockerfile admin page](https://glama.ai/mcp/servers/cole-h06/omneum/admin/dockerfile) and configure the build spec using this dedicated recipe, with the same Python image, locked source build, system prerequisites, and CMD. If the form exposes build steps and CMD rather than a Dockerfile path, translate these instructions into those fields; do not point it at the root Network Dockerfile. Glama's [release guide](https://glama.ai/blog/2026-03-15-how-to-make-a-release) describes the supported controls.

Run **Deploy**, inspect the build test, and create a Glama release from the successful test. A Glama container release is separate from a GitHub tag or PyPI release. This guide does not authorize changing either of those releases.

## Verify indexing

The schema page should expose exactly `evaluate_context`, `evaluate_voprf`, and `ping`, using the descriptions and complete schemas from the real server's `tools/list`. In particular, `evaluate_context` must retain:

> Detect unreliable sources, duplicated or dependent evidence, conflicting claims, and stale information in AI agent and RAG pipeline context before model ingestion.

Check build health and actual tool definitions before interpreting a quality grade. A missing tool catalog is not a low measured Tool Definition Quality Score. Glama scores purpose, usage guidance, behavior, parameters, conciseness, and contextual completeness; the public methodology does not disclose exact search-ranking weights.

Record observed search positions and result counts for the target engineering queries before and after the update. A pushed README or ownership file alone does not prove that Glama has claimed, built, inspected, or reindexed the listing. Recheck the public listing, schema page, and search results after Glama processes the update. If an authorized build cannot run in Glama's sandbox, contact [Glama support](https://glama.ai/support) with the build-test URL and logs; do not weaken the daemon's identity or key-isolation checks.
