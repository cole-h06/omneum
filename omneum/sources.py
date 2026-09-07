import uuid


def internal_source_id(
    scope_uuid: str,
    object_id: str,
) -> str:
    if type(scope_uuid) is not str:
        raise TypeError("scope_uuid must be a string")

    if type(object_id) is not str:
        raise TypeError("object_id must be a string")

    if not object_id:
        raise ValueError("object_id must not be empty")

    try:
        scope = uuid.UUID(scope_uuid)
    except (ValueError, AttributeError):
        raise ValueError("scope_uuid must be a UUID") from None

    if scope.int == 0 or scope.int == (1 << 128) - 1:
        raise ValueError("scope_uuid must not be Nil or Max UUID")

    object_uuid = uuid.uuid5(scope, object_id)

    return f"v1:{scope}:{object_uuid}"
