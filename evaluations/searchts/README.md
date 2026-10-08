# SearchTS

External evaluation of Omneum 1.0.3 using retrievals produced by SearchTS.

**Evaluator:** CAP.AD [NOUS]  
**System:** SearchTS  
**Omneum version:** 1.0.3  
**Environment:** Debian 13 (trixie), x86_64 container  
**Data:** Live web retrievals

## What was evaluated

SearchTS retrieves web pages through multiple backends, including `curl_cffi` and a stealth-browser path. Each retrieval can preserve the requested URL, final URL, backend, fetch timestamp, HTTP status, and retrieved text.

The evaluation tested whether Omneum distinguishes the retrieval path from the web document that actually produced the context.

This matters when an agent uses fallback retrieval or multiple web tools. Two chunks can arrive through different code paths while still coming from the same web page. Counting those chunks as independent support would inflate the amount of independent context available to the model.

The evaluation also exercised Omneum's Linux daemon and MCP server inside a Debian container without systemd.

## Integration

CAP.AD first installed the Omneum 1.0.3 Python wheel inside a Debian 13 x86_64 container.

The container used `tini` as PID 1 and did not run systemd. The original Linux installer stopped because `/run/systemd/system` was unavailable. This exposed a deployment problem for containers and other Linux environments that do not boot systemd.

A foreground daemon path was added and tested. During that test, the daemon also rejected the inherited Linux capability set when started as the protected service identity. Clearing the inheritable capability set allowed provisioning and serving to complete.

The working daemon was started under the `omneum-crypto` identity, and its evaluation socket became available.

Omneum was then initialized from the installed Python environment under the `omneum-mcp` identity:

```text
Omneum initialized.
Deployment: urn:uuid:b7cee16e-0035-4a86-9843-e9d21c401e1b
Configuration: /var/lib/omneum/.config/Omneum
```

CAP.AD then started the Omneum MCP server over stdio and called `ping`. The server returned `status: ok`, protocol version `v1`, algorithm version `omneum-v2`, and the configured VOPRF parameters.

This established that the installed Python package, protected daemon process, local IPC path, and MCP server could operate together in the no-systemd container before the retrieval cases were tested.

## Retrieval cases

### Same document through different backends

SearchTS retrieved the same Go document through two different backends:

```text
Document: https://go.dev/blog/loopvar-preview

curl_cffi
  final_url: https://go.dev/blog/loopvar-preview
  fetched_at: 2026-09-30T18:08:41Z
  status: 200

stealth-browser
  final_url: https://go.dev/blog/loopvar-preview
  fetched_at: 2026-09-30T18:08:45Z
  status: 200
```

The two retrievals followed different SearchTS execution paths, but both resolved to the same underlying web document.

The backend therefore could not be used as the source identity. `curl_cffi` and `stealth-browser` describe how the document was retrieved; the final URL identifies what document supplied the retrieved context.

This case was used to verify the integration boundary before constructing the different-source comparison.

### Different documents supporting the same statement

SearchTS 0.13.0 was then used to retrieve two different web documents through the two backends.

Both documents supported the statement that Go 1.22 changed `for`-loop variables so each iteration creates new variables, avoiding accidental sharing bugs.

The first retrieval was:

```text
backend: curl_cffi
final_url: https://thenewstack.io/golang-1-22-redefines-the-for-loop-for-easier-concurrency/
fetched_at: 2026-10-02T19:18:53Z
status: 200
```

The second was:

```text
backend: stealth-browser
final_url: https://go.dev/doc/go1.22
fetched_at: 2026-10-02T19:19:03Z
status: 200
```

Unlike the first case, these retrievals resolved to different documents on different hosts: `thenewstack.io` and `go.dev`.

The raw SearchTS captures were then mapped into an Omneum evaluation using the final URLs as source identities while retaining the retrieval metadata.

## Results

Omneum completed the different-source evaluation with the following output:

```text
Support: 1.00
Supporting sources: 2
Estimated independent support: 2.00
Dependency signal coverage: 0.25

Source reliability
  curl_cffi:       0.5000
  stealth-browser: 0.5000

Dependency: 0.0000
Conflicts: 0
Convergence iterations: 1
Evaluation latency: 11.9 ms
```

The two retrieved documents were counted as two supporting sources.

Omneum estimated **2.00 independent supporting sources** and assigned an observed dependency of **0.0000** between them. Neither source received additional weight; both received source reliability scores of **0.5000**.

Dependency signal coverage was **0.25**. The result therefore means that Omneum found no dependency in the source metadata available to this evaluation. It does not establish that the two publishers are globally independent outside the supplied context.

No conflicting value was present, and BRAID converged in one iteration.

## Findings

The evaluation exercised a distinction that matters in web retrieval pipelines: a retrieval backend is not the same thing as a source.

`curl_cffi` and `stealth-browser` can retrieve the same URL. Treating the backend name as source identity would make one web document appear to be two independent sources simply because the agent reached it through two code paths.

The SearchTS metadata exposes enough structure to avoid that mistake. `final_url` identifies the retrieved document, while `backend` records the retrieval path and `fetched_at` records when the retrieval occurred.

The different-document case then tested the opposite condition. SearchTS returned two documents from different hosts supporting the same statement. With the source metadata supplied in that evaluation, Omneum returned two supporting sources, estimated independent support of **2.00**, and observed dependency of **0.0000**.

The integration test also exposed a Linux deployment issue before the evaluation ran. Omneum's original installer assumed a systemd environment even though the daemon itself could run without systemd. Testing in SearchTS's Debian container led to a foreground daemon path and exposed the inherited-capability failure during daemon startup.

## Scope

The retrieval captures came from live SearchTS requests.

The different-source result should be interpreted from the metadata available to Omneum. A dependency score of `0.0000` means no dependency was observed from the supplied source relationships; it is not a claim that no relationship could exist outside the evaluation input.

The reported **11.9 ms** latency is the result from this individual evaluation and is not a production latency benchmark.

## Artifacts

The original SearchTS retrieval captures supplied by CAP.AD are included unchanged. The repository filenames were shortened for clarity; the file contents were not modified.

- [`independent-curl-cffi.json`](artifacts/independent-curl-cffi.json)
- [`independent-stealth-browser.json`](artifacts/independent-stealth-browser.json)

SHA-256:

- `independent-curl-cffi.json` — `f74098d5120aa9150b201bc50bed618f32e318bbec0122e3576f1e029e247a87`
- `independent-stealth-browser.json` — `99ee945c64171e37fa20529202aedf65e919f30b0f5cb7d3bacc148562a6fe2f`