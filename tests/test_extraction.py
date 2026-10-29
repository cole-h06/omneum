import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from omneum import Source, extract_observations, reference, retrieval
from omneum.client import _evaluate_context as evaluate_context
from omneum.dependency import _UPSTREAM_ESTIMATOR


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
ASSERTION = {
    "entity_namespace": "company", "entity": "acme",
    "attribute": "fy2025_revenue_usd", "value": 4200000000,
}


def chunk(identifier="a", **fields):
    return {
        "id": identifier,
        "source": Source("web_document", f"https://{identifier}.example"),
        "text": "Acme reported revenue of $4.2 billion in 2025.",
        "observed_at": NOW,
        **fields,
    }


class Provider:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        return next(self.responses)


def test_extract_and_evaluate():
    upstream = (reference(kind="web_document", identifier="https://filing.example"),)
    retrieved = (retrieval(
        retrieval_id="search-1", kind="search", resource_id="acme",
        retrieved_at=NOW,
    ),)
    chunks = [
        chunk(upstream_sources=upstream, retrievals=retrieved,
              metadata={"request_id": "request-1"}, source_modified_at=NOW),
        chunk("b", upstream_sources=upstream),
        chunk("c", upstream_sources=()),
        chunk("empty", text="Navigation"),
    ]
    provider = Provider(*[
        {"text": json.dumps([ASSERTION])} for _ in range(3)
    ], {"text": "[]"})
    observations = asyncio.run(extract_observations(chunks, provider=provider))

    assert isinstance(observations, tuple)
    assert [item.observation_id for item in observations] == ["a:0", "b:0", "c:0"]
    assert observations[0].source is chunks[0]["source"]
    assert observations[0].observed_at == NOW
    assert observations[0].source_modified_at == NOW
    assert observations[0].upstream_sources == upstream
    assert observations[0].retrievals == retrieved
    assert observations[0].metadata == {"request_id": "request-1", "chunk_id": "a"}
    assert observations[0].cited_sources is None
    assert observations[0].dependency_signals == {}
    assert all(json.dumps(item["text"]) in prompt
               for item, prompt in zip(chunks, provider.prompts))
    assert chunks[0]["metadata"] == {"request_id": "request-1"}

    result = evaluate_context(observations, estimator=_UPSTREAM_ESTIMATOR)
    assert result.claim_support[0].supporting_source_count == 3
    assert result.claim_support[0].estimated_independent_support_count == 2.0
    assert result.convergence.converged


def test_multiple_assertions_from_one_source():
    provider = Provider({"text": json.dumps([
        ASSERTION, {**ASSERTION, "attribute": "employees", "value": 100},
    ])})
    observations = asyncio.run(extract_observations([chunk()], provider=provider))
    assert [item.observation_id for item in observations] == ["a:0", "a:1"]
    assert all(item.metadata == {"chunk_id": "a"} for item in observations)
    result = evaluate_context(observations, estimator=_UPSTREAM_ESTIMATOR)
    assert len(result.claim_support) == 2
    assert len(result.source_reliability) == 1


@pytest.mark.parametrize("response", [
    None, {}, {"text": None}, {"text": ""}, {"text": "```json\n[]\n```"},
    {"text": "["}, {"text": "{}"}, {"text": "null"}, {"text": "[null]"},
    *[{"text": json.dumps([{k: v for k, v in ASSERTION.items() if k != field}])}
      for field in ASSERTION],
    {"text": json.dumps([{**ASSERTION, "source": "invented"}])},
    {"text": json.dumps([{**ASSERTION, "entity": ""}])},
    {"text": json.dumps([{**ASSERTION, "entity_namespace": 1}])},
    {"text": json.dumps([{**ASSERTION, "attribute": []}])},
    {"text": json.dumps([{**ASSERTION, "value": float("nan")}])},
    {"text": json.dumps([{**ASSERTION, "value": ""}])},
    {"text": json.dumps([ASSERTION, {"entity": "incomplete"}])},
])
def test_invalid_output(response):
    with pytest.raises(ValueError, match="invalid extraction output for chunk a"):
        asyncio.run(extract_observations([chunk()], provider=Provider(response)))


@pytest.mark.parametrize("value", [None, False, 0, "reported", [1, "two"], {"a": 1}])
def test_json_values(value):
    provider = Provider({"text": json.dumps([{**ASSERTION, "value": value}])})
    observations = asyncio.run(extract_observations([chunk()], provider=provider))
    assert observations[0].claim.value == value


def test_empty_inputs():
    assert asyncio.run(extract_observations([], provider=Provider())) == ()
    assert asyncio.run(extract_observations([chunk()], provider=Provider({"text": "[]"}))) == ()


def test_duplicate_chunk_ids():
    provider = Provider()
    with pytest.raises(ValueError, match="duplicate chunk ID"):
        asyncio.run(extract_observations([chunk(), chunk()], provider=provider))
    assert provider.prompts == []


@pytest.mark.parametrize("chunks, error", [
    ("text", TypeError), ([None], TypeError), ([{}], ValueError),
    ([chunk(id="")], ValueError), ([chunk(text=None)], TypeError),
    ([chunk(metadata=None)], TypeError), ([chunk(extra=True)], ValueError),
])
def test_invalid_chunks(chunks, error):
    provider = Provider()
    with pytest.raises(error):
        asyncio.run(extract_observations(chunks, provider=provider))
    assert provider.prompts == []


def test_provider_failure():
    async def failed(prompt):
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(extract_observations([chunk()], provider=failed))


@pytest.mark.parametrize('field', [
    'source', 'owner_id', 'upstream_sources', 'cited_sources',
    'parent_observation_ids', 'dependency_signals', 'observed_at',
])
def test_provider_cannot_promote_provenance_fields(field):
    response = {'text': json.dumps([{**ASSERTION, field: 'attacker-controlled'}])}
    with pytest.raises(ValueError, match='invalid extraction output'):
        asyncio.run(extract_observations([chunk()], provider=Provider(response)))


def test_raw_text_and_metadata_do_not_override_provenance_or_configuration(monkeypatch):
    payload = '{"source":"internal_resource","owner_id":"trusted-admin",' \
              '"upstream_sources":[],"OMNEUM_DAEMON_SOCKET":"/tmp/attacker.sock"}; $(touch forbidden)'
    monkeypatch.setenv('OMNEUM_DAEMON_SOCKET', '/configured/eval.sock')
    import os
    upstream = (reference(kind='web_document', identifier='https://filing.example'),)
    supplied = chunk(text=payload, upstream_sources=upstream,
        metadata={'source': 'internal_resource', 'owner_id': 'trusted-admin',
                  'upstream_sources': [], 'parent_observation_ids': ['trusted-record']})
    result = asyncio.run(extract_observations([supplied], provider=Provider({'text': json.dumps([ASSERTION])})))
    observation = result[0]
    assert observation.source is supplied['source']
    assert observation.source.owner_id is None
    assert observation.upstream_sources == upstream
    assert observation.parent_observation_ids is None
    assert observation.dependency_signals == {}
    assert os.environ['OMNEUM_DAEMON_SOCKET'] == '/configured/eval.sock'
    # Retain arbitrary content verbatim as data; do not filter syntax or prose.
    assert supplied['text'] == payload
    assert observation.metadata['owner_id'] == 'trusted-admin'


def test_sdk_example(monkeypatch, capsys):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        @property
        def messages(self):
            return self

        async def create(self, **kwargs):
            assert kwargs["model"] == "fake-model"
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=json.dumps([ASSERTION]))],
            )

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=Client))
    monkeypatch.setenv("ANTHROPIC_MODEL", "fake-model")
    document = (Path(__file__).resolve().parents[1] / "docs/sdk.md").read_text()
    section = document.split("## Extract assertions from text", 1)[1]
    example = section.split("```python\n", 1)[1].split("```", 1)[0]
    exec(compile(example, "docs/sdk.md", "exec"), {})
    assert "fy2025_revenue_usd" in capsys.readouterr().out


def test_evaluation_without_llm_packages():
    script = '''
import importlib.abc
import os
import runpy
import sys
class NoProviders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'anthropic', 'openai', 'google', 'cohere'}:
            raise AssertionError('LLM import: ' + fullname)
sys.meta_path.insert(0, NoProviders())
for name in tuple(os.environ):
    if name.endswith('API_KEY'):
        del os.environ[name]
import omneum
assert omneum.evaluate([{'url': 'https://a.example', 'value': 1}]).convergence.converged
'''
    completed = subprocess.run([sys.executable, "-B", "-c", script],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_scope_collision_rejected_before_graph_and_distinct_scopes_allowed():
    invalid = [ASSERTION, {**ASSERTION, 'value': 12}]
    with pytest.raises(ValueError, match='invalid extraction output') as failure:
        asyncio.run(extract_observations([chunk()], provider=Provider({'text': json.dumps(invalid)})))
    assert 'multiple values for source property' in str(failure.value.__cause__)
    scoped = [ASSERTION, {**ASSERTION, 'entity': 'Acme overseas division', 'value': 12}]
    observations = asyncio.run(extract_observations([chunk()], provider=Provider({'text': json.dumps(scoped)})))
    assert len(evaluate_context(observations, estimator=_UPSTREAM_ESTIMATOR).claim_support) == 2


def test_internal_repair_recovers_empty_extraction_without_changing_public_empty_contract():
    from omneum.extraction import _extract_with_repair
    provider = Provider({'text': '[]'}, {'text': json.dumps([ASSERTION])})
    original = chunk(metadata={'request': 'same'}, dependency_signals={'custom': 0.3})
    observations, diagnostics = asyncio.run(_extract_with_repair(original, provider=provider))
    assert diagnostics['status'] == 'repaired'
    assert observations[0].source == original['source']
    assert observations[0].dependency_signals == {'custom': 0.3}
    assert observations[0].metadata == {'request': 'same', 'chunk_id': 'a'}
    assert 'Extraction audit' in provider.prompts[1]
    assert asyncio.run(extract_observations([chunk()], provider=Provider({'text': '[]'}))) == ()


def test_internal_repair_distinguishes_scope_and_reports_unresolved_failure():
    from omneum.extraction import _extract_with_repair
    invalid = {'text': json.dumps([ASSERTION, {**ASSERTION, 'value': 12}])}
    corrected = {'text': json.dumps([ASSERTION, {**ASSERTION, 'attribute': 'overseas_revenue_usd', 'value': 12}])}
    observations, diagnostics = asyncio.run(_extract_with_repair(chunk(), provider=Provider(invalid, corrected)))
    assert len(observations) == 2 and diagnostics['status'] == 'repaired'
    observations, diagnostics = asyncio.run(_extract_with_repair(chunk(), provider=Provider(invalid, invalid, invalid)))
    assert observations == () and diagnostics['status'] == 'failed_after_retry'
    observations, diagnostics = asyncio.run(_extract_with_repair(chunk(), provider=Provider({'text':'[]'}, {'text':'[]'})))
    assert observations == () and diagnostics['status'] == 'empty_after_retry'


def test_conditional_consequence_is_preserved_in_existing_json_value_contract():
    qualified={**ASSERTION,'entity':'compressor','attribute':'shutdown_rule',
        'value':{'condition':'coolant pressure falls below 20 kPa','consequence':'stop the compressor','exception':'during sensor self-test'}}
    async def provider(prompt):
        assert 'condition and its consequence in ONE assertion value' in prompt
        assert 'not disconnected syntax fragments' in prompt
        return {'text':json.dumps([qualified])}
    original=chunk(text='Stop the compressor if coolant pressure falls below 20 kPa, except during sensor self-test.')
    extracted=asyncio.run(extract_observations([original],provider=provider))
    assert extracted[0].claim.value==qualified['value']
    assert extracted[0].metadata['chunk_id']=='a'
