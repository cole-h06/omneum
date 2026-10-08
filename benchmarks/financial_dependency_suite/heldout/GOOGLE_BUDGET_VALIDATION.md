# Google selector execution correction

The completed clean-validation-1trial-20261004T013826Z run recorded 27/48
Google selector failures with MAX_TOKENS and incomplete JSON, without HTTP
429/503 errors. The fixed selection schema requires at most about 80 compact
JSON bytes, but that is not the complete provider output budget.

Google's generateContent thinking documentation states that max_output_tokens
includes thinking plus answer tokens and is a hard cutoff, not a setting that
reduces the model's thinking effort. Gemini 3.8 Flash defaults to medium thinking.

- https://ai.google.dev/gemini-api/docs/generate-content/thinking
- https://ai.google.dev/gemini-api/docs/generate-content/latest-model

The sole request change is a Google structured-selector output allowance of
8,192 tokens instead of 1,024 for gemini-3.8-flash. Larger explicitly requested
caps remain respected. Nonstructured Google generation and other models and
providers are unchanged. No thinking level/budget is set, and no schema, prompt,
candidate, top_n, retry, fallback or parser behavior is changed.

This is a bounded allowance for completing the existing reasoning and JSON,
not a claim that 8,192 is a mathematically minimal or guaranteed sufficient
value. Documentation gives no task-specific lower bound, and the old run did
not save thought-token counts. A precise minimum cannot be inferred from the
truncated records. The allowance is fixed before the new validation; no cap
search, repeated decision attempts, or outcome-based adjustment is performed.
If truncation recurs, the parser must still report failure.

## Refusals

The seven previous support_stale_runbook refusals have provider-returned
stop_reason=refusal, content_block_types=[], output_tokens=0, and text="".
They occurred under the unchanged Anthropic generator and fixed context.
The adapter concatenates text blocks; there were no returned text blocks to
lose. The harness preserves these responses and classifies them as generation
failures. Thus these are genuine provider refusals, not evidence of an
extraction or execution bug. No refusal rationale is saved, so their underlying
policy trigger cannot be established. Their appropriateness is not adjudicated.
They remain benchmark outcomes; no generation is retried or context edited.

## Integrity

Before editing, all 56 frozen manifest entries matched. A separate 112-file
protected baseline covers the frozen inputs, selector/prompt implementation,
downstream prompt, BRAID sources and every file in both completed run directories.
The Google client configuration and its offline contract tests are the only
executable changes. No frozen manifest or prior result is rewritten. The new
run must use a new identifier and a new implementation fingerprint.
