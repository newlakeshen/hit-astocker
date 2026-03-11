"""Event classification LLM enhancement — classify UNKNOWN events via Kimi."""

import json
import logging

from hit_astocker.llm.cache import LLMCache
from hit_astocker.llm.client import LLMClient, NullClient
from hit_astocker.llm.models import LLMEventResult
from hit_astocker.llm.prompts import EVENT_CLASSIFY_PROMPT
from hit_astocker.models.event_data import (
    EventType,
    PolicyLevel,
)

logger = logging.getLogger(__name__)

# LLM event_type string → EventType constant
_LLM_TYPE_MAP: dict[str, str] = {
    "POLICY": EventType.POLICY,
    "EARNINGS": EventType.EARNINGS,
    "CONCEPT": EventType.CONCEPT,
    "RESTRUCTURE": EventType.RESTRUCTURE,
    "TECHNICAL": EventType.TECHNICAL,
    "CAPITAL": EventType.CAPITAL,
    "INDUSTRY": EventType.INDUSTRY,
    "NEWS": EventType.NEWS,
}

_LLM_POLICY_MAP: dict[str, str] = {
    "S": PolicyLevel.STATE,
    "A": PolicyLevel.MINISTRY,
    "B": PolicyLevel.INDUSTRY,
    "C": PolicyLevel.LOCAL,
}


class EventEnhancer:
    """Batch-classify UNKNOWN events via LLM (Kimi Instant Mode)."""

    def __init__(self, client: LLMClient, cache: LLMCache | None = None):
        self._client = client
        self._cache = cache

    def classify_batch(
        self,
        unknowns: list[dict],
        trade_date: str,
    ) -> list[LLMEventResult]:
        """Classify a batch of UNKNOWN stocks via a single LLM call.

        Parameters
        ----------
        unknowns : list of dicts with keys: code, lu_desc, ann_title, themes
        trade_date : YYYYMMDD string for cache key

        Returns
        -------
        list[LLMEventResult] — one per input, or empty list on failure
        """
        if not unknowns or isinstance(self._client, NullClient):
            return []

        # Check cache
        cache_content = json.dumps(unknowns, ensure_ascii=False, sort_keys=True)
        cache_key = None
        if self._cache:
            cache_key = LLMCache.make_key(trade_date, "event_classify", cache_content)
            cached = self._cache.get_json(cache_key)
            if cached is not None:
                logger.info("LLM event classify: cache hit (%d stocks)", len(unknowns))
                return self._parse_results(cached)

        # Build prompt
        json_input = json.dumps(unknowns, ensure_ascii=False, indent=2)
        prompt = EVENT_CLASSIFY_PROMPT.format(json_input=json_input)

        try:
            response = self._client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                use_thinking=False,
            )
        except Exception:
            logger.warning("LLM event classify failed", exc_info=True)
            return []

        # Parse JSON response
        results = self._parse_response(response)

        # Cache successful result
        if results and self._cache and cache_key:
            self._cache.put_json(cache_key, [
                {"code": r.code, "event_type": r.event_type,
                 "policy_level": r.policy_level, "amount_wan": r.amount_wan,
                 "confidence": r.confidence}
                for r in results
            ])

        return results

    def _parse_response(self, response: str) -> list[LLMEventResult]:
        """Parse LLM JSON response into LLMEventResult list."""
        # Strip markdown code fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last line (``` markers)
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM event classify: JSON parse failed: %s", text[:200])
            return []

        if not isinstance(data, list):
            logger.warning("LLM event classify: expected list, got %s", type(data))
            return []

        return self._parse_results(data)

    @staticmethod
    def _parse_results(data: list) -> list[LLMEventResult]:
        """Convert raw dicts to LLMEventResult objects."""
        results = []
        for item in data:
            if not isinstance(item, dict):
                continue
            code = item.get("code", "")
            raw_type = item.get("event_type", "UNKNOWN")
            event_type = _LLM_TYPE_MAP.get(raw_type, EventType.UNKNOWN)

            raw_policy = item.get("policy_level")
            policy_level = _LLM_POLICY_MAP.get(raw_policy, None) if raw_policy else None

            amount_wan = item.get("amount_wan")
            if amount_wan is not None:
                try:
                    amount_wan = float(amount_wan)
                except (TypeError, ValueError):
                    amount_wan = None

            confidence = float(item.get("confidence", 0.0))

            results.append(LLMEventResult(
                code=code,
                event_type=event_type,
                policy_level=policy_level,
                amount_wan=amount_wan,
                confidence=confidence,
            ))
        return results
