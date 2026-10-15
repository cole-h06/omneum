"""Run explicitly; these dev-tool tests are outside the package test path."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import os
from unittest.mock import patch

import pytest

from tools.provenance_explorer import explorer as e
from omneum.canonicalization import canonicalize_source


def test_fixture_lineage():
    rows = e.fixture_observations()
    assert len(rows) == 72
    assert len({row.source for row in rows}) == 36
    assert len({row.claim for row in rows}) == 12
    assert Counter(t for _, _, t, _ in e.RELATIONS) == {"upstream": 27, "citation": 13}
    assert all(row.metadata[e.NAMESPACE]["synthetic"] for row in rows)
    assert len({row.observation_id for row in rows}) == len(rows)
    for row in rows:
        canonicalize_source(row.source.kind, row.source.identifier)
    relationships = {(d, u, t) for d, u, t, _ in e.RELATIONS}
    assert {("gateway", "registry", "upstream"), ("registry", "report", "upstream"),
            ("report", "bulletin", "citation")} <= relationships
    assert ("gateway", "registry", "citation") in relationships
    assert ("registry", "gateway", "upstream") not in relationships
    assert {d for d,u,t,_ in e.RELATIONS if u == "shared" and t == "upstream"} == {"regional", "cache", "audit"}
    endpoints = {key for d,u,_,_ in e.RELATIONS for key in (d,u)}
    assert {key for key, *_ in e.SOURCE_SPECS} - endpoints == {"ind-web", "ind-db", "ind-json", "ind-standard"}
    assert all(reason and d != u for d,u,_,reason in e.RELATIONS)
    assert e.fixture_observations() == rows


@pytest.mark.parametrize("dsn", ["dbname=omneum_prod", "host=example.com dbname=omneum_dev",
    "host=/tmp dbname=omneum_dev", "service=anything", "hostaddr=192.0.2.1", "options=-cfoo=bar"])
def test_connection_guard_rejects_before_any_database_access(dsn):
    with patch("psycopg.connect") as connect:
        with pytest.raises(ValueError):
            e.connect(dsn)
        connect.assert_not_called()


def test_connection_isolation(monkeypatch):
    monkeypatch.delenv("PGSERVICE", raising=False)
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    monkeypatch.setenv("PGDATABASE", "omneum_prod")
    monkeypatch.setenv("PGPASSWORD", "unrelated-secret-not-used")
    with patch("psycopg.connect") as connect:
        connect.return_value.execute.return_value.fetchone.return_value = ("omneum_dev", "127.0.0.1")
        e.connect(readonly=True)
        kwargs=connect.call_args.kwargs
        assert kwargs["dbname"] == "omneum_dev"
        assert kwargs["hostaddr"] == "127.0.0.1"
        assert kwargs["password"] == "unused-local-development-password"
        assert kwargs["options"] == "-c default_transaction_read_only=on"


@pytest.mark.skipif(os.environ.get("OMNEUM_PROVENANCE_INTEGRATION") != "1", reason="explicit dev-only integration opt-in")
def test_fixture_concurrency():
    with e.connect() as db:
        before = e.read_graph(db)
        assert e.populate(db)["inserted_observations"] == 0
        assert e.read_graph(db) == before
        # A changed fixture must fail rather than silently overwrite immutable records.
        altered=list(e.fixture_observations())
        altered[0].metadata[e.NAMESPACE]["source"]["name"] = "changed"
        with patch.object(e, "fixture_observations", return_value=tuple(altered)):
            with pytest.raises(ValueError, match="drift"):
                e.populate(db)
        assert e.read_graph(db) == before
    def repeat(_):
        with e.connect() as db:
            return e.populate(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(result["inserted_observations"] == 0 for result in pool.map(repeat, range(2)))
    with e.connect(readonly=True) as db:
        after = e.read_graph(db)
        e.validate_graph(after)
        assert after == before
        assert db.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        # Every inspector relationship exactly equals the stored JSON array item.
        for edge in after["edges"]:
            data = edge["data"]
            if "stored_relationship" in data:
                pointer = data["derived"]["metadata_pointer"].split("/")
                metadata = db.execute("SELECT metadata FROM public.observations WHERE id=%s",
                                      (data["derived"]["observation_id"],)).fetchone()[0]
                assert metadata[pointer[1]][pointer[2]][int(pointer[3])] == data["stored_relationship"]
