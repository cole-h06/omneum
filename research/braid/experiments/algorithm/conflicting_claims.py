from omneum.inference import infer

from ...adapters.structural import build_graph


ASSERTIONS = [
    ("source_1", "truth", "claim_true"),
    ("source_2", "truth", "claim_true"),
    ("source_3", "truth", "claim_false"),
    ("source_4", "truth", "claim_false"),
]

DEPENDENCY = {
    "source_1": {"source_1": 0.0, "source_2": 0.0, "source_3": 0.0, "source_4": 0.0},
    "source_2": {"source_1": 0.0, "source_2": 0.0, "source_3": 0.0, "source_4": 0.0},
    "source_3": {"source_1": 0.0, "source_2": 0.0, "source_3": 0.0, "source_4": 0.0},
    "source_4": {"source_1": 0.0, "source_2": 0.0, "source_3": 0.0, "source_4": 0.0},
}

result = infer(build_graph(ASSERTIONS, DEPENDENCY))
print(result)
