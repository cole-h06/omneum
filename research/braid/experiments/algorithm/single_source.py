from omneum.inference import infer

from ...adapters.structural import build_graph


ASSERTIONS = [
    ("source_1", "claim_a", "claim_a"),
]

DEPENDENCY = {
    "source_1": {"source_1": 0.0},
}

result = infer(build_graph(ASSERTIONS, DEPENDENCY))
print(result)
