"""Build a provider adapter from a ModelSpec."""
from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from lilly.domain.caps import Cap
from lilly.domain.errors import ConfigurationError
from lilly.domain.ports import KeyStore, Provider
from lilly.domain.settings import ModelSpec
from lilly.providers.gemini import GeminiProvider
from lilly.providers.local_gate import LocalGate
from lilly.providers.ollama import DEFAULT_KEEP_ALIVE_S, OllamaProvider
from lilly.providers.openai_compat import OpenAICompatProvider

_REASONING = re.compile(r"^(o\d|gpt-5)")
REASONING_TOKEN_FACTOR = 4
_OPENAI_URL = "https://api.openai.com/v1"
_MISTRAL_URL = "https://api.mistral.ai/v1"
_OPENROUTER_URL = "https://openrouter.ai/api/v1"


def build_provider(spec: ModelSpec, client: httpx.AsyncClient, keys: KeyStore,
                   local_client: httpx.AsyncClient | None = None, gate: LocalGate | None = None,
                   keep_alive_s: Callable[[], int] | None = None) -> Provider:
    """The adapter for `spec`. A model's key reference defaults to its provider name. Servers on this computer
    use `local_client`, which never goes through a proxy."""
    ref = spec.key_ref or spec.provider
    json_ok = bool(spec.caps & Cap.JSON)
    if spec.provider == "mistral":
        return OpenAICompatProvider("mistral", client, keys, ref, spec.model_id, spec.base_url or _MISTRAL_URL,
                                    json_mode=json_ok)
    if spec.provider == "openai":
        reasoning = bool(_REASONING.match(spec.model_id))   # these models take no temperature and think before answering
        return OpenAICompatProvider("openai", client, keys, ref, spec.model_id, spec.base_url or _OPENAI_URL,
                                    json_mode=json_ok, limit_field="max_completion_tokens",
                                    send_temperature=not reasoning, limit_factor=REASONING_TOKEN_FACTOR if reasoning else 1,
                                    stream_usage=True)
    if spec.provider == "openrouter":
        return OpenAICompatProvider("openrouter", client, keys, ref, spec.model_id, spec.base_url or _OPENROUTER_URL,
                                    {"X-Title": "Lilly"}, json_mode=json_ok)
    if spec.provider == "gemini":
        return GeminiProvider(client, keys, ref, spec.model_id, spec.base_url or "https://generativelanguage.googleapis.com/v1beta")
    if spec.provider == "ollama":
        return OllamaProvider(local_client or client, spec.model_id, spec.base_url, gate,
                              keep_alive_s or (lambda: DEFAULT_KEEP_ALIVE_S))
    raise ConfigurationError(f"unknown provider {spec.provider!r}")
