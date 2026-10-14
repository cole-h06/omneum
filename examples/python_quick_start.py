"""Run with: python -m examples.python_quick_start"""

from datetime import datetime, timezone

from omneum import (
    Claim, DependencyEstimatorConfig, Observation, Source,
    evaluate_context, reference,
)

claim = Claim("company", "acme", "revenue_2025", 4_200_000_000)
upstream = reference(kind="web_document", identifier="https://upstream.example/report")
observations = [
    Observation(
        observation_id=name,
        source=Source("web_document", f"https://{name}.example/report"),
        claim=claim,
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        upstream_sources=(upstream,) if name != "independent" else (),
    )
    for name in ("report-a", "report-b", "independent")
]
# Use upstream provenance as the dependency signal for this example.
estimator = DependencyEstimatorConfig(
    upstream_weight=1.0,
    citation_weight=0.0,
    assertion_lineage_weight=0.0,
    ownership_weight=0.0,
    temporal_weight=0.0,
    graph_weight=0.0,
    temporal_window_seconds=7200.0,
)
result = evaluate_context(observations, estimator=estimator)
support = result.claim_support[0].estimated_independent_support_count
print(f"Estimated independent support: {support:.2f}")
