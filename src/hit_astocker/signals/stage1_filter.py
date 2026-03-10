"""Stage 1: Hard filter — removes candidates that should never be traded.

Extracts hard NO_GO rules into a dedicated pre-ML filter stage.
The remaining candidates are passed to Stage 2 (ML ranking or rule-based scoring).

Filters are deliberately conservative: only remove obvious non-tradeable samples.
Borderline cases should pass to Stage 2 for proper scoring.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hit_astocker.models.sentiment_cycle import CyclePhase
from hit_astocker.utils.stock_filter import should_exclude

if TYPE_CHECKING:
    from hit_astocker.models.daily_context import DailyAnalysisContext
    from hit_astocker.signals.composite_scorer import ScoredCandidate

logger = logging.getLogger(__name__)


class Stage1Filter:
    """Hard filter: removes candidates that cannot produce profitable trades.

    Rules (any → filter out):
    1. ST / BJ / 风险警示 — 制度性不可交易
    2. 大盘暴跌 — 系统性风险, 全面空仓
    3. 情绪极度低迷 — 市场整体无赚钱效应
    4. 退潮期低分标的 — 除绝对龙头外全部回避
    5. 冰点期低分标的 — 仅极高分龙头可参与
    6. 质量硬伤 — 首板封板质量极差 / 连板生存率极低
    """

    def filter(
        self,
        candidates: list[ScoredCandidate],
        ctx: DailyAnalysisContext,
    ) -> list[ScoredCandidate]:
        """Stage 1: remove non-tradeable samples, return survivors."""
        # Market-level kill conditions (affects ALL candidates)
        if self._market_kill(ctx):
            logger.info("Stage1: market-level kill → 0 candidates pass")
            return []

        result = []
        for c in candidates:
            reason = self._should_filter(c, ctx)
            if reason:
                logger.debug("Stage1: filtered %s (%s) — %s", c.ts_code, c.name, reason)
                continue
            result.append(c)

        logger.info(
            "Stage1: %d/%d candidates pass hard filter",
            len(result), len(candidates),
        )
        return result

    @staticmethod
    def _market_kill(ctx: DailyAnalysisContext) -> bool:
        """Market-level conditions that kill ALL signals."""
        # 大盘暴跌
        mc = ctx.sentiment.market_context
        if mc and (mc.sh_pct_chg <= -3.0 or mc.gem_pct_chg <= -4.0):
            return True

        # 情绪极度低迷 (打板完全无赚钱效应)
        if ctx.sentiment.overall_score < 25:
            return True

        return False

    @staticmethod
    def _should_filter(c: ScoredCandidate, ctx: DailyAnalysisContext) -> str | None:
        """Return filter reason string, or None if candidate passes.

        Only hard rules that are unambiguously disqualifying.
        """
        # 1. ST / BJ / 风险警示
        if should_exclude(c.ts_code, c.name):
            return "ST/BJ/风险警示"

        # 2. 退潮期: 除绝对龙头外全部回避
        cycle = ctx.sentiment_cycle
        if cycle and cycle.phase == CyclePhase.RETREAT:
            if not (c.signal_type == "SECTOR_LEADER" and c.score >= 85):
                return f"退潮期 (score={c.score:.0f})"

        # 3. 冰点期: 仅极高分标的可参与
        if cycle and cycle.phase == CyclePhase.ICE:
            if c.score < 75:
                return f"冰点期 (score={c.score:.0f})"

        # 4. 首板封板质量硬伤 (封板质量极差 = 炸板概率极高)
        if c.signal_type == "FIRST_BOARD":
            sq = c.factors.get("seal_quality", 0)
            if sq < 25:
                return f"封板质量极差 (seal_quality={sq:.0f})"

        # 5. 连板生存率极低 (历史统计上几乎必炸)
        if c.signal_type == "FOLLOW_BOARD":
            surv = c.factors.get("survival", 0)
            if surv < 15:
                return f"晋级率极低 (survival={surv:.0f})"

        return None
