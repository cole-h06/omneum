"""Run with: python -m examples.context_quality_demo.before_after"""

from dataclasses import fields
import json
import sys

import omneum
from omneum.context_selection import claim_id, token_count


def _json_default(value):
    if isinstance(value, omneum.Claim):
        return {name: getattr(value, name) for name in (
            "entity_namespace", "entity", "attribute", "value",
        )}
    return {field.name: getattr(value, field.name) for field in fields(value)}


def main():
    token_budget = 80
    claims = {
        "processing_region": "EU",
        "provider_retention_days": 0,
        "customer_content": "redacted only",
        "audit_retention_days": 365,
    }
    retrieved = [
        {
            "chunk_id": "team-faq",
            "url": "https://support.example/team-faq",
            "upstream": ["https://security.example/copilot-policy"],
            "claims": ["processing_region", "provider_retention_days"],
            "raw_text": (
                "The support copilot processes tickets in the EU. The hosted "
                "provider retains ticket content for zero days, per the security policy."
            ),
        },
        {
            "chunk_id": "wiki-mirror",
            "url": "https://wiki.example/copilot",
            "upstream": ["https://security.example/copilot-policy"],
            "claims": ["processing_region", "provider_retention_days"],
            "raw_text": (
                "Copied from the security policy: support copilot processing "
                "stays in the EU and provider retention is zero days."
            ),
        },
        {
            "chunk_id": "gateway-config",
            "url": "https://gateway.example/copilot/config",
            "upstream": [],
            "claims": ["processing_region", "provider_retention_days"],
            "raw_text": (
                "The deployed support copilot gateway reports region EU and "
                "provider content retention of zero days."
            ),
        },
        {
            "chunk_id": "security-policy",
            "url": "https://security.example/copilot-policy",
            "upstream": [],
            "claims": ["processing_region", "provider_retention_days", "customer_content"],
            "raw_text": (
                "Support copilot policy: process in the EU, require zero days "
                "of provider retention, and send only redacted customer content."
            ),
        },
        {
            "chunk_id": "audit-config",
            "url": "https://audit.example/copilot/config",
            "upstream": [],
            "claims": ["customer_content", "audit_retention_days"],
            "raw_text": (
                "The support copilot audit service accepts only redacted "
                "customer content and retains audit records for 365 days."
            ),
        },
    ]
    claim_ids = {
        attribute: claim_id(omneum.Claim("service", "support_copilot", attribute, value))
        for attribute, value in claims.items()
    }
    observations = [
        {
            "url": chunk["url"],
            "upstream": chunk["upstream"],
            "claim": {
                "entity_namespace": "service",
                "entity": "support_copilot",
                "attribute": attribute,
            },
            "value": claims[attribute],
        }
        for chunk in retrieved
        for attribute in chunk["claims"]
    ]
    chunks = [
        {
            "chunk_id": chunk["chunk_id"],
            "raw_text": chunk["raw_text"],
            "claim_ids": [claim_ids[attribute] for attribute in chunk["claims"]],
        }
        for chunk in retrieved
    ]

    evaluation = omneum.evaluate(observations)
    # Retrieval packing ignores support scores; both paths share SDK rendering and counting.
    raw = omneum.reconstruct_context(
        evaluation, chunks, token_budget=token_budget,
        strategy="retrieval", count_tokens=token_count,
    )
    prepared = omneum.reconstruct_context(
        evaluation, chunks, token_budget=token_budget,
        strategy="coverage_support", count_tokens=token_count,
    )

    print("Support copilot: processing, provider retention, redaction, and audit retention", file=sys.stderr)
    print(f"Budget: {token_budget} Unicode word/punctuation units, including chunk headers", file=sys.stderr)
    print("\nRetrieved evidence (original order; synthetic fixture)", file=sys.stderr)
    for chunk in retrieved:
        print(f"\n[{chunk['chunk_id']}] {chunk['url']}", file=sys.stderr)
        print("  Declared upstream: " + (", ".join(chunk["upstream"]) or "none"), file=sys.stderr)
        print("  Claims: " + ", ".join(chunk["claims"]), file=sys.stderr)

    print("\nStructural evaluation (all retrieved evidence)", file=sys.stderr)
    width = max(len(item.claim.attribute) for item in evaluation.claim_support) + 1
    for item in sorted(evaluation.claim_support, key=lambda item: item.claim.attribute):
        print(f"  {item.claim.attribute + ':':<{width}} "
              f"{item.supporting_source_count} sources, "
              f"{item.estimated_independent_support_count:.2f} estimated independent support", file=sys.stderr)

    for label, result in (("Raw RAG", raw), ("Omneum", prepared)):
        selected = set(result["selected_chunk_ids"])
        excluded = [chunk["chunk_id"] for chunk in chunks if chunk["chunk_id"] not in selected]
        covered = [attribute for attribute, identifier in claim_ids.items()
                   if identifier in result["covered_claim_ids"]]
        print(f"\n{label}", file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        print("  Selected (rendering order): " + ", ".join(result["selected_chunk_ids"]), file=sys.stderr)
        print(f"  Token usage: {result['token_usage']}/{token_budget}", file=sys.stderr)
        print(f"  Claim coverage: {len(covered)}/{len(claims)} ({', '.join(covered)})", file=sys.stderr)
        print("  Excluded: " + (", ".join(excluded) or "none"), file=sys.stderr)

    results = {"evaluation": evaluation, "raw_rag": raw, "omneum": prepared}
    if DEBUG_JSON:
        print(json.dumps(results, default=_json_default, indent=2, allow_nan=False))
    return results


DEBUG_JSON = False

if __name__ == "__main__":
    main()
