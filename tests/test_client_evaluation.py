
from daemon_support import VOPRFServer
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone

import pytest
from omneum.mcp.types import CallToolResult
from omneum import ExactEquivalence

import omneum.client as client_module
from omneum.base64url import decode_unpadded, encode_unpadded
from omneum.client import (
    ClaimSupportResult,
    ConflictingClaimResult,
    ConvergenceMetadata,
    ContextEvaluation,
    EvaluationTransportError,
    ContextEvaluationMappingError,
    ContextEvaluationRejectedError,
    ContextEvaluationResponseError,
    ContextEvaluationTransportError,
    LinkageToken,
    SourceEvaluation,
    SupportingSourceResult,
    OmneumClient,
    OmneumClientConfig,
)
from omneum.dependency import (
    DependencyCluster,
    DependencyEstimatorConfig,
    DependencySignalScores,
    PairwiseDependencyResult,
)
from omneum.engine_graph import AssertionTriple, SourcePair, build_graph
from omneum.inference import infer
from omneum.information import Claim, Observation, Retrieval, Source, SourceReference
from omneum.linkage import LinkagePurpose
from omneum.metrics import JsonlMetricsRecorder
from omneum.models import EvaluateVOPRFRequest, EvaluateAssertionRequest

from test_client import DEPLOYMENT_ID, make_config, make_server, success_result


def lists(value):
    if type(value) is tuple:
        return [lists(item) for item in value]
    if type(value) is list:
        return [lists(item) for item in value]
    if type(value) is dict:
        return {key: lists(item) for key, item in value.items()}
    return value


class Evaluator:
    def __init__(self, server: VOPRFServer, key_version=1):
        self.server = server
        self.key_version = key_version
        self.evaluations = []
        self.requests = []
        self.active = 0
        self.maximum_active = 0

    async def evaluate_voprf(self, request: EvaluateVOPRFRequest):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0)
        self.evaluations.append(request)
        evaluation = self.server.evaluate(
            decode_unpadded(request.blinded_element, expected_length=32)
        )
        self.active -= 1
        return success_result(
            voprf_key_version=self.key_version,
            evaluated_element=encode_unpadded(
                evaluation.evaluated_element, expected_length=32
            ),
            proof=encode_unpadded(evaluation.proof, expected_length=64),
        )

    async def evaluate_context(self, request: EvaluateAssertionRequest):
        self.requests.append(request)
        graph = build_graph(
            tuple(
                AssertionTriple(item.source_id, item.attribute_id, item.claim_id)
                for item in request.assertions
            ),
            tuple(
                SourcePair(
                    item.source_a_id,
                    item.source_b_id,
                    item.dependency,
                    item.weighted_signal_coverage,
                    exact_equivalence=item.exact_equivalence,
                )
                for item in request.source_pairs
            ),
        )
        result = lists(asdict(infer(graph)))
        result.update({
            "protocol_version": "v1",
            "deployment_id": DEPLOYMENT_ID,
            "voprf_key_version": self.key_version,
            "voprf_mode": "voprf",
            "voprf_ciphersuite": "ristretto255-SHA512",
            "linkage_encoding_version": 1,
        })
        return CallToolResult(
            content=[], structuredContent=result, isError=False
        )


def estimator(threshold=None):
    return DependencyEstimatorConfig(
        upstream_weight=0.25,
        citation_weight=0.20,
        assertion_lineage_weight=0.20,
        ownership_weight=0.10,
        temporal_weight=0.10,
        graph_weight=0.15,
        temporal_window_seconds=7200.0,
        dependency_cluster_threshold=threshold,
    )


def observations():
    claim = Claim("service", "Product", "Return Window", "30 days")
    return (
        Observation(
            observation_id="a1",
            source=Source("web_publisher", "https://a.example", "owner"),
            claim=claim,
            observed_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
            source_modified_at=datetime(2026, 1, 1, 11, tzinfo=timezone.utc),
            upstream_sources=(),
            cited_sources=(),
            parent_observation_ids=(),
            retrievals=(),
        ),
        Observation(
            observation_id="b1",
            source=Source("web_publisher", "https://b.example", "owner"),
            claim=claim,
            observed_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
            source_modified_at=datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
            upstream_sources=(),
            cited_sources=(
                SourceReference("web_publisher", "https://a.example"),
            ),
            parent_observation_ids=(),
            retrievals=(),
        ),
    )


def make_observation(observation_id, source, claim, **changes):
    values = {
        "observation_id": observation_id,
        "source": source,
        "claim": claim,
        "observed_at": datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        "source_modified_at": None,
        "upstream_sources": (),
        "cited_sources": (),
        "parent_observation_ids": (),
        "retrievals": (),
    }
    values.update(changes)
    return Observation(**values)


@pytest.mark.parametrize("signal,expected", [
    ("upstream", False), ("parent", False), ("citation", False),
    ("shared_upstream", False), ("none", False),
    ("ownership", False), ("temporal", False),
    ("exact", True),
])
def test_exact_equivalence_transport(tmp_path, signal, expected):
    from test_evaluate_context import make_state
    from omneum.tools.evaluate_context import AssertionEvaluationService

    async def run():
        server = make_server(tmp_path)
        service = AssertionEvaluationService(make_state())

        class WireEvaluator(Evaluator):
            async def evaluate_context(self, request):
                # Exercise the strict wire model and production server, then
                # let the SDK verify that response using its local graph.
                request = EvaluateAssertionRequest.model_validate_json(
                    request.model_dump_json()
                )
                self.requests.append(request)
                return await service.evaluate(request)

        evaluator = WireEvaluator(server)
        client = OmneumClient(make_config(server), evaluator)
        rows = []
        shared = Claim("service", "Product", "Return Window", "30 days")
        for i in range(3):
            changes = {}
            if i and signal in {"upstream", "citation"}:
                field = "upstream_sources" if signal == "upstream" else "cited_sources"
                changes[field] = (SourceReference("web_publisher", f"https://s{i-1}.example"),)
            elif i and signal == "parent":
                changes["parent_observation_ids"] = (f"o{i-1}",)
            elif signal == "shared_upstream":
                changes["upstream_sources"] = (SourceReference("web_publisher", "https://up.example"),)
            elif signal == "temporal":
                changes["source_modified_at"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
            owner = ("shared" if i < 2 else "other") if signal == "ownership" else None
            rows.append(make_observation(
                f"o{i}", Source("web_publisher", f"https://s{i}.example", owner), shared,
                **changes,
            ))
        try:
            equivalences = tuple(
                ExactEquivalence(
                    SourceReference("web_publisher", f"https://S{i}.example/"),
                    SourceReference("web_publisher", f"https://s{i-1}.example"),
                )
                for i in (1, 2)
            ) if expected else ()
            result = await client._evaluate_context(
                rows, estimator=estimator(), exact_equivalences=equivalences,
            )
            pairs = evaluator.requests[0].source_pairs
            assert sum(pair.exact_equivalence for pair in pairs) == (2 if expected else 0)
            if signal in {"upstream", "parent", "citation", "shared_upstream"}:
                assert any(pair.dependency == 1.0 for pair in pairs)
            if signal in {"ownership", "temporal"}:
                assert any(pair.dependency > 0.0 for pair in pairs)
            if expected:
                assert [item.independence for item in result.claim_support[0].supporting_sources] == pytest.approx([1 / 3] * 3)
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["type", "unknown", "self"])
def test_invalid_exact_equivalence(tmp_path, kind):
    async def run():
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(make_config(server), evaluator)
        a = SourceReference("web_publisher", "https://a.example")
        b = SourceReference("web_publisher", "https://missing.example")
        equivalence = {"type": object(), "unknown": ExactEquivalence(a, b),
                       "self": ExactEquivalence(a, a)}[kind]
        with pytest.raises(TypeError if kind == "type" else ValueError):
            await client._evaluate_context(
                observations(), estimator=estimator(), exact_equivalences=(equivalence,),
            )
        assert evaluator.evaluations == evaluator.requests == []

    asyncio.run(run())


def test_exact_equivalence_endpoint_type():
    with pytest.raises(TypeError, match="SourceReference"):
        ExactEquivalence("a", "b")


def test_inference(tmp_path):
    async def run():
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(make_config(server), evaluator)
        result = await client._evaluate_context(
            observations(), estimator=estimator(0.5)
        )

        assert len(evaluator.evaluations) == 4
        assert evaluator.maximum_active == 1
        assert len(evaluator.requests) == 1
        request = evaluator.requests[0]
        assert set(request.model_dump()) == {
            "protocol_version",
            "deployment_id",
            "voprf_key_version",
            "voprf_mode",
            "voprf_ciphersuite",
            "linkage_encoding_version",
            "assertions",
            "source_pairs",
        }
        wire = repr(request.model_dump())
        for secret in (
            "a.example", "b.example", "owner", "provenance",
            "Product", "Return Window", "30 days",
        ):
            assert secret not in wire
        assert len(request.assertions) == 2
        assert len(request.source_pairs) == 1
        assert result.source_reliability[0].source.identifier in {
            "a.example", "b.example"
        }
        assert result.claim_support[0].claim.value == "30 days"
        assert result.claim_support[0].dependency_clusters is not None
        assert result.dependency_cluster_threshold == 0.5
        assert "dependency_cluster_threshold" not in repr(result)

    asyncio.run(run())


def test_repeated(tmp_path):
    async def run():
        server = make_server(tmp_path)
        client = OmneumClient(make_config(server), Evaluator(server))
        first = await client._evaluate_context(observations(), estimator=estimator())
        second = await client._evaluate_context(observations(), estimator=estimator())
        assert first == second
        assert first.claim_support[0].dependency_clusters is None

    asyncio.run(run())


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (True, 1),
        ([["a", 1]], {"a": 1}),
        ([{"nested": [True]}], {"nested": [True]}),
    ],
)
def test_claim_identity(tmp_path, first, second):
    async def run():
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(make_config(server), evaluator)
        values = (
            make_observation(
                "a1", Source("web_publisher", "a.example"),
                Claim("service", "entity", "attribute", first),
            ),
            make_observation(
                "b1", Source("web_publisher", "b.example"),
                Claim("service", "entity", "attribute", second),
            ),
        )
        await client._evaluate_context(values, estimator=estimator())
        assert len(evaluator.evaluations) == 5
        assert len({item.claim_id for item in evaluator.requests[0].assertions}) == 2

    asyncio.run(run())


def test_claim_equivalence(tmp_path):
    async def run():
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(make_config(server), evaluator)
        values = (
            make_observation(
                "a1", Source("web_publisher", "a.example"),
                Claim("service", "entity", "attribute", {"a": 1, "b": 2}),
            ),
            make_observation(
                "b1", Source("web_publisher", "b.example"),
                Claim("service", "entity", "attribute", {"b": 2, "a": 1}),
            ),
        )
        await client._evaluate_context(values, estimator=estimator())
        assert len(evaluator.evaluations) == 4
        assert len({item.claim_id for item in evaluator.requests[0].assertions}) == 1

    asyncio.run(run())


def test_result_types():
    source_value = Source("web_publisher", "example.com")
    claim_value = Claim("service", "entity", "attribute", "value")

    with pytest.raises(TypeError):
        SourceEvaluation(source_value, True)
    with pytest.raises(TypeError):
        SupportingSourceResult(source_value, True, 0.0)
    with pytest.raises(ValueError):
        ConflictingClaimResult(claim_value, float("nan"))
    with pytest.raises(TypeError):
        ClaimSupportResult(
            claim_value, 1.0, 1.0, True, 1, 1.0, None,
            [], (), None,
        )
    supporting = SupportingSourceResult(source_value, 1.0, 1.0)
    with pytest.raises(ValueError):
        ClaimSupportResult(
            claim_value, 1.0, 1.0, True, 1, 1.0, 0.5,
            (supporting,), (), None,
        )
    with pytest.raises(TypeError):
        ConvergenceMetadata("omneum-v2", True, True, 1e-8, 0.0)
    convergence = ConvergenceMetadata("omneum-v2", 1, True, 1e-8, 0.0)
    with pytest.raises(TypeError):
        ContextEvaluation([], (), (), convergence, None)


def result_values():
    sources = tuple(
        Source("web_publisher", f"{name}.example")
        for name in ("a", "b", "c")
    )
    source_results = tuple(
        SourceEvaluation(source, 1.0 / 3.0)
        for source in sources
    )
    claim_value = Claim("service", "entity", "attribute", "value")
    supporting = SupportingSourceResult(sources[0], 1.0, 1.0)
    claim_result = ClaimSupportResult(
        claim_value, 1.0, 1.0, True, 1, 1.0, None,
        (supporting,), (), None,
    )
    signals = DependencySignalScores(
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        True, True, True, True, True, True,
    )
    references = tuple(
        SourceReference(source.kind, source.identifier)
        for source in sources
    )
    pairs = tuple(
        PairwiseDependencyResult(
            references[index], references[other], signals, 0.0, 1.0
        )
        for index in range(len(references))
        for other in range(index + 1, len(references))
    )
    convergence = ConvergenceMetadata("omneum-v2", 1, True, 1e-8, 0.0)
    return source_results, (claim_result,), pairs, convergence


def test_evaluation_explanation():
    sources, claims, pairs, convergence = result_values()

    evaluation = ContextEvaluation(
        sources,
        claims,
        pairs,
        convergence,
        None,
        evaluation_latency_ms=19.9,
    )

    rendered = evaluation.explanation

    assert rendered.startswith(
        "Omneum Evaluation\nEvaluation latency: 19.9 ms"
    )
    assert "\n\nAttribute\n" in rendered
    assert "\n  value\n" in rendered
    assert "  Support: 1.00" in rendered
    assert "  Supporting sources: 1" in rendered
    assert "  Estimated independent support: 1.00" in rendered
    assert "  Explanation:\n    One source supports this claim." in rendered
    assert not rendered.endswith("\n")


@pytest.mark.parametrize(
    "change",
    [
        lambda pairs: (pairs[0], pairs[1], pairs[0]),
        lambda pairs: (pairs[0], pairs[2]),
        lambda pairs: (pairs[1], pairs[0], pairs[2]),
        lambda pairs: (
            pairs[0],
            pairs[1],
            PairwiseDependencyResult(
                SourceReference("web_publisher", "b.example"),
                SourceReference("web_publisher", "d.example"),
                pairs[2].signals,
                0.0,
                1.0,
            ),
        ),
    ],
)
def test_result_pairs(change):
    sources, claims, pairs, convergence = result_values()

    with pytest.raises(ValueError):
        ContextEvaluation(
            sources, claims, change(pairs), convergence, None
        )


def cluster_values(clusters):
    sources = tuple(
        Source("web_publisher", f"{name}.example")
        for name in ("a", "b", "c")
    )
    supporting = tuple(
        SupportingSourceResult(source, 1.0, 1.0 / 3.0)
        for source in sources
    )
    return ClaimSupportResult(
        Claim("service", "entity", "attribute", "value"),
        1.0,
        1.0,
        True,
        3,
        3.0,
        1.0,
        supporting,
        (),
        clusters,
    )


def support_values(sources, clusters):
    supporting = tuple(
        SupportingSourceResult(source, 1.0, 1.0 / len(sources))
        for source in sources
    )
    return ClaimSupportResult(
        Claim("service", "entity", "attribute", "value"),
        1.0,
        1.0,
        True,
        len(sources),
        float(len(sources)),
        1.0,
        supporting,
        (),
        clusters,
    )


@pytest.mark.parametrize(
    "sources",
    [
        (
            Source("web_publisher", "HTTPS://EXAMPLE.COM/"),
            Source("web_publisher", "example.com"),
        ),
        (
            Source("web_document", "HTTPS://EXAMPLE.COM:443/path"),
            Source("web_document", "https://example.com/path"),
        ),
    ],
)
def test_support_equivalence(sources):
    reference = SourceReference(sources[0].kind, sources[0].identifier)

    with pytest.raises(ValueError):
        support_values(
            sources,
            (DependencyCluster(0.5, (reference,)),),
        )


def test_support_partition():
    sources = (
        Source("web_publisher", "a.example"),
        Source("web_publisher", "b.example"),
    )
    clusters = (
        DependencyCluster(
            0.5,
            (SourceReference("web_publisher", "a.example"),),
        ),
        DependencyCluster(
            0.5,
            (SourceReference("web_publisher", "b.example"),),
        ),
    )

    assert support_values(sources, clusters).dependency_clusters == clusters


def test_cluster_partition():
    a, b, c, d = tuple(
        SourceReference("web_publisher", f"{name}.example")
        for name in ("a", "b", "c", "d")
    )

    assert cluster_values((
        DependencyCluster(0.5, (a, b)),
        DependencyCluster(0.5, (c,)),
    )).dependency_clusters is not None
    for clusters in (
        (DependencyCluster(0.5, (a, b)), DependencyCluster(0.5, (b, c))),
        (DependencyCluster(0.5, (a, b)),),
        (DependencyCluster(0.5, (a, b)), DependencyCluster(0.5, (d,))),
        (DependencyCluster(0.5, (b,)), DependencyCluster(0.5, (a, c))),
    ):
        with pytest.raises(ValueError):
            cluster_values(clusters)


def test_cluster_members():
    a = SourceReference("web_publisher", "a.example")
    b = SourceReference("web_publisher", "b.example")

    with pytest.raises(ValueError):
        DependencyCluster(0.5, (a, a))
    with pytest.raises(ValueError):
        DependencyCluster(0.5, (b, a))


def test_token_validation():
    values = (
        DEPLOYMENT_ID,
        1,
        "voprf",
        "ristretto255-SHA512",
        1,
        LinkagePurpose.SOURCE,
        b"t" * 64,
    )
    token = LinkageToken(*values)
    assert "urn:uuid" not in repr(token)
    assert "tttt" not in repr(token)
    with pytest.raises(TypeError):
        LinkageToken(*values[:5], 1, values[6])
    with pytest.raises(ValueError):
        LinkageToken(values[0], True, *values[2:])
    assert "0.25" not in repr(estimator())


def test_source_equivalence(tmp_path):
    async def execute(values):
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(make_config(server), evaluator)
        result = await client._evaluate_context(values, estimator=estimator())
        return result, evaluator

    values = (
        make_observation(
            "a1", Source("web_publisher", "HTTPS://EXAMPLE.COM/", "owner"),
            Claim("service", "entity", "first", 1),
        ),
        make_observation(
            "a2", Source("web_publisher", "example.com", "owner"),
            Claim("service", "entity", "second", 2),
        ),
    )
    first, first_evaluator = asyncio.run(execute(values))
    second, second_evaluator = asyncio.run(execute(tuple(reversed(values))))

    assert first == second
    assert first.source_reliability[0].source == Source(
        "web_publisher", "example.com", "owner"
    )
    assert len(first_evaluator.evaluations) == 5
    assert len(second_evaluator.evaluations) == 5


def test_mutation_during_linkage(tmp_path, monkeypatch):
    class Paused(Evaluator):
        def __init__(self, server):
            super().__init__(server)
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def evaluate_voprf(self, request):
            self.started.set()
            await self.release.wait()
            return await super().evaluate_voprf(request)

    async def run():
        original = {"nested": [1]}
        retrieval = Retrieval(
            retrieval_id="retrieval-a",
            kind="http",
            resource_id="resource-a",
            retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            fields={"nested": [1]},
        )
        item = make_observation(
            "a1",
            Source("web_publisher", "example.com"),
            Claim("service", "entity", "attribute", original),
            retrievals=(retrieval,),
        )
        snapshots = []
        snapshot_observations = client_module._snapshot_observations

        def capture(values):
            result = snapshot_observations(values)
            snapshots.extend(result)
            return result

        monkeypatch.setattr(client_module, "_snapshot_observations", capture)
        server = make_server(tmp_path)
        evaluator = Paused(server)
        client = OmneumClient(make_config(server), evaluator)
        task = asyncio.create_task(
            client._evaluate_context((item,), estimator=estimator())
        )
        await evaluator.started.wait()
        original["nested"].append(2)
        retrieval.fields["nested"].append(2)
        evaluator.release.set()
        result = await task
        assert result.claim_support[0].claim.value == {"nested": [1]}
        assert snapshots[0].retrievals[0].fields == {"nested": [1]}
        assert "nested" not in repr(result)

    asyncio.run(run())


def test_cluster_key_order(tmp_path):
    async def execute(name, private_key, key_version):
        key = tmp_path / name
        key.write_bytes(private_key)
        server = VOPRFServer(key)
        evaluator = Evaluator(server, key_version)
        client = OmneumClient(
            OmneumClientConfig(
                DEPLOYMENT_ID,
                key_version,
                "voprf",
                "ristretto255-SHA512",
                1,
                server.public_key,
            ),
            evaluator,
        )
        result = await client._evaluate_context(
                observations(), estimator=estimator(0.19)
        )
        return result.claim_support[0].dependency_clusters

    first = asyncio.run(execute("first.key", b"\x01" + b"\x00" * 31, 1))
    second = asyncio.run(execute("second.key", b"\x02" + b"\x00" * 31, 2))

    assert first == second
    assert tuple(source.identifier for source in first[0].sources) == (
        "a.example", "b.example"
    )


def test_unavailable(tmp_path):
    async def run():
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(
            make_config(server), evaluator, context_evaluation_available=False
        )
        with pytest.raises(
            ContextEvaluationResponseError,
            match="The evaluate_context tool is unavailable",
        ):
            await client._evaluate_context((), estimator=estimator())
        assert evaluator.evaluations == []
        assert evaluator.requests == []

    asyncio.run(run())


def test_transport(tmp_path):
    class Broken(Evaluator):
        async def evaluate_context(self, request):
            raise ContextEvaluationTransportError(uncertain=True)

    async def run():
        server = make_server(tmp_path)
        client = OmneumClient(make_config(server), Broken(server))
        with pytest.raises(ContextEvaluationTransportError) as error:
            await client._evaluate_context(observations(), estimator=estimator())
        assert error.value.uncertain

    asyncio.run(run())


def test_injected_error(tmp_path):
    class BrokenInference(Evaluator):
        async def evaluate_context(self, request):
            raise OSError("secret transport detail")

    class BrokenEvaluation(Evaluator):
        async def evaluate_voprf(self, request):
            raise OSError("secret transport detail")

    async def run():
        server = make_server(tmp_path)
        inference = OmneumClient(make_config(server), BrokenInference(server))
        with pytest.raises(ContextEvaluationTransportError) as caught:
            await inference._evaluate_context(observations(), estimator=estimator())
        assert caught.value.uncertain
        assert "secret" not in str(caught.value)

        evaluation = OmneumClient(make_config(server), BrokenEvaluation(server))
        with pytest.raises(EvaluationTransportError) as caught:
            await evaluation.link_source("web_publisher", "example.com")
        assert caught.value.uncertain
        assert "secret" not in str(caught.value)

    asyncio.run(run())


def test_cancel(tmp_path):
    class Cancelled(Evaluator):
        async def evaluate_context(self, request):
            raise asyncio.CancelledError

    async def run():
        server = make_server(tmp_path)
        client = OmneumClient(make_config(server), Cancelled(server))
        with pytest.raises(asyncio.CancelledError):
            await client._evaluate_context(observations(), estimator=estimator())

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        "pin",
        "algorithm",
        "reordered",
        "duplicate",
        "missing",
        "agreement",
        "cross_purpose",
        "unknown",
    ],
)
def test_malformed(tmp_path, change):
    class Malformed(Evaluator):
        async def evaluate_context(self, request):
            result = await super().evaluate_context(request)
            content = result.structuredContent
            if change == "pin":
                content["voprf_key_version"] = 2
            elif change == "algorithm":
                content["metadata"]["algorithm_version"] = "other"
            elif change == "reordered":
                content["source_reliability"].reverse()
            elif change == "duplicate":
                content["source_reliability"][1] = content["source_reliability"][0]
            elif change == "missing":
                content["claim_support"] = []
            elif change == "agreement":
                content["claim_support"][0]["agreement_weight"] = 0.5
            elif change == "cross_purpose":
                content["source_reliability"][0]["source_id"] = (
                    content["claim_support"][0]["claim_id"]
                )
            else:
                content["unknown"] = True
            return result

    async def run():
        server = make_server(tmp_path)
        client = OmneumClient(make_config(server), Malformed(server))
        error = (
            ContextEvaluationMappingError
            if change == "cross_purpose"
            else ContextEvaluationResponseError
        )
        with pytest.raises(error):
            await client._evaluate_context(observations(), estimator=estimator())

    asyncio.run(run())


@pytest.mark.parametrize("code", [
    "request_too_large", "invalid_request", "authentication_required",
    "permission_denied", "unsupported_protocol_version",
    "deployment_mismatch", "voprf_key_version_mismatch",
    "unsupported_voprf_mode", "unsupported_voprf_ciphersuite",
    "unsupported_linkage_encoding_version", "invalid_blinded_element",
    "invalid_graph", "rate_limited", "server_busy", "request_timeout",
    "evaluation_failed", "assertion_evaluation_failed", "internal_error",
])
def test_rejected(tmp_path, code):
    class Rejected(Evaluator):
        async def evaluate_context(self, request):
            return CallToolResult(
                content=[],
                structuredContent={"message": "secret", "omneum_code": code},
                isError=True,
            )

    async def run():
        server = make_server(tmp_path)
        client = OmneumClient(make_config(server), Rejected(server))
        with pytest.raises(ContextEvaluationRejectedError) as error:
            await client._evaluate_context(observations(), estimator=estimator())
        assert error.value.omneum_code == code
        assert "secret" not in str(error.value)

    asyncio.run(run())


def test_records_evaluation_metrics(tmp_path):
    async def run():
        server = make_server(tmp_path)
        metrics_path = tmp_path / "evaluations.jsonl"

        client = OmneumClient(
            make_config(server),
            Evaluator(server),
            metrics_recorder=JsonlMetricsRecorder(metrics_path),
        )

        result = await client._evaluate_context(
            observations(),
            estimator=estimator(),
        )

        lines = metrics_path.read_text().splitlines()
        assert len(lines) == 1

        metrics = json.loads(lines[0])

        assert metrics["observation_count"] == 2
        assert metrics["source_count"] == len(
            result.source_reliability
        )
        assert metrics["claim_count"] == len(
            result.claim_support
        )
        assert metrics["pair_count"] == len(
            result.pairwise_dependencies
        )
        assert metrics["convergence_iterations"] == (
            result.convergence.iterations
        )
        assert metrics["convergence_delta"] == (
            result.convergence.convergence_delta
        )
        assert metrics["evaluation_latency_ms"] >= 0.0
        assert metrics["recorded_at"]

    asyncio.run(run())


def test_appends_evaluation_metrics(tmp_path):
    async def run():
        server = make_server(tmp_path)
        metrics_path = tmp_path / "evaluations.jsonl"

        client = OmneumClient(
            make_config(server),
            Evaluator(server),
            metrics_recorder=JsonlMetricsRecorder(metrics_path),
        )

        await client._evaluate_context(
            observations(),
            estimator=estimator(),
        )
        await client._evaluate_context(
            observations(),
            estimator=estimator(),
        )

        lines = metrics_path.read_text().splitlines()

        assert len(lines) == 2

        for line in lines:
            json.loads(line)

    asyncio.run(run())


def test_failed_evaluation_does_not_record_metrics(tmp_path):
    class Broken(Evaluator):
        async def evaluate_context(self, request):
            raise ContextEvaluationTransportError(uncertain=True)

    async def run():
        server = make_server(tmp_path)
        metrics_path = tmp_path / "evaluations.jsonl"

        client = OmneumClient(
            make_config(server),
            Broken(server),
            metrics_recorder=JsonlMetricsRecorder(metrics_path),
        )

        with pytest.raises(ContextEvaluationTransportError):
            await client._evaluate_context(
                observations(),
                estimator=estimator(),
            )

        assert not metrics_path.exists()

    asyncio.run(run())
