from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .dependency import DependencySignal, SIGNALS
from .information import Observation
from .observations import observe, reference


Extractor = str | Callable[[Any], Any]
SignalExtractor = Callable[[Any], DependencySignal]


def _extract(item: Any, path: Extractor) -> Any:
    if callable(path):
        return path(item)

    value = item
    for part in path.split("."):
        if isinstance(value, Mapping):
            value = value.get(part)
        else:
            value = getattr(value, part, None)

        if value is None:
            return None
    return value


def _normalize_source_references(value):
    if value is None:
        return None

    if isinstance(value, tuple):
        values = value
    elif isinstance(value, list):
        values = tuple(value)
    else:
        values = (value,)

    return tuple(
        item
        if hasattr(item, "kind") and hasattr(item, "identifier")
        else reference(kind=item["kind"], identifier=item["identifier"])
        if isinstance(item, Mapping)
        else (_ for _ in ()).throw(
            TypeError("source references must include kind and identifier")
        )
        for item in values
    )


class ContextMapper:
    def __init__(
        self,
        *,
        source: Extractor,
        entity_namespace: Extractor,
        entity: Extractor,
        attribute: Extractor,
        value: Extractor,
        observation_id: Extractor | None = None,
        observed_at: Extractor,
        source_modified_at: Extractor | None = None,
        upstream_sources: Extractor | None = None,
        cited_sources: Extractor | None = None,
        parent_observation_ids: Extractor | None = None,
        retrievals: Extractor | None = None,
        metadata: Mapping[str, Extractor] | None = None,
        signals: Mapping[str, SignalExtractor] | None = None,
        assertion_id: Extractor | None = None,
        parent_assertion_ids: Extractor | None = None,
    ) -> None:
        if observation_id is None:
            observation_id = assertion_id
        elif assertion_id is not None:
            raise ValueError("specify only one observation ID extractor")
        if observation_id is None:
            raise TypeError("observation_id is required")
        if parent_observation_ids is None:
            parent_observation_ids = parent_assertion_ids
        elif parent_assertion_ids is not None:
            raise ValueError("specify only one parent observation ID extractor")
        self._mapping = {
            "source": source,
            "entity_namespace": entity_namespace,
            "entity": entity,
            "attribute": attribute,
            "value": value,
            "observation_id": observation_id,
            "observed_at": observed_at,
            "source_modified_at": source_modified_at,
            "upstream_sources": upstream_sources,
            "cited_sources": cited_sources,
            "parent_observation_ids": parent_observation_ids,
            "retrievals": retrievals,
        }

        self._metadata_mapping = (
            {} if metadata is None else dict(metadata)
        )

        self._signal_mapping = (
            {} if signals is None else dict(signals)
        )

        unknown_signals = set(self._signal_mapping) - set(SIGNALS)
        if unknown_signals:
            raise ValueError(
                "unsupported dependency signals: "
                + ", ".join(sorted(unknown_signals))
            )

    def map(self, item: Any) -> Observation:
        values = {
            name: (
                None
                if extractor is None
                else _extract(item, extractor)
            )
            for name, extractor in self._mapping.items()
        }

        if values["parent_observation_ids"] is not None:
            if isinstance(values["parent_observation_ids"], str):
                values["parent_observation_ids"] = (
                    values["parent_observation_ids"],
                )
            else:
                values["parent_observation_ids"] = tuple(
                    values["parent_observation_ids"]
                )

        metadata = {
            name: _extract(item, extractor)
            for name, extractor in self._metadata_mapping.items()
        }

        signals = {
            name: extractor(item)
            for name, extractor in self._signal_mapping.items()
        }

        return observe(
            observation_id=values["observation_id"],
            source=values["source"],
            entity_namespace=values["entity_namespace"],
            entity=values["entity"],
            attribute=values["attribute"],
            value=values["value"],
            observed_at=values["observed_at"],
            source_modified_at=values["source_modified_at"],
            upstream_sources=_normalize_source_references(values["upstream_sources"]),
            cited_sources=_normalize_source_references(values["cited_sources"]),
            parent_observation_ids=values["parent_observation_ids"],
            retrievals=values["retrievals"],
            metadata=metadata,
            dependency_signals=signals,
        )

    def map_many(self, items: Sequence[Any]) -> tuple[Observation, ...]:
        return tuple(self.map(item) for item in items)
