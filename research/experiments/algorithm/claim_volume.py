from omneum.inference import infer

from ...adapters.structural import build_graph


ASSERTIONS = [
    ("source_1", "shared_claim", "shared_claim"),
    ("source_2", "extra_1", "extra_1"),
    ("source_2", "extra_2", "extra_2"),
    ("source_2", "extra_3", "extra_3"),
    ("source_2", "extra_4", "extra_4"),
    ("source_2", "extra_5", "extra_5"),
    ("source_2", "shared_claim", "shared_claim"),
]

DEPENDENCY = {
    "source_1": {"source_1": 0.0, "source_2": 0.0},
    "source_2": {"source_1": 0.0, "source_2": 0.0},
}

result = infer(build_graph(ASSERTIONS, DEPENDENCY))
print(result)
