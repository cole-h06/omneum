from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .information import Observation
from .observations import observe


Extractor = str | Callable[[Any], Any]


def _extract(item: Any, path: Extractor) -> Any:
    if callable(path):
        return path(item)

    value = item
    for part in path.split("."):
        if isinstance(value, Mapping):
            value = value[part]
        else:
            value = getattr(value, part)
    return value


class ContextMapper:
    def __init__(
        self,
        *,
        source: Extractor,
        entity_namespace: Extractor,
        entity: Extractor,
        attribute: Extractor,
        value: Extractor,
        assertion_id: Extractor,
        observed_at: Extractor,
        source_modified_at: Extractor | None = None,
        upstream_sources: Extractor | None = None,
        cited_sources: Extractor | None = None,
        parent_assertion_ids: Extractor | None = None,
        retrievals: Extractor | None = None,
    ) -> None:
        self._mapping = {
            "source": source,
            "entity_namespace": entity_namespace,
            "entity": entity,
            "attribute": attribute,
            "value": value,
            "assertion_id": assertion_id,
            "observed_at": observed_at,
            "source_modified_at": source_modified_at,
            "upstream_sources": upstream_sources,
            "cited_sources": cited_sources,
            "parent_assertion_ids": parent_assertion_ids,
            "retrievals": retrievals,
        }

    def map(self, item: Any) -> Observation:
        values = {
            name: (
                None
                if extractor is None
                else _extract(item, extractor)
            )
            for name, extractor in self._mapping.items()
        }

        return observe(
            assertion_id=values["assertion_id"],
            source=values["source"],
            entity_namespace=values["entity_namespace"],
            entity=values["entity"],
            attribute=values["attribute"],
            value=values["value"],
            observed_at=values["observed_at"],
            source_modified_at=values["source_modified_at"],
            upstream_sources=values["upstream_sources"],
            cited_sources=values["cited_sources"],
            parent_assertion_ids=values["parent_assertion_ids"],
            retrievals=values["retrievals"],
        )

    def map_many(self, items: Sequence[Any]) -> tuple[Observation, ...]:
        return tuple(self.map(item) for item in items)
