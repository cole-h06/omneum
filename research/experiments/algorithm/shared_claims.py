from omneum.inference import infer

from ...adapters.structural import build_graph


ASSERTIONS = [
    ("source_1", "claim_a", "claim_a"),
    ("source_1", "claim_b", "claim_b"),
    ("source_2", "claim_a", "claim_a"),
    ("source_3", "claim_a", "claim_a"),
]

DEPENDENCY = {
    "source_1": {"source_1": 0.0, "source_2": 0.9, "source_3": 0.0},
    "source_2": {"source_1": 0.9, "source_2": 0.0, "source_3": 0.0},
    "source_3": {"source_1": 0.0, "source_2": 0.0, "source_3": 0.0},
}

result = infer(build_graph(ASSERTIONS, DEPENDENCY))
print(result)
