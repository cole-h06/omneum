from omneum.inference import infer

from ...adapters.structural import build_graph


ASSERTIONS = [
    ("source_1", "claim_a", "claim_a"),
    ("source_1", "claim_b", "claim_b"),
    ("source_2", "claim_a", "claim_a"),
    ("source_2", "claim_c", "claim_c"),
    ("source_3", "claim_a", "claim_a"),
    ("source_3", "claim_d", "claim_d"),
    ("source_4", "claim_b", "claim_b"),
    ("source_4", "claim_d", "claim_d"),
    ("source_5", "claim_c", "claim_c"),
    ("source_5", "claim_d", "claim_d"),
]

DEPENDENCY = {
    "source_1": {"source_1": 0.0, "source_2": 0.8, "source_3": 0.1, "source_4": 0.2, "source_5": 0.0},
    "source_2": {"source_1": 0.8, "source_2": 0.0, "source_3": 0.2, "source_4": 0.1, "source_5": 0.3},
    "source_3": {"source_1": 0.1, "source_2": 0.2, "source_3": 0.0, "source_4": 0.4, "source_5": 0.2},
    "source_4": {"source_1": 0.2, "source_2": 0.1, "source_3": 0.4, "source_4": 0.0, "source_5": 0.5},
    "source_5": {"source_1": 0.0, "source_2": 0.3, "source_3": 0.2, "source_4": 0.5, "source_5": 0.0},
}

result = infer(build_graph(ASSERTIONS, DEPENDENCY))
print(result)
