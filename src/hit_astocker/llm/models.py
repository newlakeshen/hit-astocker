"""LLM output data models (frozen dataclasses)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMEventResult:
    """LLM 事件分类结果."""

    code: str
    event_type: str
    policy_level: str | None = None
    amount_wan: float | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class LLMSignalReason:
    """LLM 生成的信号理由."""

    ts_code: str
    reason: str
    confidence: float = 0.0


@dataclass(frozen=True)
class ThemeCluster:
    """LLM 题材语义聚类结果."""

    main_theme: str
    sub_themes: tuple[str, ...]
    narrative: str
