from omneum.inference import infer

from .context import build_graph


result = infer(build_graph())

print("reliability:", result.source_reliability)
print("claim support:", result.claim_support)
