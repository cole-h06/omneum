from omneum.inference import infer

from .context import build_graph, MIXED


result = infer(build_graph(MIXED))

print(result)
