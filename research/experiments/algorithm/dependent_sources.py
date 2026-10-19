from omneum.inference import infer

from .context import build_graph, DEPENDENT


result = infer(build_graph(DEPENDENT))

print(result)
