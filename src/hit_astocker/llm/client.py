"""LLM client abstraction — KimiClient (Kimi K2.5) + NullClient (no-op fallback)."""

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM client implementations."""

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.6,
        max_tokens: int = 2000,
        use_thinking: bool = False,
    ) -> str:
        """Send chat completion request and return the response content."""
        ...


class NullClient:
    """No-op LLM client — returns empty string, zero cost."""

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.6,
        max_tokens: int = 2000,
        use_thinking: bool = False,
    ) -> str:
        return ""


class KimiClient:
    """Kimi K2.5 client via OpenAI-compatible SDK.

    Uses Instant Mode by default (thinking disabled) for structured tasks.
    Thinking Mode can be enabled for creative/analytical tasks.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.moonshot.cn/v1",
        model: str = "kimi-k2.5",
        timeout: float = 30.0,
    ):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai package required for LLM integration. "
                "Install with: pip install 'hit-astocker[llm]'"
            )

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.6,
        max_tokens: int = 2000,
        use_thinking: bool = False,
    ) -> str:
        """Send chat completion and return content string.

        Parameters
        ----------
        messages : list of role/content dicts
        temperature : sampling temperature (0.6 for Instant, 1.0 for Thinking)
        max_tokens : max output tokens
        use_thinking : if False, disable thinking (Instant Mode); if True, Thinking Mode
        """
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": 1.0 if use_thinking else temperature,
            "max_tokens": max_tokens,
        }
        if not use_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        return choice.message.content or ""


def get_llm_client(settings) -> LLMClient:
    """Factory: return KimiClient if enabled and configured, else NullClient."""
    if not settings.llm_enabled:
        return NullClient()

    if not settings.kimi_api_key:
        logger.warning("LLM enabled but KIMI_API_KEY not set — falling back to NullClient")
        return NullClient()

    try:
        return KimiClient(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            model=settings.kimi_model,
        )
    except ImportError:
        logger.warning("openai package not installed — falling back to NullClient")
        return NullClient()
