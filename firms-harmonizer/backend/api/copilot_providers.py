"""Bounded completions from the selected provider, with local evidence on failure."""
from __future__ import annotations

from backend.api.copilot_network import is_offline

import logging
import os
from time import monotonic

import httpx

log = logging.getLogger(__name__)
PROMPT_CHAR_LIMIT = 4500
OUTPUT_TOKEN_LIMIT = 900


def agent_config() -> tuple[str, str, str, str]:
    """Return the selected provider only; credentials never cross providers."""
    provider = os.getenv('COPILOT_PROVIDER', 'gemini').strip().lower()
    if provider == 'gemini':
        return (provider, os.getenv('GEMINI_API_KEY', ''),
                'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
                os.getenv('GEMINI_MODEL', 'gemini-3.8-flash'))
    if provider == 'groq':
        return (provider, os.getenv('GROQ_API_KEY', ''),
                'https://api.groq.com/openai/v1/chat/completions',
                os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b'))
    return ('unconfigured', '', '', '')


def bounded_messages(messages: list[dict]) -> list[dict]:
    """Retain instructions and the latest evidence; drop older conversation first.

    This is a final transport bound. Callers should supply compact, complete JSON
    evidence so a truncation never removes the most relevant document passages.
    """
    if sum(len(str(m.get('content', ''))) for m in messages) <= PROMPT_CHAR_LIMIT:
        return messages
    system = next((str(m.get('content', '')) for m in messages if m.get('role') == 'system'), '')[:1900]
    latest = str(messages[-1].get('content', '')) if messages else ''
    return [{'role': 'system', 'content': system},
            {'role': 'user', 'content': latest[:PROMPT_CHAR_LIMIT-len(system)]}]


def complete(messages: list[dict], *, structured: bool = False,
             schema: dict | None = None, timeout: float = 10,
             default_model: str = 'llama-3.3-70b-versatile') -> tuple[str | None, str]:
    if is_offline():
        return None, 'deterministic-offline-science'
    # Auxiliary extraction uses the same selection as the main investigator.
    # Groq is an explicit alternative, never a hidden fallback from Gemini.
    selected, _, selected_url, selected_model = agent_config()
    providers = [
        ('groq', 'GROQ_API_KEY', 'https://api.groq.com/openai/v1/chat/completions',
         os.getenv('GROQ_MODEL', default_model)),
        ('groq-compatible', 'GROQ_API_KEY', 'https://api.groq.com/openai/v1/chat/completions',
         os.getenv('GROQ_FALLBACK_MODEL', 'openai/gpt-oss-120b')),
    ]
    if selected == 'gemini':
        providers = [('gemini', 'GEMINI_API_KEY', selected_url, selected_model)]
    elif selected != 'groq':
        providers = []
    messages = bounded_messages(messages)
    # A single deadline bounds the entire cascade, including exhausted quotas.
    deadline = monotonic() + min(10.0, timeout)
    model_unavailable = False
    for provider, variable, url, model in providers:
        if provider == 'groq-compatible' and not model_unavailable:
            continue
        key = os.getenv(variable)
        remaining = deadline - monotonic()
        if not key or not url or remaining < 0.1:
            continue
        body = {'model': model, 'messages': messages, 'temperature': 0.2,
                'max_tokens': OUTPUT_TOKEN_LIMIT}
        if provider == 'gemini':
            body['reasoning_effort'] = 'low'
        if 'gpt-oss' in model:
            body['reasoning_effort'] = 'low'
        if schema and provider.startswith('groq') and 'gpt-oss' in model:
            body['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'fire_answer', 'strict': True, 'schema': schema}}
        elif schema or structured:
            body['response_format'] = {'type': 'json_object'}
        try:
            with httpx.Client(timeout=httpx.Timeout(remaining, connect=min(3, remaining))) as client:
                response = client.post(url, headers={'Authorization': f'Bearer {key}'}, json=body)
            model_unavailable = provider == 'groq' and response.status_code == 404
            response.raise_for_status()
            choice = response.json()['choices'][0]
            content = choice['message'].get('content')
            if choice.get('finish_reason') == 'stop' and isinstance(content, str) and content.strip():
                return content.strip(), f'{provider.removesuffix("-compatible")}/{model}'
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            log.info('Copilot provider %s unavailable; continuing bounded cascade', provider)
    return None, 'deterministic-offline-science'
