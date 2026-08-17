import json
from pathlib import Path
from typing import Callable

import pytest

from omneum.canonicalization import canonicalize_value
from omneum.serialization import (
    MAX_INTEGER,
    serialize_attribute,
    serialize_claim,
    serialize_source,
)


VECTOR_PATH = (
    Path(__file__).parent
    / "vectors"
    / "canonical_linkage.json"
)


def test_linkage_vectors() -> None:
    vectors = json.loads(
        VECTOR_PATH.read_text(encoding="utf-8")
    )

    for vector in vectors:
        values = vector["input"]

        if vector["type"] == "source":
            serialized = serialize_source(**values)
        elif vector["type"] == "attribute":
            serialized = serialize_attribute(**values)
        else:
            serialized = serialize_claim(**values)

        assert serialized.hex() == vector["canonical_hex"]


def test_rfc_vector() -> None:
    value = {
        "numbers": [
            333333333.33333329,
            1e30,
            4.50,
            2e-3,
            1e-27,
        ],
        "string": "€$\u000f\nA'B\"\\\\\"/",
        "literals": [None, True, False],
    }

    serialized = serialize_claim(
        "service",
        "worker",
        "profile",
        value,
    )

    assert serialized == (
        b'{"attribute":"profile","entity":"worker",'
        b'"entity_namespace":"service","value":'
        b'{"literals":[null,true,false],"numbers":'
        b'[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        b'"string":"\xe2\x82\xac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}}'
    )


def test_utf16_key_order() -> None:
    serialized = serialize_claim(
        "service",
        "worker",
        "profile",
        {
            "\ue000": 1,
            "\U0001f600": 2,
        },
    )

    assert serialized.endswith(
        b',"value":{"\xf0\x9f\x98\x80":2,"\xee\x80\x80":1}}'
    )


def test_nested_object_order() -> None:
    first = {
        "z": {
            "b": 2,
            "a": 1,
        },
        "a": 0,
    }
    second = {
        "a": 0,
        "z": {
            "a": 1,
            "b": 2,
        },
    }

    first_serialized = serialize_claim(
        "service",
        "worker",
        "profile",
        first,
    )
    second_serialized = serialize_claim(
        "service",
        "worker",
        "profile",
        second,
    )

    assert first_serialized == second_serialized
    assert first_serialized.endswith(
        b',"value":{"a":0,"z":{"a":1,"b":2}}}'
    )


def test_unicode_output() -> None:
    serialized = serialize_claim(
        "service",
        "caf\u00e9",
        "weather",
        "\u96ea",
    )

    assert b"caf\xc3\xa9" in serialized
    assert b"\xe9\x9b\xaa" in serialized


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, b"0"),
        (-0.0, b"0"),
        (1e-6, b"0.000001"),
        (1e20, b"100000000000000000000"),
        (1e-7, b"1e-7"),
        (1e21, b"1e+21"),
    ],
)
def test_number_format(
    value: float,
    expected: bytes,
) -> None:
    serialized = serialize_claim(
        "service",
        "worker",
        "ratio",
        value,
    )

    assert serialized.endswith(
        b',"value":' + expected + b"}"
    )


def test_equivalent_numbers() -> None:
    integer = serialize_claim(
        "service",
        "worker",
        "count",
        1,
    )
    floating = serialize_claim(
        "service",
        "worker",
        "count",
        1.0,
    )

    assert integer == floating


@pytest.mark.parametrize(
    "value",
    [
        -MAX_INTEGER,
        MAX_INTEGER,
    ],
)
def test_safe_integer(value: int) -> None:
    serialized = serialize_claim(
        "service",
        "worker",
        "count",
        value,
    )

    assert str(value).encode() in serialized


@pytest.mark.parametrize(
    ("value", "error"),
    [
        pytest.param(-MAX_INTEGER - 1, ValueError, id="integer-min"),
        pytest.param(MAX_INTEGER + 1, ValueError, id="integer-max"),
        pytest.param(float("nan"), ValueError, id="nan"),
        pytest.param(float("inf"), ValueError, id="positive-infinity"),
        pytest.param(float("-inf"), ValueError, id="negative-infinity"),
        pytest.param(b"value", TypeError, id="bytes"),
        pytest.param(("value",), TypeError, id="tuple"),
        pytest.param({"value"}, TypeError, id="set"),
    ],
)
def test_invalid_value(value: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        serialize_claim(
            "service",
            "worker",
            "value",
            value,
        )


@pytest.mark.parametrize(
    "value",
    [
        "\ud800",
        {"\udfff": None},
    ],
)
def test_lone_surrogate(value: object) -> None:
    with pytest.raises(ValueError):
        serialize_claim(
            "service",
            "worker",
            "profile",
            value,
        )


def test_lone_surrogate_field() -> None:
    with pytest.raises(ValueError):
        serialize_source(
            "web_publisher",
            "\ud800",
        )


@pytest.mark.parametrize(
    "serialize",
    [
        lambda: serialize_source(
            1,
            "docs.anthropic.com",
        ),
        lambda: serialize_attribute(
            "service",
            None,
            "status",
        ),
        lambda: serialize_claim(
            "service",
            "worker",
            [],
            None,
        ),
    ],
)
def test_invalid_field_type(
    serialize: Callable[[], bytes],
) -> None:
    with pytest.raises(TypeError):
        serialize()


def test_non_string_key() -> None:
    with pytest.raises(TypeError):
        serialize_claim(
            "service",
            "worker",
            "profile",
            {1: "value"},
        )


def test_nesting_depth() -> None:
    value: object = None

    for _ in range(32):
        value = [value]

    serialize_claim(
        "service",
        "worker",
        "profile",
        value,
    )

    with pytest.raises(ValueError):
        serialize_claim(
            "service",
            "worker",
            "profile",
            [value],
        )


def test_value_nodes() -> None:
    serialize_claim(
        "service",
        "worker",
        "profile",
        [None] * 4_095,
    )

    with pytest.raises(ValueError):
        serialize_claim(
            "service",
            "worker",
            "profile",
            [None] * 4_096,
        )


def test_payload_size() -> None:
    prefix = b'{"identifier":"'
    suffix = b'","kind":"web_publisher"}'
    identifier = "a" * (65_517 - len(prefix) - len(suffix))

    assert len(
        serialize_source(
            "web_publisher",
            identifier,
        )
    ) == 65_517

    with pytest.raises(ValueError):
        serialize_source(
            "web_publisher",
            identifier + "a",
        )


def test_serialization_does_not_normalize() -> None:
    serialized = serialize_attribute(
        " Service ",
        "Cafe\u0301 ",
        "Display Name",
    )

    assert serialized == (
        b'{"attribute":"Display Name","entity":"Cafe\xcc\x81 ",'
        b'"entity_namespace":" Service "}'
    )
    assert canonicalize_value("a") != canonicalize_value("а")
