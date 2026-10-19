from omneum.inference import infer

from ...adapters.structural import build_graph


BASE_ASSERTIONS = [
    ("source_1", "claim_a", "claim_a"),
    ("source_2", "claim_a", "claim_a"),
]

BASE_DEPENDENCY = {
    "source_1": {"source_1": 0.0, "source_2": 0.0},
    "source_2": {"source_1": 0.0, "source_2": 0.0},
}

base_result = infer(build_graph(BASE_ASSERTIONS, BASE_DEPENDENCY))
print(base_result)


ADDITIONAL_CLAIM_ASSERTIONS = [
    ("source_1", "claim_a", "claim_a"),
    ("source_2", "claim_a", "claim_a"),
    ("source_2", "claim_b", "claim_b"),
]

ADDITIONAL_CLAIM_DEPENDENCY = {
    "source_1": {"source_1": 0.0, "source_2": 0.0},
    "source_2": {"source_1": 0.0, "source_2": 0.0},
}

additional_claim_result = infer(build_graph(ADDITIONAL_CLAIM_ASSERTIONS, ADDITIONAL_CLAIM_DEPENDENCY))
print(additional_claim_result)
