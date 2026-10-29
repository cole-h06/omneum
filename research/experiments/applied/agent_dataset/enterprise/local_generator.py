import re
import subprocess
import time

import httpx


class LocalGenerator:
    def __init__(self, model):
        self.http = httpx.Client(trust_env=False, timeout=300)
        self.endpoint = 'http://127.0.0.1:11434'
        self.model = model
        self.options = {'temperature': 0, 'seed': 42, 'num_ctx': 8192, 'num_predict': 256}
        installed = self.request(self.endpoint, '/api/tags')['models']
        self.identity = next(item for item in installed if item['name'] == model)
        info = self.request(self.endpoint, '/api/show', {'model': model})
        if info.get('remote_host') or info.get('remote_model') or info['details']['family'] != 'qwen2':
            raise ValueError('This adapter requires an installed local Qwen2 model')
        self.request(self.endpoint, '/api/generate', {
            'model': model, 'prompt': 'Reply OK.', 'stream': False,
            'options': {**self.options, 'num_predict': 8}, 'keep_alive': '30m',
        })
        processes = subprocess.check_output(['ps', '-axo', 'command='], text=True)
        ports = [match[1] for line in processes.splitlines() if 'ollama' in line and 'llama-server' in line
                 if (match := re.search(r'--port\s+(\d+)\b', line))]
        if len(ports) != 1:
            raise ValueError('Exactly one resident Ollama llama-server is required')
        self.tokenizer = 'http://127.0.0.1:' + ports[0]
        self.tokenizer_identity = {'endpoint': self.tokenizer, 'name': 'resident model tokenizer',
                                   'template': info['template'], 'model_digest': self.identity['digest']}
        self.generate('Reply with OK.')

    def request(self, endpoint, route, payload=None):
        response = (self.http.get(endpoint + route) if payload is None else
                    self.http.post(endpoint + route, json=payload))
        response.raise_for_status()
        result = response.json()
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result

    def count(self, text):
        return len(self.request(self.tokenizer, '/tokenize', {
            'content': text, 'add_special': False, 'parse_special': True,
        })['tokens'])

    def generate(self, prompt):
        rendered = self.request(self.tokenizer, '/apply-template', {
            'messages': [{'role': 'user', 'content': prompt}],
        })['prompt']
        predicted = self.count(rendered)
        if predicted + self.options['num_predict'] > self.options['num_ctx']:
            raise ValueError('Full prompt and reserved output exceed model context window')
        request = {'model': self.model, 'prompt': rendered, 'raw': True, 'stream': False,
                   'options': dict(self.options), 'keep_alive': '30m'}
        started = time.perf_counter()
        response = self.request(self.endpoint, '/api/generate', request)
        seconds = time.perf_counter() - started
        if response.get('prompt_eval_count') != predicted:
            raise ValueError(f"Tokenizer mismatch: {predicted} != {response.get('prompt_eval_count')}")
        if not response.get('done') or type(response.get('eval_count')) is not int:
            raise ValueError('Incomplete model response or missing actual output usage')
        return {'request': request, 'response': response, 'seconds': seconds,
                'predicted_input_tokens': predicted}
