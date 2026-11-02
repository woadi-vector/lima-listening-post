"""Explicit, per-source Meta Model API inference. No automatic cloud routing."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

from .interpret import NoRedirect, SYSTEM, OUTPUT_SCHEMA

MODEL = 'muse-spark-1.3'
PROPOSER = 'meta:' + MODEL


def ready():
    return bool(os.environ.get('MODEL_API_KEY'))


def extract_candidates(content, project_name, *, mode='mixed', cloud_consent=False, timeout=120, subject_folders=None):
    if cloud_consent is not True:
        raise ValueError('Confirm sending this selected source and project name to Meta first.')
    if not ready():
        raise ValueError('Meta Model API key is unavailable to Lima. Local inference remains available.')
    if mode not in {'mixed', 'reference', 'work'} or not isinstance(content, str) or len(content) > 24000:
        raise ValueError('Invalid source section or interpretation mode')
    system = SYSTEM + "\nReuse an existing_subject_folders name only when the passage clearly refers to that same subject. Otherwise use a new concise subject. Never merge unrelated topics merely because names look similar."
    if mode == 'reference':
        system += '\nThis source is designated reference material. Return reference learning only.'
    result = structured_object(system, {'project_context': project_name, 'source_text': content, 'existing_subject_folders': (subject_folders or [])[:100]}, OUTPUT_SCHEMA, 'lima_claims', cloud_consent=cloud_consent, timeout=timeout)
    if not isinstance(result, dict) or not isinstance(result.get('claims'), list) or len(result['claims']) > 20 or any(not isinstance(c, dict) for c in result['claims']):
        raise ValueError('Meta returned invalid claim records')
    return result['claims']


def structured_object(system, payload, output_schema, name, *, cloud_consent=False, timeout=120, max_completion_tokens=8192, reasoning_effort='low'):
    if cloud_consent is not True:
        raise ValueError('Confirm sending selected context to Meta first.')
    if not ready():
        raise ValueError('Meta Model API key is unavailable to Lima.')
    if not isinstance(max_completion_tokens,int) or not 512<=max_completion_tokens<=8192:
        raise ValueError('Invalid Meta output budget')
    if reasoning_effort not in {'low','medium','high'}:raise ValueError('Invalid Meta reasoning effort')
    request = Request('https://api.meta.ai/v1/chat/completions',
        data=json.dumps({'model': MODEL, 'stream': False, 'max_completion_tokens': max_completion_tokens, 'reasoning_effort':reasoning_effort,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': json.dumps(payload)}],
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': name, 'strict': False, 'schema': output_schema}}}).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['MODEL_API_KEY'], 'Content-Type': 'application/json'}, method='POST')
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(1000001)
        if len(body) > 1000000:
            raise ValueError('Meta response exceeded the size limit')
        reply = json.loads(body)
        choice = reply['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise ValueError('Meta reached its output limit; retry a smaller section')
        if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
            raise ValueError('Meta did not complete structured interpretation')
        result = json.loads(choice['message']['content'])
        return result
    except HTTPError as error:
        messages = {401: 'Meta rejected the API key.', 402: 'Meta requires billing or credits before inference.',
                    403: 'Meta denied access to this model.', 429: 'Meta rate limit reached; retry later.'}
        raise ValueError(messages.get(error.code, f'Meta inference failed (HTTP {error.code}). No work state changed.')) from None
    except (URLError, OSError, TimeoutError):
        raise ValueError('Meta is unavailable or timed out. No local fallback or automatic upload retry occurred.') from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError('Meta returned an invalid structured response; no work state changed.') from None
