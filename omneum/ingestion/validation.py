"""Server uses the same bounded allowlisted wire contract as the sender."""

from omneum.contribution.validation import (
    COLLECTIONS, IDENTIFIER, MAX_BODY_BYTES, MAX_COLLECTION,
    MAX_NESTED_COLLECTION, decode, identifier, unique,
)
