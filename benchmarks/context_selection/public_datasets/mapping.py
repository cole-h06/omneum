"""Constrained local generation for the production source-mapping protocols."""

import json
from copy import deepcopy
import re
import shlex
import subprocess
from time import perf_counter

import httpx
from jsonschema import validate
from research.experiments.applied.agent_dataset.enterprise.local_generator import LocalGenerator

from omneum.extraction import _grounded_response_schema


MAPPING_CONTEXT = 32768
MAPPING_OUTPUT = 16384
CLAIM_SCHEMA = {
    'type': 'object',
    'properties': {**{k: {'type': 'string'} for k in ('entity_namespace', 'entity', 'attribute')},
                   'value': {'type': 'object', 'properties': {
                       'assertion': {'type': 'string'},
                       **{k: {'type': ['string', 'null']} for k in ('scope', 'condition', 'ordering', 'modality')}},
                       'required': ['assertion', 'scope', 'condition', 'ordering', 'modality'],
                       'additionalProperties': False}},
    'required': ['entity_namespace', 'entity', 'attribute', 'value'],
    'additionalProperties': False,
}


def object_schema(name, value):
    return dict(type='object', properties={name: value}, required=[name], additionalProperties=False)


def response_schema(prompt):
    if 'Source text (JSON string):\n' in prompt:
        source = json.loads(prompt.split('Source text (JSON string):\n', 1)[1])
        schema = _grounded_response_schema(source)
        if 'Repair request JSON:' in prompt:
            schema['items']['properties']['observation_id'] = dict(type=['string','null'])
        return schema
    data = json.loads(prompt.split('Input JSON:\n', 1)[1])
    phase = data.get('phase')
    if phase == 'identity_verification':
        quotes = ([data['source_text']] if data.get('evidence_scope') == 'whole_source_v1' else
                  _grounded_response_schema(data['source_text'])['items']['properties']['evidence']['enum'])
        item = dict(type='object',properties={
            'group_id':dict(type='string',enum=[g['group_id'] for g in data['groups']]),
            'distinct':dict(type='boolean'), 'evidence':dict(type='string',enum=['',*quotes]),
            'issues':dict(type='array',items=dict(type='string',minLength=1))},
            required=['group_id','distinct','evidence','issues'],additionalProperties=False)
        if data.get('decision_contract') == 'property_partition_v2':
            item['properties'] = dict(group_id=item['properties']['group_id'],
                reason=dict(type='string',minLength=1),
                supported_partition=dict(type='boolean'), evidence=item['properties']['evidence'],
                issues=item['properties']['issues'])
            item['required'] = ['group_id','reason','supported_partition','evidence','issues']
        size = len(data['groups'])
        return object_schema('decisions',dict(type='array',items=item,minItems=size,maxItems=size))
    if phase in ('identity_repair','mixed_repair'):
        if data.get('identity_format') == 'target_slots_v1':
            identity = dict(type='object',properties={k:dict(type='string',minLength=1)
                            for k in ('entity_namespace','entity','attribute')},
                            required=['entity_namespace','entity','attribute'],additionalProperties=False)
            slot = dict(type='object',properties={
                'reason':dict(type='string',minLength=1),
                'identity':dict(anyOf=[identity,dict(type='null')])},
                required=['reason','identity'],additionalProperties=False)
            identifiers = [o['observation_id'] for o in data['observations']]
            schema = object_schema('identities',dict(type='object',properties={i:slot for i in identifiers},
                required=identifiers,additionalProperties=False))
            if phase == 'mixed_repair':
                records = _grounded_response_schema(data['source_text'])
                item = dict(anyOf=[records['items'],dict(type='null')])
                rejected_ids = [r['observation_id'] for r in data['other_repairs']['rejected'] if 'observation_id' in r]
                schema['properties']['records'] = dict(type='object',properties={i:item for i in rejected_ids},
                    required=rejected_ids,additionalProperties=False)
                schema['properties']['additions'] = records
                schema['properties']['additions']['maxItems'] = len(data['other_repairs']['missing'])
                schema['required'].extend(['records','additions'])
            return schema
        # Preserve validation of historical call receipts; new requests use slots.
        size = len(data['observations'])
        item = dict(type='object', properties={
            'observation_id':dict(type='string',enum=[o['observation_id'] for o in data['observations']]),
            **{k:dict(type='string',minLength=1) for k in ('entity_namespace','entity','attribute')}},
            required=['observation_id','entity_namespace','entity','attribute'],additionalProperties=False)
        schema = object_schema('identities',dict(type='array',items=item,minItems=size,maxItems=size))
        if phase == 'mixed_repair':
            records = _grounded_response_schema(data['source_text'])
            records['items']['properties']['observation_id'] = dict(type=['string','null'])
            schema['properties']['records'] = records
            schema['required'].append('records')
        return schema
    if phase == 'extraction_verification':
        count = len(data['observations'])
        grounded = _grounded_response_schema(data['source_text'])
        quotes = grounded.get('items', {}).get('properties', {}).get('evidence', {}).get('enum', [])
        decision = dict(type='object', properties={
            'observation_id':dict(type='string', enum=[o['observation_id'] for o in data['observations']
                                                       if 'observation_id' in o]),
            'entailed':dict(type='boolean'), 'complete':dict(type='boolean'),
            'evidence':dict(type='string', enum=['', *quotes]),
            'issues':dict(type='array', items=dict(type='string', minLength=1)),
        }, required=['observation_id','entailed','complete','evidence','issues'], additionalProperties=False)
        if not data['observations'] or any('observation_id' not in o for o in data['observations']):
            decision['properties'].pop('observation_id')
            decision['required'].remove('observation_id')
        if data.get('decision_contract') == 'source_support_v2':
            decision['properties'] = dict(reason=dict(type='string', minLength=1), **decision['properties'])
            decision['required'].insert(0, 'reason')
        return dict(type='object', properties={
            'decisions':dict(type='array', items=decision, minItems=count, maxItems=count),
            'missing':_grounded_response_schema(data['source_text']),
        }, required=['decisions','missing'], additionalProperties=False)
    if phase == 'missing_verification':
        size = len(data['proposals'])
        grounded = _grounded_response_schema(data['source_text'])
        quotes = grounded.get('items', {}).get('properties', {}).get('evidence', {}).get('enum', [])
        decision = dict(type='object', properties={
            'proposal_id':dict(type='string', enum=[p['proposal_id'] for p in data['proposals']]),
            'supported':dict(type='boolean'), 'already_represented':dict(type='boolean'),
            'matching_observation_ids':dict(type='array', items=dict(type='string',
                enum=[o['observation_id'] for o in data['observations']])) if data['observations'] else dict(type='array', maxItems=0),
            'evidence':dict(type='string', enum=['', *quotes]), 'issues':dict(type='array', items=dict(type='string', minLength=1)),
        }, required=['proposal_id','supported','already_represented','matching_observation_ids','evidence','issues'],
            additionalProperties=False)
        if data.get('decision_contract') == 'source_support_v2':
            decision['properties'] = dict(reason=dict(type='string', minLength=1), **decision['properties'])
            decision['required'].insert(0, 'reason')
        return object_schema('decisions', dict(type='array', items=decision, minItems=size, maxItems=size))
    if phase == 'continuity_verification':
        identifiers = [p['proposal_id'] for p in data['proposals']]
        decision = dict(type='object',properties={
            'proposal_id':dict(type='string',enum=identifiers),
            'reason':dict(type='string',minLength=1), 'supported':dict(type='boolean'),
            'evidence':dict(type='string',enum=[data['source_text']])},
            required=['proposal_id','reason','supported','evidence'],additionalProperties=False)
        return object_schema('decisions',dict(type='array',items=decision,
            minItems=len(identifiers),maxItems=len(identifiers)))
    if phase == 'verify':
        return object_schema('equivalent', {'type': 'boolean'})
    if phase == 'atomic_equivalence':
        return object_schema('equivalent', dict(type='array', items={'type': 'boolean'},
                                               minItems=len(data['pairs']), maxItems=len(data['pairs'])))
    if phase == 'assignment':
        return object_schema('assignments', dict(type='array', items={'type': 'integer', 'enum': data['allowed_indices']},
                                                minItems=1, maxItems=1))
    if phase is not None:
        raise ValueError(f'unsupported production mapping phase: {phase}')
    size = len(data['observations'])
    return object_schema('observations', dict(type='array', items=CLAIM_SCHEMA, minItems=size, maxItems=size))


def tokenizer_endpoint(processes, model_path, context):
    ports = []
    for line in processes.splitlines():
        if re.match(r'^\S*/llama-server\s', line) is None:
            continue
        args = shlex.split(line)
        if all(flag in args for flag in ('--model', '--port', '-c')):
            if args[args.index('--model') + 1] == model_path and int(args[args.index('-c') + 1]) == context:
                ports.append(args[args.index('--port') + 1])
    if len(ports) != 1:
        raise ValueError('exactly one matching model/context tokenizer is required')
    return 'http://127.0.0.1:' + ports[0]


class PublicGenerator(LocalGenerator):
    """Retain shared generation/counting with an explicit resident context binding."""

    def __init__(self, model):
        self.http = httpx.Client(trust_env=False, timeout=300)
        self.endpoint = 'http://127.0.0.1:11434'
        self.model = model
        self.options = dict(temperature=0, seed=42, num_ctx=MAPPING_CONTEXT, num_predict=256)
        self.identity = next(v for v in self.request(self.endpoint, '/api/tags')['models'] if v['name'] == model)
        info = self.request(self.endpoint, '/api/show', {'model': model})
        if info.get('remote_host') or info.get('remote_model') or info['details']['family'] not in ('qwen2','qwen3'):
            raise ValueError('public evaluation requires an installed local Qwen2/Qwen3 model')
        self.mapping_chat = info['details']['family'] == 'qwen3'
        model_path = re.search(r'^FROM (.+)$', info['modelfile'], re.M).group(1).strip('"')
        self.request(self.endpoint, '/api/generate', dict(
            model=model, prompt='Reply OK.', stream=False, keep_alive='30m',
            options={**self.options, 'num_predict': 1}, **({'think': False} if self.mapping_chat else {})))
        self.tokenizer = tokenizer_endpoint(subprocess.check_output(['ps', '-axo', 'command='], text=True),
                                            model_path, MAPPING_CONTEXT)
        self.tokenizer_identity = dict(endpoint=self.tokenizer, name='resident model tokenizer',
                                       template=info['template'], model_digest=self.identity['digest'])
        if not self.mapping_chat:
            self.generate('Reply with OK.')


def generate_mapping(generator, prompt):
    """Use Ollama's JSON grammar without changing production extraction/validation."""
    schema = response_schema(prompt)
    wire_schema = deepcopy(schema)
    quotes = ['']
    indexed_nodes = set()
    # Transport exact quotation choices as indices, then expand them verbatim.
    # This avoids asking a local model to copy the same long prefix per claim.
    def index_quotes(node):
        if isinstance(node,list):
            for child in node:
                index_quotes(child)
            return
        if not isinstance(node, dict):
            return
        if id(node) in indexed_nodes:
            return
        indexed_nodes.add(id(node))
        evidence = node.get('properties', {}).get('evidence')
        if evidence and 'enum' in evidence:
            for quote in evidence['enum']:
                if quote not in quotes:
                    quotes.append(quote)
            node['properties']['evidence'] = dict(type='integer', enum=[quotes.index(q) for q in evidence['enum']])
        for value in node.values():
            if isinstance(value, (dict,list)):
                index_quotes(value)
    index_quotes(wire_schema)
    instruction = '\nReturn compact JSON matching the schema, without Markdown. '
    if 'Source text (JSON string):\n' in prompt:
        instruction += ('Use a verbatim passage prefix as evidence, ending after the supporting sentence. '
                        'Include preceding sentences so the subject and every literal number in a claim '
                        'are grounded in that span. Do not invent facts or paraphrase quotations. '
                        'Preserve distinct source properties and all explicit facts and qualifications.')
    content = prompt + instruction
    if len(quotes) > 1:
        choices = [dict(index=i, end_character=len(q), ends_with=q[-80:]) for i, q in enumerate(quotes)]
        content += ('\nWire format: every evidence field must contain an INTEGER quotation index, not copied text. '
            'Each index selects the exact original passage prefix ending at end_character. Index 0 is empty evidence. '
            'Indices and offsets are transport metadata, never facts about the world. All semantic decisions '
            'and claim fields follow the instructions above. Quotation choices:\n' + json.dumps(choices, ensure_ascii=False))
    chat = getattr(generator, 'mapping_chat', False)
    if chat:
        # Native Qwen3 templates implement think=False. A raw chatml prompt
        # cannot safely emulate that model-specific switch. Reserve a strict
        # template margin before calling the native API; never trim source text.
        raw_tokens = generator.count(content)
        predicted = raw_tokens + 1024
        available = generator.options['num_ctx'] - predicted
        route = '/api/chat'
        request = dict(model=generator.model, messages=[dict(role='user', content=content)],
            think=False, stream=False, format=wire_schema,
            options={**generator.options, 'num_predict': min(MAPPING_OUTPUT, available)}, keep_alive='30m')
    else:
        rendered = generator.request(generator.tokenizer, '/apply-template', {
            'messages': [{'role': 'user', 'content': content}]})['prompt']
        predicted = generator.count(rendered)
        available = generator.options['num_ctx'] - predicted
        route = '/api/generate'
        request = dict(model=generator.model, prompt=rendered, raw=True, stream=False, format=wire_schema,
                       options={**generator.options, 'num_predict': min(MAPPING_OUTPUT, available)}, keep_alive='30m')
    if available <= 0:
        raise ValueError('mapping input exceeds its context window; no truncation permitted')
    started = perf_counter()
    # Mapping a complete candidate pool can produce substantially more output
    # than a short answer. This is separate from downstream answer settings.
    response = generator.http.post(generator.endpoint + route, json=request, timeout=1200)
    response.raise_for_status()
    result = response.json()
    if 'error' in result:
        raise RuntimeError(result['error'])
    if chat:
        actual = result.get('prompt_eval_count')
        if type(actual) is not int or not raw_tokens <= actual <= predicted:
            raise ValueError('native chat template exceeded preflight token margin')
        if result.get('message', {}).get('thinking'):
            raise ValueError('model did not honor think=False')
        result['response'] = result['message']['content']
    elif result.get('prompt_eval_count') != predicted:
        raise ValueError('mapping tokenizer mismatch')
    if result.get('done_reason') == 'length':
        error = ValueError('mapping response exhausted its output-token limit')
        error.response = result
        raise error
    if not result.get('done') or type(result.get('eval_count')) is not int:
        raise ValueError('incomplete mapping generation')
    raw_text = result['response']
    if len(quotes) > 1:
        decoded = json.loads(raw_text)
        def expand(value):
            if isinstance(value, list):
                return [expand(v) for v in value]
            if isinstance(value, dict):
                output = {k: expand(v) for k, v in value.items()}
                if 'evidence' in output:
                    index = output['evidence']
                    if type(index) is not int or not 0 <= index < len(quotes):
                        raise ValueError('invalid source quotation index')
                    output['evidence'] = quotes[index]
                return output
            return value
        decoded = expand(decoded)
        validate(decoded, schema)
        result['response'] = json.dumps(decoded, ensure_ascii=False)
    return dict(request=request, response=result, seconds=perf_counter() - started, predicted_input_tokens=predicted,
                raw_text=raw_text, evidence_choices=quotes, evidence_transport='source-prefix-index-v1')
