This is a read-only analysis of 480 saved records: 24 cases × 10 trials × 2 selection arms. GPT-6 Astra and Omneum select context after shared BGE; Claude Sonnet 5.5 generates every answer in both arms. This does not compare their abilities as answer generators. No API calls were made.

The original recorded accuracy is tied at 209/240 (87.08%). Semantic review gives 222 fully reference-complete answers for Astra and 220 for Omneum. Astra additionally has eight correct but incomplete rollback answers (they omit tb17), yielding 230 operationally correct answers if these receive credit. Omneum has ten substantive false-consensus errors, all on the same case. Both arms have ten explicit generator refusals on support_stale_runbook. No full abstentions were identified; Omneum's census caveats still accompany a wrong numeric answer.

Verified complete answer accuracy is **Astra 92.50% (222/240)** and **Omneum 91.67% (220/240)**. Median selection latency reduction is **81.26%**, median end-to-end latency reduction is **49.00%**, and estimated total API cost reduction is **66.91%**. This demonstrates **comparable observed accuracy, not statistical equivalence**.

Publication normalization replaces machine-specific absolute input paths in the manifest with repository-relative paths. All input hashes, configuration values, and raw result/summary bytes are retained. The original pre-normalization manifest SHA-256 was 512a34c35813bdbfb9d795a7262251ca0dcf41ed2ae48cf19b3818166f6bc493. Analysis source-artifact paths are also repository-relative; the hashes below describe the published files.

Semantic assessment concerns the requested answer and essential conditions; it is not an independent blinded human-panel assessment or an exhaustive score for every ancillary sentence and citation. Manual labels are separate analysis annotations and do not replace frozen scores.

Every unscored record and generation failure is reproduced and adjudicated below. The 20 package-fix answers correctly describe bounding/eviction while keeping reuse; exact substring matching misses inflected wording. Astra Retry-After trials 3, 7, 10 correctly say 120-second rather than the required 120 seconds. Omneum TLS trial 7 correctly rolls back to tb17 and retains upstream_tls_verify, but lacks the substring verification. Astra TLS trials 1, 2, 5–10 omit tb17 because their selected sources do not identify it; these are partial answers, not wholly incorrect answers and not mere synonym mismatches. Omneum census trials 1–10 answer 240 instead of 216; the correct dataset and census summary were available in BGE's shortlist but were discarded.

Selection precision/recall use the frozen supporting-source labels. Macro means weight each record equally; micro scores pool TP/FP/FN. Those labels can exclude useful diagnostic context: service_state is not a labeled supporting source in the TLS case despite explaining the failure. Recall is also budget-limited: the average theoretical case-budget ceiling is 71.14%, and the shared-shortlist ceiling is 66.28%. Recall against all supporting sources is not a measure of whether enough evidence exists to answer.

All 240 paired BGE results match exactly, including IDs, order, texts, scores, and duration. All 480 shortlist hashes, context-budget/subset contracts, generation request hashes, selection scores, and latency sums validate. All 48 case/reference file hashes match the manifest. Identical generation settings reconstructed from all hashes are Anthropic claude-sonnet-5-5, the common question/source prompt, max_tokens=1024, and no response schema. Actual prompts differ when source order or membership differs: 112 pairs share selected sets and 72 share exact source order and request hashes. Current client code sets no explicit temperature, seed, thinking, or effort overrides.

Two integrity qualifications: (1) Omneum uses structured claims/provenance plus recursively relevant dependency observations, whereas Astra's judge prompt contains shortlist text and IDs. The shortlist and answer-generation controls are matched, but judge information is not identical. No ground-truth source labels enter current selector code. (2) The manifest records a dirty checkout at commit 66f9b5552d13943193f3b92b66ddb348b84eb25a. Saved implementation fingerprint cefc953e9e029ef8a8e58994e887de8eac2923062abbf6c2c4aef456b91a6394 differs from checkout fingerprint ca26fec535a2741eb12a3efbe3b1a66187460f0890b75906491432b8ebeb6c6a, computed before these analysis artifacts were created. Current source explains the observed contracts but is not a verified execution-time snapshot. Request hashes establish the encoded settings, not undocumented server defaults. Current suite code schedules all ten Astra trials before the ten Omneum trials within each case, rather than randomizing/interleaving arms; timing can reflect temporal service variation.

Costs use standard short-context USD rates per million tokens: Astra $10 input/$50 output, Sonnet 5.5 $2 input/$10 output, verified October 8, 2026 in [OpenAI's model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra) and [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing). Saved inference_cost fields are unavailable; these are estimates, not invoices. Astra cached input is zero. Its 9,194 reasoning tokens are included in 14,699 output tokens and must not be billed twice. Claude reasoning-token metadata is null, not an established zero. All 480 generator calls have token telemetry; refusal input tokens are included. Local BGE/Omneum compute and hosting, account discounts, tier or region adjustments, and any unlogged transport retries are excluded. No prompt-cache controls are set in the current client code.

Median selection includes shared BGE and each selector's full measured duration, including Omneum integration. Omneum's core evaluator median is 30.66 ms, but the full pipeline selection median is 640.89 ms; do not advertise the core timing as total latency. End-to-end is selection plus that arm's independent generation call. Percentiles use linear interpolation at (n−1)q and include refusals. Local models are warmed by current runner code.

Omneum has identical ordered selections across all ten trials in every case. Astra has 17 cases with identical ordered selections, 20 with identical sets; seven cases vary in order and four in membership. Membership varies in research_conflicting_reports, research_independent_false_consensus, support_resolution_conflict, and support_ticket_reference_loop. Omneum is faster on selection in 240/240 pairs and end-to-end in 239/240 pairs; every per-case median improves. Deterministic consistency includes consistently wrong census selection and is not proof of correctness.

The ten repetitions are clustered within 24 fixed synthetic cases, not 240 independent tasks. Under full-reference correctness, Astra wins 10 paired observations (the census case), Omneum wins eight (TLS completeness), and 222 tie; the net difference is only two answers, but no noninferiority margin or representative sample establishes general equivalence. Under operational credit for partial TLS answers, Astra leads by one case, repeated ten times. A trial-level significance test would exaggerate the evidence by treating repeats as independent.

Omneum is competitive on most cases and much cheaper/faster in this controlled selection experiment. It is not a demonstrated accuracy-equivalent replacement: it has lower selection precision/recall and a persistent independent-false-consensus failure. It also provides more specific TLS rollback context than Astra usually selects. The shared refusal case provides no evidence favoring either selector.


Aggregate comparison

| Metric | BGE + Astra | BGE + Omneum |
|---|---:|---:|
| Records | 240.000000 | 240.000000 |
| Macro precision | 0.927778 | 0.861111 |
| Macro recall | 0.654464 | 0.593353 |
| Micro precision | 0.930435 | 0.869565 |
| Micro recall | 0.617308 | 0.576923 |
| Selection median seconds | 3.420616 | 0.640889 |
| Selection p95 seconds | 7.791302 | 0.851560 |
| End-to-end median seconds | 5.848734 | 2.982994 |
| End-to-end p95 seconds | 10.461226 | 4.717017 |
| Generation median seconds | 2.258151 | 2.298066 |
| OpenAI input tokens | 71610.000000 | 0.000000 |
| OpenAI output tokens | 14699.000000 | 0.000000 |
| Anthropic input tokens | 56684.000000 | 56610.000000 |
| Anthropic output tokens | 54563.000000 | 58509.000000 |
| OpenAI estimated USD | 1.451050 | 0.000000 |
| Anthropic estimated USD | 0.658998 | 0.698310 |
| Total estimated USD | 2.110048 | 0.698310 |

Savings: {"selection_median_percent": 81.26392932393793, "end_to_end_median_percent": 48.99760261819115, "api_cost_percent": 66.9054921973339, "api_token_percent": 41.728421308388505}. Total API tokens: 197,556 versus 115,119. Generator tokens increase 3.48%, output tokens increase 7.23%, and generator cost increases 5.97%. Eliminating Astra saves $1.451050 at the judge, offset by $0.039312 additional generation cost: net $1.411738 saved across 240 attempts. Estimated combined paired-run API cost: $2.808358.

Per-case table: A = Astra, O = Omneum. C/U/F = recorded correct/unscored/generation failure. Manual full means complete against the reference; partial rollback answers remain separate. Every metric averages or takes the median over that case's ten trials.

| Case | Recorded C/U/F A; O | Manual full A/O | Precision A/O | Recall A/O | Selection median s A/O | E2E median s A/O |
|---|---|---:|---:|---:|---:|---:|
| analytics_derived_metric_cycle | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 1.0000/1.0000 | 3.1653/0.6941 | 4.9787/2.5672 |
| analytics_incomplete_lineage | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.7500/0.7500 | 2.6572/0.7085 | 4.7452/2.8551 |
| analytics_metric_definition_conflict | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 1.0000/1.0000 | 2.4330/0.6491 | 4.7718/2.9191 |
| analytics_stale_dashboard | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.6000/0.6000 | 3.6118/0.6624 | 5.9644/3.1058 |
| coding_api_version_change | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.6000/0.6000 | 3.0055/0.7293 | 5.8656/3.6292 |
| coding_clean_dependency | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.5000/0.5000 | 3.0631/0.6110 | 7.2547/3.7583 |
| coding_config_conflict | 10/0/0; 10/0/0 | 10/10 | 1.0000/0.5000 | 1.0000/0.5000 | 2.0973/0.6162 | 4.5817/2.5559 |
| coding_package_fix_lineage | 0/10/0; 0/10/0 | 10/10 | 1.0000/1.0000 | 0.6000/0.6000 | 2.9439/0.5907 | 6.1362/3.1275 |
| enterprise_partial_lineage | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.7500/0.7500 | 4.8960/0.6123 | 7.4285/2.7706 |
| enterprise_policy_copy_chain | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 1.0000/1.0000 | 2.6145/0.6194 | 6.1567/4.2705 |
| enterprise_semantic_distractors | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.7500/0.7500 | 2.5369/0.6309 | 4.4839/2.6597 |
| enterprise_stale_handbook | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.6000/0.6000 | 2.9202/0.6186 | 4.6085/2.2737 |
| multi_agent_feedback_loop | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.6000/0.6000 | 2.8779/0.6413 | 5.9002/3.6369 |
| multi_agent_independent_error | 7/3/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.6667/0.6667 | 2.3514/0.7212 | 4.5010/3.1334 |
| multi_agent_relevant_wrong_task | 10/0/0; 10/0/0 | 10/10 | 1.0000/0.6667 | 0.7500/0.5000 | 3.7789/0.7088 | 6.1091/2.3795 |
| multi_agent_repeated_subagent | 10/0/0; 10/0/0 | 10/10 | 0.6667/0.6667 | 0.6667/0.6667 | 2.7249/0.6360 | 4.9246/3.0123 |
| research_clean_consensus | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.4286/0.4286 | 3.7063/0.6027 | 5.4101/2.1901 |
| research_conflicting_reports | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.6000/0.6000 | 6.2555/0.6240 | 8.7625/2.8961 |
| research_independent_false_consensus | 10/0/0; 0/10/0 | 10/0 | 0.6667/0.0000 | 0.6667/0.0000 | 6.0377/0.6298 | 7.9913/4.4526 |
| research_syndicated_reporting | 10/0/0; 10/0/0 | 10/10 | 0.3333/0.3333 | 0.2500/0.2500 | 3.4528/0.6198 | 5.9842/2.7756 |
| support_clean_resolution | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.4286/0.4286 | 4.0159/0.6256 | 5.9030/2.7151 |
| support_resolution_conflict | 2/8/0; 9/1/0 | 2/10 | 0.6000/0.5000 | 0.3000/0.2500 | 6.6286/0.6958 | 9.4493/4.8063 |
| support_stale_runbook | 0/0/10; 0/0/10 | 0/0 | 1.0000/1.0000 | 0.6000/0.6000 | 3.7997/0.7292 | 5.0293/1.8640 |
| support_ticket_reference_loop | 10/0/0; 10/0/0 | 10/10 | 1.0000/1.0000 | 0.6000/0.6000 | 7.5617/0.6493 | 11.2975/4.3022 |

Per-trial consistency

| Trial | Recorded correct A/O | Manual full A/O | Macro precision A/O | Macro recall A/O | Selection median s A/O | E2E median s A/O | Estimated USD A/O |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 21/21 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 4.0485/0.7889 | 6.5644/3.3195 | 0.206220/0.070432 |
| 2 | 21/21 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 3.3485/0.6534 | 5.6514/3.0103 | 0.208996/0.070042 |
| 3 | 21/21 | 23/22 | 0.9444/0.8611 | 0.6628/0.5934 | 3.7298/0.6542 | 6.3556/2.8810 | 0.220066/0.070152 |
| 4 | 22/21 | 23/22 | 0.9444/0.8611 | 0.6628/0.5934 | 3.3552/0.6392 | 5.5033/2.9558 | 0.213748/0.070412 |
| 5 | 21/21 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 3.0552/0.6297 | 5.7164/2.9992 | 0.204704/0.070412 |
| 6 | 21/21 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 3.2692/0.6214 | 5.8204/2.9907 | 0.217396/0.069542 |
| 7 | 20/20 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 3.6444/0.6390 | 6.0368/2.9555 | 0.207874/0.069332 |
| 8 | 21/21 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 3.2247/0.6368 | 5.3929/2.8811 | 0.215308/0.069342 |
| 9 | 21/21 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 3.6764/0.6285 | 6.0520/3.0019 | 0.214850/0.069032 |
| 10 | 20/21 | 22/22 | 0.9236/0.8611 | 0.6524/0.5934 | 2.9005/0.6349 | 5.3875/2.9658 | 0.200886/0.069612 |

Selection memberships by case and arm (ordered tuples and trial counts)


**analytics_derived_metric_cycle**

bge_openai: ['source_table', 'query_result', 'source_table_2'] × 10

bge_omneum: ['source_table_2', 'source_table', 'query_result'] × 10

**analytics_incomplete_lineage**

bge_openai: ['source_table', 'source_table_2', 'query_result'] × 10

bge_omneum: ['source_table', 'source_table_2', 'metric_store'] × 10

**analytics_metric_definition_conflict**

bge_openai: ['finance_report', 'metric_docs', 'warehouse_query'] × 10

bge_omneum: ['finance_report', 'metric_docs', 'warehouse_query'] × 10

**analytics_stale_dashboard**

bge_openai: ['warehouse_table', 'api_result', 'metric_store'] × 10

bge_omneum: ['warehouse_table', 'api_result', 'metric_store'] × 10

**coding_api_version_change**

bge_openai: ['current_api_docs', 'repository_code', 'changelog'] × 10

bge_omneum: ['current_api_docs', 'repository_code', 'changelog'] × 10

**coding_clean_dependency**

bge_openai: ['current_docs', 'repository_code', 'integration_test'] × 8; ['repository_code', 'current_docs', 'integration_test'] × 2

bge_omneum: ['integration_test', 'repository_code', 'release_notes'] × 10

**coding_config_conflict**

bge_openai: ['deployment_config', 'test_output'] × 10

bge_omneum: ['readme', 'deployment_config'] × 10

**coding_package_fix_lineage**

bge_openai: ['release_notes', 'package_docs', 'pull_request'] × 10

bge_omneum: ['release_notes', 'package_docs', 'pull_request'] × 10

**enterprise_partial_lineage**

bge_openai: ['drive_document_2', 'system_record', 'announcement'] × 10

bge_omneum: ['announcement', 'email', 'drive_document_2'] × 10

**enterprise_policy_copy_chain**

bge_openai: ['policy_record', 'policy_changelog', 'hr_system'] × 10

bge_omneum: ['policy_changelog', 'policy_record', 'hr_system'] × 10

**enterprise_semantic_distractors**

bge_openai: ['policy', 'system_record', 'operations_doc'] × 10

bge_omneum: ['policy', 'system_record', 'operations_doc'] × 10

**enterprise_stale_handbook**

bge_openai: ['current_policy', 'hr_system', 'announcement'] × 10

bge_omneum: ['current_policy', 'confluence_page', 'announcement'] × 10

**multi_agent_feedback_loop**

bge_openai: ['tool_result', 'database_result', 'web_result'] × 10

bge_omneum: ['verifier_agent', 'tool_result', 'web_result'] × 10

**multi_agent_independent_error**

bge_openai: ['api_result', 'tool_result'] × 10

bge_omneum: ['api_result', 'database_result'] × 10

**multi_agent_relevant_wrong_task**

bge_openai: ['api_result', 'tool_result', 'database_result'] × 6; ['api_result', 'database_result', 'tool_result'] × 4

bge_omneum: ['operations_agent', 'code_agent', 'api_result'] × 10

**multi_agent_repeated_subagent**

bge_openai: ['database_result', 'tool_result', 'web_result'] × 10

bge_omneum: ['web_result', 'database_result', 'tool_result'] × 10

**research_clean_consensus**

bge_openai: ['primary_record', 'filing', 'dataset'] × 10

bge_omneum: ['primary_record', 'filing', 'publication'] × 10

**research_conflicting_reports**

bge_openai: ['primary_publication', 'dataset', 'report_2'] × 6; ['primary_publication', 'dataset', 'filing'] × 4

bge_omneum: ['primary_publication', 'dataset', 'report_2'] × 10

**research_independent_false_consensus**

bge_openai: ['dataset', 'web_page', 'report'] × 3; ['dataset', 'web_page', 'publication'] × 7

bge_omneum: ['analysis', 'report', 'publication'] × 10

**research_syndicated_reporting**

bge_openai: ['dataset', 'original_report', 'news_article'] × 10

bge_omneum: ['original_report', 'news_article', 'dataset'] × 10

**support_clean_resolution**

bge_openai: ['current_runbook', 'monitoring_result', 'service_state'] × 9; ['current_runbook', 'service_state', 'monitoring_result'] × 1

bge_omneum: ['current_runbook', 'kb_article', 'monitoring_result'] × 10

**support_resolution_conflict**

bge_openai: ['service_state', 'runbook'] × 8; ['runbook', 'monitoring_result'] × 1; ['deployment_config', 'runbook'] × 1

bge_omneum: ['service_state', 'deployment_config'] × 10

**support_stale_runbook**

bge_openai: ['current_runbook', 'incident_record', 'deployment_config'] × 10

bge_omneum: ['current_runbook', 'incident_record', 'deployment_config'] × 10

**support_ticket_reference_loop**

bge_openai: ['runbook', 'service_state', 'change_record'] × 4; ['runbook', 'service_state', 'deployment_config'] × 6

bge_omneum: ['runbook', 'service_state', 'deployment_config'] × 10

Individual audit of every unscored answer and generation failure (42 unscored + 20 refusals)


**coding_package_fix_lineage / bge_openai / trial 1**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

Fix it by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Don't disable reuse.

Sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request**: The change bounds idle entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs** (supporting): Reuse should stay enabled normally, and the client bounds pool size and idle-entry eviction.

Taken together, the sources suggest the fix is in version 4.2, so upgrading to it would apply it. None of them states the upgrade step directly.



**coding_package_fix_lineage / bge_openai / trial 2**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Disabling reuse is not the fix.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request**: The change bounds idle entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and bounding/evicting, but it does not explicitly mention exhaustion.



**coding_package_fix_lineage / bge_openai / trial 3**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Release 4.2 includes this fix.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request**: The change bounds idle entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and the bounding/eviction approach, but it doesn't mention the 4.2 fix directly.



**coding_package_fix_lineage / bge_openai / trial 4**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle connections in the pool and evicting expired entries, while keeping connection reuse enabled. Upgrading to version 4.2 gives you this fix.

**Supporting sources:**
- **release_notes:** Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse remains enabled.
- **pull_request:** The change bounds idle pool entries and evicts expired connections, eliminating exhaustion without disabling reuse.
- **package_docs:** Reuse should remain enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on but does not describe the fix itself.



**coding_package_fix_lineage / bge_openai / trial 5**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

Bound the idle pool entries and evict expired connections, while keeping connection reuse enabled. Don't disable reuse to fix the problem.

Sources supporting this:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse remains enabled.
- **pull_request**: The change bounds idle pool entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and the bounding/eviction approach, but it doesn't explicitly describe the fix.

If you're on an older version, the sources suggest upgrading to 4.2 or later, since that release includes the fix.



**coding_package_fix_lineage / bge_openai / trial 6**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Version 4.2 includes this fix.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse stays enabled.
- **pull_request**: The change bounds idle entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: This supports the approach only partly. It says reuse should remain enabled and that the client bounds pool size and idle-entry eviction. It does not mention the 4.2 fix specifically.



**coding_package_fix_lineage / bge_openai / trial 7**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Release 4.2 includes this fix, so upgrading to it is the route the sources point to. Disabling reuse isn't needed.

**Supporting sources:**
- **release_notes:** Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse remains enabled.
- **pull_request:** The change bounds idle pool entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs:** Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and the bounded and evicting behavior, but it doesn't mention the specific fix or version.



**coding_package_fix_lineage / bge_openai / trial 8**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Release 4.2 ships this fix.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse remains enabled.
- **pull_request**: The change bounds idle pool entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and bounding the pool, but it does not mention the 4.2 fix directly.



**coding_package_fix_lineage / bge_openai / trial 9**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while leaving connection reuse enabled. Version 4.2 includes this fix.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse stays enabled.
- **pull_request**: The change bounds idle pool entries and evicts expired connections, which eliminates exhaustion without disabling reuse.
- **package_docs**: This supports the approach only partly. It says reuse should stay enabled and that the client bounds pool size and idle-entry eviction. It does not describe the fix itself.



**coding_package_fix_lineage / bge_openai / trial 10**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle connections and evicting expired entries, while keeping connection reuse enabled. Disabling reuse is not needed.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request**: The change bounds idle pool entries and evicts expired connections, eliminating exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and bounding the pool, but it does not explicitly describe the fix.

Together, these indicate that the fix is the 4.2 bounding-and-eviction behavior. The sources do not give specific upgrade or configuration steps beyond that.



**coding_package_fix_lineage / bge_omneum / trial 1**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Release 4.2 includes this fix.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request**: The change bounds idle entries and evicts expired connections, eliminating exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This is consistent with the fix but does not mention the exhaustion issue directly.



**coding_package_fix_lineage / bge_omneum / trial 2**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Version 4.2 includes this fix.

**Supporting sources:**
- **release_notes:** Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse remains enabled.
- **pull_request:** The change bounds idle pool entries and evicts expired connections, which eliminates exhaustion without disabling reuse.
- **package_docs:** This supports the "keep reuse enabled" part, and says the client bounds pool size and idle-entry eviction. It does not describe the fix itself.



**coding_package_fix_lineage / bge_omneum / trial 3**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix the pool exhaustion by bounding idle connections and evicting expired entries, while keeping connection reuse enabled. Reuse should not be disabled.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request**: The change bounds idle pool entries and evicts expired connections, eliminating exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports the approach but does not explicitly mention the fix.



**coding_package_fix_lineage / bge_omneum / trial 4**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Version 4.2 includes this fix, so upgrading to it should resolve the problem.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse stays enabled.
- **pull_request**: The change bounds idle pool entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: Reuse should remain enabled in normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on, but it doesn't describe the fix itself.



**coding_package_fix_lineage / bge_omneum / trial 5**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Release 4.2 includes this fix, so upgrading to it is the practical route.

**Supporting sources:**
- **release_notes:** Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse stays enabled.
- **pull_request:** The change bounds idle pool entries and evicts expired connections, which eliminates exhaustion without disabling reuse.
- **package_docs:** Reuse should stay enabled under normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and bounding the pool, but it does not mention the exhaustion fix directly.



**coding_package_fix_lineage / bge_omneum / trial 6**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Disabling reuse isn't needed. Version 4.2 includes this fix.

**Supporting sources:**
- **release_notes:** Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse stays enabled.
- **pull_request:** The change bounds idle entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs:** Reuse should remain enabled in normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and the bounding/eviction approach, but it doesn't mention the 4.2 fix specifically.



**coding_package_fix_lineage / bge_omneum / trial 7**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Version 4.2 includes this fix.

Supporting sources:
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, and reuse remains enabled.
- **pull_request**: The change bounds idle entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: Reuse should stay enabled, and the client bounds pool size and idle-entry eviction. This is consistent with the fix but does not describe it directly.



**coding_package_fix_lineage / bge_omneum / trial 8**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled. Version 4.2 includes this fix.

**Supporting sources:**
- **release_notes:** Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request:** The change bounds idle entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs:** Reuse should stay enabled in normal operation, and the client bounds pool size and idle-entry eviction. This supports keeping reuse on and the bounding/eviction approach, but it doesn't mention the 4.2 fix specifically.



**coding_package_fix_lineage / bge_omneum / trial 9**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should fix pool exhaustion by bounding idle pool entries and evicting expired connections, while keeping connection reuse enabled (don't disable reuse). According to the release notes, this is the fix shipped in version 4.2.

**Supporting sources:**
- **release_notes:** Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse remaining enabled.
- **pull_request:** The change bounds idle pool entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs:** Supports the "keep reuse enabled" part, noting that the client bounds pool size and idle-entry eviction. It doesn't explicitly describe the fix itself.



**coding_package_fix_lineage / bge_omneum / trial 10**

Recorded: unscored. Manual: correct. Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.

Reference: Bound idle connections and evict expired entries while keeping connection reuse enabled.

Selected: release_notes, package_docs, pull_request

The client should bound idle pool entries and evict expired connections, while keeping connection reuse enabled (don't disable it). Upgrading to version 4.2, which includes this fix, accomplishes this.

**Supporting sources:**
- **release_notes**: Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries, with reuse still enabled.
- **pull_request**: The change bounds idle pool entries and evicts expired connections to eliminate exhaustion without disabling reuse.
- **package_docs**: Supports keeping reuse enabled and notes that the client bounds pool size and idle-entry eviction. It doesn't describe the fix itself.



**multi_agent_independent_error / bge_openai / trial 3**

Recorded: unscored. Manual: correct. Correct 120-second delay; normalized 120-second is not required substring 120 seconds.

Reference: Wait 120 seconds before retrying.

Selected: api_result, tool_result

The orchestrator should read `Retry-After: 120` as a 120-second delay and wait that long before retrying the request.

Both sources support this:
- **api_result (EU invoice API response schema):** `Retry-After` can be delay-seconds or an HTTP date. A numeric value of 120 requires a 120-second wait.
- **tool_result (HTTP conformance tool, invoice sandbox):** Numeric `Retry-After` values are seconds, so a header of 120 sets a 120-second retry timer.

The tool result comes from the sandbox, not necessarily production. The API schema, which covers the EU invoice API itself, gives the same interpretation.



**multi_agent_independent_error / bge_openai / trial 7**

Recorded: unscored. Manual: correct. Correct 120-second delay; normalized 120-second is not required substring 120 seconds.

Reference: Wait 120 seconds before retrying.

Selected: api_result, tool_result

The orchestrator should read `Retry-After: 120` as a 120-second delay and wait that long before retrying the request.

Both sources support this:
- **api_result (EU invoice API response schema):** `Retry-After` can be delay-seconds or an HTTP date, and a numeric value of 120 requires a 120-second wait.
- **tool_result (HTTP conformance tool, invoice sandbox):** Numeric `Retry-After` values are seconds, so a header of 120 sets a 120-second retry timer.

One caveat is that the tool_result comes from the sandbox, not necessarily production. The api_result schema is the direct source for the EU invoice API, and the sandbox result agrees with it.



**multi_agent_independent_error / bge_openai / trial 10**

Recorded: unscored. Manual: correct. Correct 120-second delay; normalized 120-second is not required substring 120 seconds.

Reference: Wait 120 seconds before retrying.

Selected: api_result, tool_result

The orchestrator should read `Retry-After: 120` as a 120-second delay and wait that long before retrying the request.

Both sources support this:
- **api_result (EU invoice API response schema):** Retry-After can be delay-seconds or an HTTP date, and a numeric value of 120 requires a 120-second wait.
- **tool_result (HTTP conformance tool, invoice sandbox):** numeric Retry-After values are seconds, so a header of 120 sets a 120-second retry timer.

One caveat: the tool_result comes from the sandbox, not necessarily the live API. The schema in api_result is the direct source for the current EU invoice API, and the tool_result is consistent with it.



**research_independent_false_consensus / bge_omneum / trial 1**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes.** All three sources give this figure:

- **Analysis (Property Lab):** reports 240 occupied homes, based on its own digitized parcel footprints.
- **Report (Urban Metrics):** counted 240 homes on the site map and reported 240 occupied. It did no household interviews.
- **Publication (Housing Review):** estimates 240 occupied homes from its own facade survey.

None of the sources mentions the August 2026 census. Each figure comes from a separate method (footprints, a site map, a facade survey), not from census data. The sources agree on 240, but none confirms it as the census count or shows how vacant units were excluded. The report's method in particular, counting homes on a map without interviews, cannot really distinguish occupied from vacant homes.



**research_independent_false_consensus / bge_omneum / trial 2**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes**, with the caveat below.

Three sources give that figure:
- **Analysis (Property Lab):** 240 occupied homes, from its own digitized parcel footprints.
- **Report (Urban Metrics):** 240 occupied homes, from a count of homes on the site map. It did no household interviews.
- **Publication (Housing Review):** about 240 occupied homes, estimated from its own facade survey.

**Caveat:** None of the sources mentions the August 2026 census. Each figure comes from a different method (footprints, site map, facade survey), and none verifies occupancy directly. So 240 is the consistent figure across the sources, but they do not confirm it as the census count excluding vacant units.



**research_independent_false_consensus / bge_omneum / trial 3**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes.** This is the figure in all three sources, but none of them is the August 2026 census itself.

- **Property Lab analysis:** reports 240 occupied homes, based on its own digitized parcel footprints.
- **Urban Metrics report:** counted 240 homes on the site map and reported 240 occupied. It did no household interviews, so occupancy was not directly verified.
- **Housing Review publication:** estimates 240 occupied homes from its own facade survey.

None of the sources mentions the August 2026 census or how vacant units were handled. The figure comes from three separate methods (parcel footprints, a site-map count and a facade survey) that all arrive at 240. It is a consistent estimate, not a confirmed census count.



**research_independent_false_consensus / bge_omneum / trial 4**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes, with a caveat.**

All three sources give the same figure:
- **Property Lab analysis** reports 240 occupied homes, based on digitized parcel footprints.
- **Urban Metrics report** counted 240 homes on the site map and reported 240 occupied. It notes that no household interviews were done.
- **Housing Review publication** estimates 240 occupied homes from a facade survey.

None of the sources mentions an August 2026 census. Each figure comes from its own map, footprint, or facade method, and none is a census count. The sources also don't show how occupancy was verified or how vacant units were excluded. So 240 is the consistently reported figure, but the sources don't confirm it as the August 2026 census result.



**research_independent_false_consensus / bge_omneum / trial 5**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes, with a caveat.**

Three sources give this figure:
- **Analysis (Property Lab):** reports 240 occupied homes, based on digitized parcel footprints.
- **Report (Urban Metrics):** counted 240 homes on the site map and reported 240 occupied. It did no household interviews, so occupancy wasn't directly verified.
- **Publication (Housing Review):** estimates 240 occupied homes from a facade survey.

The caveat is that none of the sources mentions the August 2026 census. Each figure comes from its own method (footprints, map count, facade survey). So the sources agree on 240, but they don't confirm that this is the census count or that vacant units were excluded.



**research_independent_false_consensus / bge_omneum / trial 6**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes, with a caveat.**

Three sources give this figure:
- **Property Lab analysis** reports 240 occupied homes, based on its digitized parcel footprints.
- **Urban Metrics report** reports 240 occupied homes, based on a count of 240 homes on the site map. It did no household interviews, so it did not verify occupancy.
- **Housing Review publication** estimates 240 occupied homes, based on a facade survey.

None of the sources mentions the August 2026 census. Each figure comes from its own method (parcel digitization, a map count, a facade survey), not from census data. The sources therefore support 240 as the reported or estimated number, but they do not confirm it as the August 2026 census count excluding vacant units.



**research_independent_false_consensus / bge_omneum / trial 7**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes**, with a caveat about what the sources actually cover.

- **Analysis (Property Lab):** reports 240 occupied homes, based on its own digitized parcel footprints.
- **Report (Urban Metrics):** reports 240 occupied homes, based on its own count of homes on the site map. It did no household interviews, so occupancy wasn't directly verified.
- **Publication (Housing Review):** estimates 240 occupied homes, based on its own facade survey.

All three reach 240 by different methods. However, none of them says it is the August 2026 census, and none describes how vacant units were excluded. So 240 is well supported as the reported figure, but the sources don't confirm it is the census count.



**research_independent_false_consensus / bge_omneum / trial 8**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes.**

All three sources give this figure:
- **Analysis (Property Lab):** 240 occupied homes, from its own digitized parcel footprints.
- **Report (Urban Metrics):** 240 occupied homes, from its own count on the site map.
- **Publication (Housing Review):** an estimate of 240 occupied homes, from its own facade survey.

None of the sources mentions the August 2026 census, so they don't confirm that 240 is the census figure. They also rely on different methods: footprints, a site map and a facade survey. The Urban Metrics report did no household interviews, and the Housing Review figure is only an estimate. The agreement on 240 is therefore consistent, but occupancy was not directly verified.



**research_independent_false_consensus / bge_omneum / trial 9**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes.** All three sources give this figure:

- **Analysis (Property Lab):** 240 occupied homes, from its own digitized parcel footprints.
- **Report (Urban Metrics):** 240 occupied homes, from a count of homes on the site map. It did no household interviews.
- **Publication (Housing Review):** an estimate of 240 occupied homes, from its own facade survey.

None of the sources mentions the August 2026 census. Each figure comes from a separate method (parcel digitization, a site-map count, a facade survey), so they are not census results. The agreement on 240 is consistent, but the sources do not confirm that it is the census count. The Urban Metrics count in particular is of homes on a map, and without interviews it does not clearly separate occupied from vacant units.



**research_independent_false_consensus / bge_omneum / trial 10**

Recorded: unscored. Manual: incorrect. Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer.

Reference: There were 216 occupied homes in the August census.

Selected: analysis, report, publication

**Answer: 240 occupied homes.** All three sources give this figure:

- **Property Lab analysis** reports 240 occupied homes, based on its own digitized parcel footprints.
- **Urban Metrics report** reports 240 occupied homes, based on a count of 240 homes on the site map. It did no household interviews.
- **Housing Review publication** estimates 240 occupied homes, based on its own facade survey.

None of the sources mentions the August 2026 census itself, so I can't confirm the figure comes from that census. The three methods (parcel footprints, a site-map count and a facade survey) are independent, but none directly verified occupancy. The Urban Metrics count in particular was of homes on a map, not of confirmed occupied units. The agreement on 240 is therefore consistent but indirect.



**support_resolution_conflict / bge_openai / trial 1**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle (the one before tb18) and keep certificate verification enabled. They should not disable TLS verification as a workaround.

- **service_state:** The error is `upstream_tls_verify_failed`. The upstream certificate chain ends at Alder-CA, and the current tb18 bundle does not contain that issuer. This points to the trust-bundle deployment as the cause.
- **runbook:** When a trust-bundle deployment removes an upstream issuer, roll back to the last working trust bundle and retain certificate verification.

The sources don't name the previous bundle's version or give the rollback steps, so support will need to identify the last working bundle from deployment records.



**support_resolution_conflict / bge_openai / trial 2**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle, and keep certificate verification enabled. Do not disable TLS verification as a workaround.

**Supporting sources:**
- **service_state:** The error is `upstream_tls_verify_failed`. The upstream chain ends at Alder-CA, and the current tb18 bundle does not include that issuer. So the deployment removed a needed issuer.
- **runbook:** When a trust-bundle deployment removes an upstream issuer, roll back to the last working trust bundle and retain certificate verification.

The sources do not name the last working bundle's version, so support will need to identify it before rolling back.



**support_resolution_conflict / bge_openai / trial 5**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle, and keep certificate verification enabled. They should not disable TLS verification as a workaround.

- **service_state:** The errors are `upstream_tls_verify_failed`. The upstream certificate chain ends at Alder-CA, and the current tb18 bundle does not contain that issuer. So the deployment removed a needed issuer.
- **runbook:** When a trust-bundle deployment removes an upstream issuer, roll back to the last working trust bundle and retain certificate verification.

The sources don't name the last working bundle version, so support will need to identify it from deployment history. The sources also don't cover the longer-term fix, such as re-adding Alder-CA to a new bundle.



**support_resolution_conflict / bge_openai / trial 6**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle (replacing the current tb18 bundle) and keep certificate verification enabled. They should not disable TLS verification as a workaround.

**Supporting sources:**
- **service_state:** The errors are `upstream_tls_verify_failed`, the upstream chain ends at Alder-CA, and the current tb18 bundle does not contain that issuer. This points to the trust-bundle deployment as the cause.
- **runbook:** When a trust-bundle deployment removes an upstream issuer, the TLS incident runbook says to roll back to the last working trust bundle and retain certificate verification.

The sources don't name the last working bundle's version, so support would need to identify it from deployment history.



**support_resolution_conflict / bge_openai / trial 7**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle (replacing the current tb18 bundle) and keep certificate verification enabled. They should not disable TLS verification as a workaround.

**Supporting sources:**
- **service_state:** The errors are `upstream_tls_verify_failed`. The upstream certificate chain ends at Alder-CA, and the current tb18 bundle does not contain that issuer. This points to the trust-bundle deployment as the cause.
- **runbook:** When a trust-bundle deployment removes an upstream issuer, the TLS incident runbook says to roll back to the last working trust bundle and retain certificate verification.

The sources don't name the last working bundle's version, so support will need to identify it before rolling back.



**support_resolution_conflict / bge_openai / trial 8**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle (replacing the current tb18 bundle) and keep certificate verification enabled. Do not disable TLS verification as a workaround.

**Supporting sources:**
- **service_state:** The error is `upstream_tls_verify_failed`. The upstream certificate chain ends at Alder-CA, and the current tb18 bundle does not contain that issuer. This shows the deployment removed a needed issuer.
- **runbook:** When a trust-bundle deployment removes an upstream issuer, roll back to the last working trust bundle and retain certificate verification.

The sources do not name the last working bundle. Support will need to identify it, for example the bundle in place before tb18.



**support_resolution_conflict / bge_openai / trial 9**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle, and keep certificate verification enabled. Don't disable TLS verification as a workaround.

- **Service state:** The errors are `upstream_tls_verify_failed`. The upstream certificate chain ends at Alder-CA, and the current tb18 bundle doesn't include that issuer. This shows the new deployment removed a needed issuer.
- **Runbook:** When a trust-bundle deployment removes an upstream issuer, roll back to the last working trust bundle and retain certificate verification.

Note: The sources don't name the last working bundle's version, so support will need to identify it. They also don't say how to perform the rollback.



**support_resolution_conflict / bge_openai / trial 10**

Recorded: unscored. Manual: partial. Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, runbook

Support should roll back to the last working trust bundle, and should keep certificate verification enabled. They should not disable TLS verification as a workaround.

- **Why:** The service state shows `upstream_tls_verify_failed`. The upstream certificate chain ends at Alder-CA, and the current tb18 bundle does not contain that issuer. This matches the runbook's condition of a trust-bundle deployment removing an upstream issuer.
- **What to do:** The runbook says to roll back to the last working trust bundle and retain certificate verification.

**Sources:** `service_state` supports the cause (tb18 is missing the Alder-CA issuer). `runbook` supports the action (roll back and keep verification on).

The sources don't name the last working bundle, so support will need to identify it from deployment history.



**support_resolution_conflict / bge_omneum / trial 7**

Recorded: unscored. Manual: correct. Correct tb18-to-tb17 rollback and keeping upstream_tls_verify enabled; wording lacks required substring verification.

Reference: Roll back the trust bundle to tb17 while keeping TLS verification enabled.

Selected: service_state, deployment_config

**Support should roll back the production trust bundle from tb18 to tb17, or escalate to whoever owns deployments to do so.** Do not disable `upstream_tls_verify`.

- **Cause:** The upstream certificate chain ends at Alder-CA, and the current tb18 bundle does not contain that issuer. That explains the `upstream_tls_verify_failed` errors right after the deployment. *(Source: service_state)*
- **Fix:** Production runs `trust_bundle=tb18` with `upstream_tls_verify=true`. Revision tb17 is still available for rollback and includes Alder-CA. *(Source: deployment_config)*

The sources do not describe a support runbook or say who is authorized to roll back. They also do not say whether tb18 should later be corrected to add Alder-CA. The rollback recommendation is an inference from the two facts above, not an explicit instruction.



**support_stale_runbook / bge_openai / trial 1**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 2**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 3**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 4**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 5**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 6**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 7**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 8**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 9**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_openai / trial 10**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 1**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 2**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 3**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 4**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 5**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 6**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 7**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 8**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 9**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



**support_stale_runbook / bge_omneum / trial 10**

Recorded: generation_failure. Manual: generator_refusal. Explicit Anthropic stop_reason=refusal; empty content; no answer to assess.

Reference: POST /admin/keys/refresh, then confirm the loaded key ID.

Selected: current_runbook, incident_record, deployment_config

Empty answer. Diagnostics: `{"content_block_types": [], "stop_reason": "refusal", "usage_metadata": {"input_tokens": 280, "output_tokens": 0, "reasoning_tokens": null}}`



Source artifact SHA-256 hashes

```json
{
  "benchmarks/financial_dependency_suite/heldout/results/bge-openai-vs-bge-omneum-20261008/manifest.json": "be6320d1498c125bcf12015e41eac8ecac38762bea03381ab9765e4b581641b3",
  "benchmarks/financial_dependency_suite/heldout/results/bge-openai-vs-bge-omneum-20261008/summary.json": "834eb789b6d1c5b50d8c8beda10de202675414334564ca24c63062a4aadab202",
  "benchmarks/financial_dependency_suite/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl": "ecd99f2707e8511d8b3637a0a7aff94b32bc7ef1ada364b45312552dca5f6196"
}
```
