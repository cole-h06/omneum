# Diagnostic smoke corrections

Scope: diagnostic-smoke-1trial. Existing results are immutable; these changes
apply only to a separately authorized new run. Do not resume the old run with
the changed implementation fingerprint or refresh its hashes.

## Selector transport

Both ordinary and provenance frontier selectors send the same JSON schema:
an object containing `selected_sources`, an array of strings, with no additional
properties. Anthropic uses `output_config.format`, Google uses
`response_mime_type=application/json` plus `response_json_schema`, and OpenAI
uses `text.format` with strict JSON schema. Local candidate-membership,
uniqueness, cardinality, ordering and parsing behavior are unchanged. Prompts,
candidate inputs and context budgets are unchanged. No prose scraping,
fallback request, model substitution, or retry policy has been added.

The installed SDKs (anthropic 0.125.0, google-genai 2.21.0, openai 2.54.0)
serialize these options in offline HTTP-transport tests. Anthropic documents
Sonnet 5.5 structured-output support. Offline tests establish request shape,
not live account access or a guarantee against refusals/truncation.

References:
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- https://ai.google.dev/gemini-api/docs/structured-output
- https://developers.openai.com/api/docs/guides/structured-outputs

## Google readiness

The smoke model is `gemini-3.8-flash`; the configured cap is 1,024 output tokens.
Previously no JSON/schema output was requested. The cap remains 1,024 for all
frontier selectors, and downstream generation is unchanged. No thinking
configuration is overridden. The small selection object does not itself
justify a larger cap (at most 80 bytes in compact JSON, taking the longest IDs
up to each frozen case's budget). The saved MAX_TOKENS response establishes truncation,
but lacks the reasoning-token evidence needed to attribute it to a particular
budget component or choose a defensible replacement cap. Structured output
removes unconstrained prose/fences; it does not guarantee avoidance of a
generation limit. Future truncation remains an explicit parse failure.

HTTP 429 remains `provider_error`, categorized as `rate_or_quota_limit`; HTTP
503 remains `provider_error`, categorized as `service_unavailable`. Status and
exception class survive credential-safe persistence; arbitrary exception
bodies remain redacted. No retry policy is changed. Google HTTP-transport tests
verify one request for 429 and 503.

External prerequisite: in Google AI Studio, identify the project belonging to
GEMINI_API_KEY, inspect that project's active limits and usage for this exact
model, and determine the exhausted dimension (RPM, TPM, daily quota, or a
spend-related limit). Confirm billing/tier and sufficient available quota;
request the applicable increase or wait for the relevant reset if exhausted.
A new key in the same project does not increase its project quota. The saved
429s cannot establish which limit or a numeric increase to request. Check the
503's provider availability separately. Do not switch models to evade limits.

Reference: https://ai.google.dev/gemini-api/docs/rate-limits

## Downstream outcomes

`generate_answer_safe` now returns the existing `generation_failure` result
category for explicit refusal (`failure_type=refusal`) and absent/whitespace
answers (`failure_type=empty_output`). Raised exceptions retain
`failure_type=provider_error`. Explicit refusal takes precedence even when
text is present. Detection uses response metadata, not interpretation of prose.
Returned text and the complete generation envelope are preserved. There is no
second generation attempt. The held-out runner already propagates this failure
envelope and retains selected candidates without scoring an unanswered result.

Summaries retain existing counts/denominators and add `selection_failures`,
`generation_failures`, and `generation_failure_types`. Old smoke records are
not rewritten or retrospectively recategorized.

## Scorer decision: no correction authorized by the narrow rule

The three established misses are all in coding_package_fix_lineage, trial 1:

| Record | Method | Observed wording | Required literal that fails |
| --- | --- | --- | --- |
| 75 | openai | bound the number of idle connections in the pool | bound idle connections |
| 78 | openai_provenance | bound the number of idle connections | bound idle connections |
| 80 | braid | bounding the number of idle pool connections and evicting expired entries | bound idle connections; evict expired |

These are substantive paraphrase/inflection equivalences, not thousands
separators, harmless punctuation, or an identical textual representation.
Recognizing them requires the synonym/semantic broadening excluded by the
current instruction. Consequently there is no old-to-new normalization change,
and no frozen case is affected by a scoring change. Method-blind regression
tests retain this boundary. No unrelated numeric-normalization change is made.
The known representation limitation remains documented for separate review.
multi_agent_feedback_loop still requires both `blocked` and `load_test`.

## Integrity and validation

Verify all 56 entries in dataset_manifest.json before and after editing;
candidate text and provenance are covered by the 24 complete case.json hashes.
Also preserve both selector prompt templates, downstream generation prompts,
the manifest itself, and all saved smoke artifacts. No frozen hashes are
refreshed. Code corrections legitimately change the implementation fingerprint
for a new run; the prior run's manifest remains untouched.

All relevant financial_dependency_suite tests run offline with outbound TCP
blocked and model downloads disabled. Provider contract tests use in-memory
HTTP transports. Run the dataset validator and git diff --check separately.
Live readiness still requires resolution of Google quota and an explicitly
authorized clean validation, including observation of structured completion
and downstream refusal outcomes. No provider call or benchmark rerun is part
of this correction task.

Offline verification completed: 340 passed, one pre-existing paid test skipped,
and three legacy live-provider tests deselected. The TCP guard blocked those
three before any provider connection during the initial broad test discovery.
Local daemon integration tests require permission to bind Unix sockets outside
the filesystem sandbox; they pass with that permission and TCP still blocked.
Dataset validation passes for 24 cases, retaining its pre-existing canonical
community-note/matrix-slot warning. All 56 manifest hashes and 62 protected
baseline file hashes match; both selector prompt templates are unchanged.
git diff --check passes.
