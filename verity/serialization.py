import orjson

from typing import Any


def serialize_assertion(
    assertion: dict[str, Any],
) -> bytes:
    """
    Serializes a canonical assertion into a deterministic
    JSON byte sequence.
    """

    return orjson.dumps(
        assertion,
        option=(
            orjson.OPT_SORT_KEYS
        ),
    )