from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from verity.base64url import decode_unpadded
from verity.config import (
    PROTOCOL_VERSION,
    VOPRF_MODE,
    DeploymentState,
)
from verity.engine_graph import (
    AssertionTriple,
    GraphError,
    InferenceGraph,
    SourcePair as EngineSourcePair,
    build_graph,
)
from verity.inference import (
    ALGORITHM_VERSION,
    CONVERGENCE_TOLERANCE,
    InferenceError,
    infer,
)
from verity.linkage import ENCODING_VERSION
from verity.models import (
    InferCredibilityRequest,
    InferCredibilityResponse,
)
from verity.oprf import CIPHERSUITE
from verity.tools.evaluate_voprf import error_result


TOKEN_LENGTH = 64
MAX_ASSERTIONS = 4096
MAX_SOURCES = 64
MAX_ATTRIBUTES = 2048
MAX_CLAIMS = 4096
MAX_SOURCE_PAIRS = 2016
MAX_CONFLICTING_CLAIM_ENTRIES = 16_384


class InferenceService:
    """Bounded, request-scoped credibility inference."""

    def __init__(self, state: DeploymentState) -> None:
        self._state = state
        self._timeout_seconds = state.inference_timeout_ms / 1_000
        self._executor = ThreadPoolExecutor(
            max_workers=state.inference_max_concurrency,
            thread_name_prefix="verity-inference",
        )
        self._capacity = state.inference_max_concurrency
        self._active = 0
        self._closed = False
        self._lock = threading.Lock()

    async def evaluate(
        self,
        request: InferCredibilityRequest,
    ) -> CallToolResult:
        mismatch = self._metadata_error(request)
        if mismatch is not None:
            return mismatch

        try:
            graph = _validate_graph(request)
        except GraphError:
            return _invalid_graph_result()
        except Exception:
            return _internal_error_result()

        try:
            future = self._submit(graph)
        except Exception:
            return _internal_error_result()
        if future is None:
            return error_result(
                "Inference capacity is exhausted.",
                "server_busy",
            )

        try:
            result = await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(future)),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return error_result(
                "Inference exceeded its deadline.",
                "request_timeout",
            )
        except InferenceError:
            return error_result(
                "Inference failed.",
                "inference_failed",
            )
        except Exception:
            return _internal_error_result()

        try:
            response = _build_response(self._state, graph, result)
            _validate_response(response, graph, self._state)
        except (InferenceError, ValidationError, ValueError):
            return error_result(
                "Inference failed.",
                "inference_failed",
            )
        except Exception:
            return _internal_error_result()
        return _success_result(response)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(
            wait=True,
            cancel_futures=True,
        )

    def _submit(self, graph: InferenceGraph):
        with self._lock:
            if self._closed or self._active >= self._capacity:
                return None
            self._active += 1

        try:
            future = self._executor.submit(infer, graph)
        except Exception:
            self._release()
            raise
        future.add_done_callback(lambda _future: self._release())
        return future

    def _release(self) -> None:
        with self._lock:
            self._active -= 1

    def _metadata_error(
        self,
        request: InferCredibilityRequest,
    ) -> CallToolResult | None:
        comparisons = (
            (
                request.protocol_version,
                PROTOCOL_VERSION,
                "The protocol version is unsupported.",
                "unsupported_protocol_version",
            ),
            (
                request.deployment_id,
                self._state.deployment_id,
                "The deployment does not match.",
                "deployment_mismatch",
            ),
            (
                request.voprf_key_version,
                self._state.voprf_key_version,
                "The VOPRF key version does not match.",
                "voprf_key_version_mismatch",
            ),
            (
                request.voprf_mode,
                VOPRF_MODE,
                "The VOPRF mode is unsupported.",
                "unsupported_voprf_mode",
            ),
            (
                request.voprf_ciphersuite,
                CIPHERSUITE,
                "The VOPRF ciphersuite is unsupported.",
                "unsupported_voprf_ciphersuite",
            ),
            (
                request.linkage_encoding_version,
                ENCODING_VERSION,
                "The linkage encoding version is unsupported.",
                "unsupported_linkage_encoding_version",
            ),
        )
        for actual, expected, message, code in comparisons:
            if actual != expected:
                return error_result(message, code)
        return None


def _validate_graph(
    request: InferCredibilityRequest,
) -> InferenceGraph:
    assertions = request.assertions
    if not 1 <= len(assertions) <= MAX_ASSERTIONS:
        raise GraphError("invalid assertion count")

    sources = {item.source_id for item in assertions}
    attributes = {item.attribute_id for item in assertions}
    claims = {item.claim_id for item in assertions}
    if not 1 <= len(sources) <= MAX_SOURCES:
        raise GraphError("invalid source count")
    if not 1 <= len(attributes) <= MAX_ATTRIBUTES:
        raise GraphError("invalid attribute count")
    if not 1 <= len(claims) <= MAX_CLAIMS:
        raise GraphError("invalid claim count")

    expected_pair_count = len(sources) * (len(sources) - 1) // 2
    if (
        len(request.source_pairs) != expected_pair_count
        or len(request.source_pairs) > MAX_SOURCE_PAIRS
    ):
        raise GraphError("invalid source-pair count")

    assertion_keys = []
    for assertion in assertions:
        _token(assertion.source_id)
        _token(assertion.attribute_id)
        _token(assertion.claim_id)
        key = (
            assertion.source_id,
            assertion.attribute_id,
            assertion.claim_id,
        )
        assertion_keys.append(key)

    if assertion_keys != sorted(assertion_keys):
        raise GraphError("assertions are not canonically ordered")
    if len(set(assertion_keys)) != len(assertion_keys):
        raise GraphError("duplicate assertion")

    claim_attributes = {}
    source_attributes = set()
    for assertion in assertions:
        attribute_id = claim_attributes.setdefault(
            assertion.claim_id,
            assertion.attribute_id,
        )
        if attribute_id != assertion.attribute_id:
            raise GraphError("claim belongs to multiple attributes")
        source_attribute = (
            assertion.source_id,
            assertion.attribute_id,
        )
        if source_attribute in source_attributes:
            raise GraphError("source has multiple claims for an attribute")
        source_attributes.add(source_attribute)

    _validate_conflict_entry_count(
        _conflict_entry_count(claim_attributes)
    )

    pair_keys = []
    engine_pairs = []
    for pair in request.source_pairs:
        _token(pair.source_a_id)
        _token(pair.source_b_id)
        if (
            pair.source_a_id not in sources
            or pair.source_b_id not in sources
        ):
            raise GraphError("source pair contains an unknown source")
        if pair.source_a_id == pair.source_b_id:
            raise GraphError("source pair is diagonal")
        if pair.source_a_id > pair.source_b_id:
            raise GraphError("source pair is reversed")

        key = (pair.source_a_id, pair.source_b_id)
        pair_keys.append(key)
        engine_pairs.append(EngineSourcePair(
            source_a_id=pair.source_a_id,
            source_b_id=pair.source_b_id,
            dependency=pair.dependency,
            weighted_signal_coverage=(
                pair.weighted_signal_coverage
            ),
        ))

    if pair_keys != sorted(pair_keys):
        raise GraphError("source pairs are not canonically ordered")
    if len(set(pair_keys)) != len(pair_keys):
        raise GraphError("duplicate source pair")

    ordered_sources = sorted(sources)
    expected_pairs = {
        (source_a_id, source_b_id)
        for index, source_a_id in enumerate(ordered_sources)
        for source_b_id in ordered_sources[index + 1:]
    }
    if set(pair_keys) != expected_pairs:
        raise GraphError("source-pair matrix is incomplete")

    engine_assertions = [
        AssertionTriple(
            source_id=item.source_id,
            attribute_id=item.attribute_id,
            claim_id=item.claim_id,
        )
        for item in assertions
    ]
    return build_graph(engine_assertions, engine_pairs)


def _conflict_entry_count(claim_attributes) -> int:
    claim_counts = {}
    for attribute_id in claim_attributes.values():
        claim_counts[attribute_id] = claim_counts.get(attribute_id, 0) + 1
    return sum(
        count * (count - 1)
        for count in claim_counts.values()
    )


def _validate_conflict_entry_count(count: int) -> None:
    if count > MAX_CONFLICTING_CLAIM_ENTRIES:
        raise GraphError("too many conflicting-claim entries")


def _token(value: str) -> None:
    try:
        decode_unpadded(value, expected_length=TOKEN_LENGTH)
    except ValueError:
        raise GraphError("invalid linkage token") from None


def _build_response(state, graph, result) -> InferCredibilityResponse:
    return InferCredibilityResponse(
        protocol_version=PROTOCOL_VERSION,
        deployment_id=state.deployment_id,
        voprf_key_version=state.voprf_key_version,
        voprf_mode=VOPRF_MODE,
        voprf_ciphersuite=CIPHERSUITE,
        linkage_encoding_version=ENCODING_VERSION,
        summary={
            "source_count": result.summary.source_count,
            "claim_count": result.summary.claim_count,
            "assertion_count": result.summary.assertion_count,
        },
        source_credibility=[
            {
                "source_id": item.source_id,
                "credibility": item.credibility,
            }
            for item in result.source_credibility
        ],
        claim_support=[
            {
                "attribute_id": item.attribute_id,
                "claim_id": item.claim_id,
                "support": item.support,
                "agreement_weight": item.agreement_weight,
                "is_attribute_max_support": (
                    item.is_attribute_max_support
                ),
                "supporting_source_count": (
                    item.supporting_source_count
                ),
                "estimated_independent_support_count": (
                    item.estimated_independent_support_count
                ),
                "dependency_confidence": item.dependency_confidence,
                "supporting_sources": [
                    {
                        "source_id": source.source_id,
                        "independence": source.independence,
                        "contribution": source.contribution,
                    }
                    for source in item.supporting_sources
                ],
                "conflicting_claims": [
                    {
                        "claim_id": conflict.claim_id,
                        "support": conflict.support,
                    }
                    for conflict in item.conflicting_claims
                ],
            }
            for item in result.claim_support
        ],
        metadata={
            "algorithm_version": result.metadata.algorithm_version,
            "iterations": result.metadata.iterations,
            "converged": result.metadata.converged,
            "convergence_tolerance": (
                result.metadata.convergence_tolerance
            ),
            "maximum_credibility_delta": (
                result.metadata.maximum_credibility_delta
            ),
        },
    )


def _validate_response(
    response: InferCredibilityResponse,
    graph: InferenceGraph,
    state: DeploymentState,
) -> None:
    if (
        response.protocol_version != PROTOCOL_VERSION
        or response.deployment_id != state.deployment_id
        or response.voprf_key_version != state.voprf_key_version
        or response.voprf_mode != VOPRF_MODE
        or response.voprf_ciphersuite != CIPHERSUITE
        or response.linkage_encoding_version != ENCODING_VERSION
        or response.metadata.algorithm_version != ALGORITHM_VERSION
        or not response.metadata.converged
        or response.metadata.convergence_tolerance
        != CONVERGENCE_TOLERANCE
    ):
        raise InferenceError("invalid inference metadata")
    if response.summary.model_dump() != {
        "source_count": len(graph.sources),
        "claim_count": len(graph.claims),
        "assertion_count": graph.assertion_count,
    }:
        raise InferenceError("invalid inference summary")

    source_ids = [item.source_id for item in response.source_credibility]
    for source_id in source_ids:
        _token(source_id)
    if set(source_ids) != set(graph.sources) or len(source_ids) != len(
        graph.sources
    ):
        raise InferenceError("invalid source results")
    if response.source_credibility != sorted(
        response.source_credibility,
        key=lambda item: (-item.credibility, item.source_id),
    ):
        raise InferenceError("invalid source ordering")

    claim_ids = [item.claim_id for item in response.claim_support]
    if set(claim_ids) != set(graph.claims) or len(claim_ids) != len(
        graph.claims
    ):
        raise InferenceError("invalid claim results")
    if response.claim_support != sorted(
        response.claim_support,
        key=lambda item: (
            item.attribute_id,
            -item.support,
            item.claim_id,
        ),
    ):
        raise InferenceError("invalid claim ordering")

    support_by_claim = {
        claim.claim_id: claim.support
        for claim in response.claim_support
    }
    for item in response.claim_support:
        _token(item.attribute_id)
        _token(item.claim_id)
        if item.attribute_id != graph.claim_to_attribute[item.claim_id]:
            raise InferenceError("invalid claim attribute")
        if (
            item.supporting_source_count != len(item.supporting_sources)
            or item.estimated_independent_support_count
            > item.supporting_source_count
        ):
            raise InferenceError("invalid supporting-source telemetry")
        supporters = {source.source_id for source in item.supporting_sources}
        for source_id in supporters:
            _token(source_id)
        if supporters != set(graph.claim_to_sources[item.claim_id]):
            raise InferenceError("invalid supporting sources")
        if item.supporting_sources != sorted(
            item.supporting_sources,
            key=lambda source: (
                -source.contribution,
                source.source_id,
            ),
        ):
            raise InferenceError("invalid supporting-source ordering")
        conflicts = {conflict.claim_id for conflict in item.conflicting_claims}
        for claim_id in conflicts:
            _token(claim_id)
        expected_conflicts = set(
            graph.attribute_to_claims[item.attribute_id]
        ) - {item.claim_id}
        if conflicts != expected_conflicts:
            raise InferenceError("invalid conflicts")
        if item.conflicting_claims != sorted(
            item.conflicting_claims,
            key=lambda conflict: (
                -conflict.support,
                conflict.claim_id,
            ),
        ):
            raise InferenceError("invalid conflict ordering")
        if any(
            conflict.support != support_by_claim[conflict.claim_id]
            for conflict in item.conflicting_claims
        ):
            raise InferenceError("invalid conflict support")
        contribution_by_source = {
            source.source_id: source.contribution
            for source in item.supporting_sources
        }
        contribution_total = 0.0
        for source_id in graph.claim_to_sources[item.claim_id]:
            contribution_total += contribution_by_source[source_id]
        if contribution_total != item.support:
            raise InferenceError("invalid contribution total")
        expected_maximum = max(
            support_by_claim[claim_id]
            for claim_id in graph.attribute_to_claims[item.attribute_id]
        )
        if item.is_attribute_max_support != (
            item.support == expected_maximum
        ):
            raise InferenceError("invalid claim maximum")
        if (item.dependency_confidence is None) != (
            item.supporting_source_count == 1
        ):
            raise InferenceError("invalid dependency confidence")


def _invalid_graph_result() -> CallToolResult:
    return error_result(
        "The inference graph is invalid.",
        "invalid_graph",
    )


def _internal_error_result() -> CallToolResult:
    return error_result(
        "An internal server error occurred.",
        "internal_error",
    )


def _success_result(
    response: InferCredibilityResponse,
) -> CallToolResult:
    content = response.model_dump(mode="json")
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    content,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        ],
        structuredContent=content,
        isError=False,
    )
