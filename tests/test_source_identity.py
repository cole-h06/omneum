from uuid import UUID

from omneum.canonicalization import canonicalize_source


SCOPE_A = "12345678-1234-4abc-8def-123456789abc"
SCOPE_B = "87654321-4321-4abc-8def-cba987654321"


def test_deterministic():
    from omneum.sources import internal_source_id

    first = internal_source_id(SCOPE_A, "config-1847")
    second = internal_source_id(SCOPE_A, "config-1847")

    assert first == second


def test_distinct_objects():
    from omneum.sources import internal_source_id

    assert (
        internal_source_id(SCOPE_A, "config-1847")
        != internal_source_id(SCOPE_A, "config-2911")
    )


def test_distinct_scopes():
    from omneum.sources import internal_source_id

    assert (
        internal_source_id(SCOPE_A, "config-1847")
        != internal_source_id(SCOPE_B, "config-1847")
    )


def test_canonical_form():
    from omneum.sources import internal_source_id

    value = internal_source_id(SCOPE_A, "config-1847")

    prefix, scope_uuid, object_uuid = value.split(":")

    assert prefix == "v1"
    assert scope_uuid == SCOPE_A
    assert UUID(object_uuid)
    assert canonicalize_source("internal_resource", value) == value
