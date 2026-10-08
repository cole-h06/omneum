"""Lossless candidate inventory and conservative point mapping; no evaluation runner."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import unicodedata


DEFAULT_DATASET = Path(__file__).parent / "data" / "world.json"
NORMALIZATION_VERSION = "isolated-point-text-v1"


def normalize_point(text):
    """Normalize typography, case, whitespace and a final period only.

    No entity resolution, paraphrase merging, stemming, or factual inference.
    """
    text = unicodedata.normalize("NFC", text).translate(
        str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
    )
    return " ".join(text.casefold().split()).removesuffix(".").rstrip()


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def adapt_dataset(dataset):
    """Keep every record; baseline fields never enter assertion observations."""
    raw = deepcopy(dataset)
    candidates = []
    seen = set()
    for record in raw["items"]:
        candidate_id = record.get("id")
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in seen:
            raise ValueError("candidate IDs must be nonempty unique strings")
        seen.add(candidate_id)
        points = record.get("points_isolated")
        issues = []
        if points is None:
            points = []
            issues.append("missing_points_isolated")
        elif not isinstance(points, list):
            points = []
            issues.append("invalid_points_isolated")
        assertions = []
        by_text = {}
        for index, point in enumerate(points):
            if not isinstance(point, str) or not normalize_point(point):
                issues.append(f"unusable_point:{index}")
                continue
            normalized = normalize_point(point)
            # Repeated points remain in raw data and retain all occurrence indexes,
            # but are not duplicated as canonical assertions in Omneum.
            if normalized in by_text:
                by_text[normalized]["point_indexes"].append(index)
                continue
            assertion = {
                "assertion_id": json.dumps([candidate_id, index], separators=(",", ":")),
                "candidate_id": candidate_id,
                "point_indexes": [index],
                "original_text": point,
                "normalized_text": normalized,
                "alignment_key": sha256(normalized.encode()).hexdigest(),
            }
            assertions.append(assertion)
            by_text[normalized] = assertion
        url = record.get("canonical_link")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            issues.append("missing_or_invalid_canonical_link")
        if _timestamp(raw.get("generated_at")) is None:
            issues.append("missing_or_invalid_generated_at")
        eligible = bool(assertions) and not any(
            issue.startswith("missing_or_invalid_") for issue in issues
        )
        if not assertions and not issues:
            issues.append("no_usable_points")
        candidates.append({
            "candidate_id": candidate_id,
            "record": record,
            "assertions": assertions,
            "eligible": eligible,
            "issues": issues,
        })
    baseline = [{
        "candidate_id": c["candidate_id"],
        "duplicate_of": c["record"]["duplicate_of"],
        "dup_rule": c["record"].get("dup_rule"),
        "dup_score": c["record"].get("dup_score"),
    } for c in candidates if c["record"].get("duplicate_of")]
    return {"dataset": raw, "candidates": candidates, "baseline": baseline}


def load_dataset(path=DEFAULT_DATASET):
    return adapt_dataset(json.loads(Path(path).read_text()))


def observations_for_candidate(mapped, candidate_id):
    """Explicit per-candidate mapping; never silently select an evaluation pool.

    generated_at is the export observation time, not an inferred article time.
    A normalized proposition is an opaque entity key, not an extracted entity.
    Its full text is the asserted value; no additional factual claim is created.
    """
    from omneum import Claim, Observation, Source

    candidate = next(c for c in mapped["candidates"] if c["candidate_id"] == candidate_id)
    if not candidate["eligible"]:
        raise ValueError(f"candidate {candidate_id} is ineligible: {candidate['issues']}")
    return tuple(Observation(
        observation_id=a["assertion_id"],
        source=Source("web_document", candidate["record"]["canonical_link"]),
        claim=Claim("service", "briefing-point:" + a["alignment_key"],
                    "isolated point", a["normalized_text"]),
        observed_at=_timestamp(mapped["dataset"]["generated_at"]),
        source_modified_at=None,
        upstream_sources=None,
        cited_sources=None,
        parent_observation_ids=None,
        retrievals=None,
        metadata={"candidate_id": candidate_id, "point_indexes": a["point_indexes"],
                  "original_text": a["original_text"]},
    ) for a in candidate["assertions"])


def mapping_audit(mapped):
    candidates = mapped["candidates"]
    by_id = {c["candidate_id"]: c for c in candidates}
    pairs = []
    for baseline in mapped["baseline"]:
        left = by_id[baseline["candidate_id"]]
        right = by_id.get(baseline["duplicate_of"])
        shared = sorted(
            {a["normalized_text"] for a in left["assertions"]}
            & ({a["normalized_text"] for a in right["assertions"]} if right else set())
        )
        pairs.append({**baseline, "target_present": right is not None,
                      "both_eligible": bool(right and left["eligible"] and right["eligible"]),
                      "matching_normalized_assertions": shared})
    groups = {}
    urls = {}
    for c in candidates:
        urls.setdefault(c["record"].get("canonical_link"), []).append(c["candidate_id"])
        for a in c["assertions"]:
            groups.setdefault(a["normalized_text"], []).append(c["candidate_id"])
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "candidate_count": len(candidates),
        "eligible_candidate_ids": [c["candidate_id"] for c in candidates if c["eligible"]],
        "ineligible_candidates": [{"candidate_id": c["candidate_id"], "issues": c["issues"]}
                                  for c in candidates if not c["eligible"]],
        "usable_assertion_count": sum(len(c["assertions"]) for c in candidates),
        "eligible_assertion_count": sum(len(c["assertions"]) for c in candidates if c["eligible"]),
        "candidates": [{"candidate_id": c["candidate_id"], "eligible": c["eligible"],
                        "issues": c["issues"], "assertions": c["assertions"]} for c in candidates],
        "duplicate_pairs": pairs,
        "cross_candidate_exact_matches": {text: ids for text, ids in sorted(groups.items()) if len(ids) > 1},
        "shared_canonical_urls": {url: ids for url, ids in urls.items() if url and len(ids) > 1},
        "observable_dependency_signals": [],
        "unobserved_dependency_signals": ["upstream", "citation", "assertion_lineage", "ownership",
                                          "temporal", "graph", "retrieval"],
        "limitations": [
            "Exact normalized text alignment only; unmatched points are not evidence of disagreement or independence.",
            "Publication timestamps are preserved, but are not source last-modified timestamps.",
            "generated_at supplies export observation time only, not dependency evidence.",
            "Duplicate labels are external heuristic observations, not verified dependency truth.",
            "Full candidate pool is retained; no full-pool Omneum evaluation is defined for records without assertions.",
        ],
    }


if __name__ == "__main__":
    # Inventory only: no estimator, provider, network, or benchmark execution.
    print(json.dumps(mapping_audit(load_dataset()), indent=2, ensure_ascii=False))
