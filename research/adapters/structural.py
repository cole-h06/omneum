from collections.abc import Mapping, Sequence
from itertools import combinations

from omneum.engine_graph import AssertionTriple, InferenceGraph, SourcePair
from omneum.engine_graph import build_graph as build_inference_graph


def build_graph(
    assertions: Sequence[tuple[str, str, str]],
    dependency_matrix: Mapping[str, Mapping[str, float]] | None = None,
    coverage_matrix: Mapping[str, Mapping[str, float]] | None = None,
    *,
    exact_equivalences: Sequence[tuple[str, str]] = (),
) -> InferenceGraph:
    sources = sorted({source for source, _, _ in assertions})
    for matrix in (dependency_matrix, coverage_matrix):
        if matrix is None:
            continue
        if set(matrix) != set(sources) or any(
            set(matrix[source]) != set(sources) for source in sources
        ):
            raise ValueError("pair matrix must contain exactly the graph sources")
        if any(matrix[source][source] != 0.0 for source in sources):
            raise ValueError("pair diagonal must be zero")
        if any(matrix[a][b] != matrix[b][a] for a, b in combinations(sources, 2)):
            raise ValueError("pair matrix must be symmetric")

    equivalences = {tuple(sorted(pair)) for pair in exact_equivalences}
    pairs = set(combinations(sources, 2))
    if not equivalences <= pairs:
        raise ValueError("exact equivalence requires two distinct graph sources")
    return build_inference_graph(
        [AssertionTriple(*row) for row in assertions],
        [
            SourcePair(
                a, b,
                0.0 if dependency_matrix is None else dependency_matrix[a][b],
                0.0 if coverage_matrix is None else coverage_matrix[a][b],
                exact_equivalence=(a, b) in equivalences,
            )
            for a, b in sorted(pairs)
        ],
    )
