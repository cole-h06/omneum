from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _Assertion:
    """
    Internal representation of a single assertion.
    """

    source_kind: str
    source: str

    entity_namespace: str
    entity: str

    attribute: str
    value: Any


class BipartiteGraph:
    """
    A bipartite graph of sources and claims constructed from submitted assertions.
    """

    def __init__(self) -> None:
        self._assertions: list[_Assertion] = []

    @property
    def assertions(self) -> tuple[_Assertion, ...]:
        return tuple(self._assertions)

    def add(
        self,
        source_kind: str,
        source: str,
        entity_namespace: str,
        entity: str,
        attribute: str,
        value: Any,
    ) -> None:
        """
        Adds an assertion to the graph.
        """

        self._assertions.append(
            _Assertion(
                source_kind=source_kind,
                source=source,
                entity_namespace=entity_namespace,
                entity=entity,
                attribute=attribute,
                value=value,
            )
        )

    def __len__(self) -> int:
        return len(self._assertions)
