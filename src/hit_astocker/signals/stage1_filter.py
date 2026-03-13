"""Stage 1: Hard filter — removes candidates that should never be traded.

Extracts hard NO_GO rules into a dedicated pre-ML filter stage.
The remaining candidates are passed to Stage 2 (ML ranking or rule-based scoring).

Filters are deliberately conservative: only remove obvious non-tradeable samples.
Borderline cases should pass to Stage 2 for proper scoring.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hit_astocker.models.profit_effect import ProfitRegime
from hit_astocker.models.sentiment_cycle import CyclePhase
from hit_astocker.utils.stock_filter import should_exclude

if TYPE_CHECKING:
    from hit_astocker.models.daily_context import DailyAnalysisContext
    from hit_astocker.models.profit_effect import ProfitEffectSnapshot
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

        # 赚钱效应冰封 (分层数据驱动: 全面亏钱效应)
        pe = ctx.profit_effect
        if pe and pe.regime == ProfitRegime.FROZEN:
            return True

        # 系统性弱市: STRONG_BEAR + WEAK赚钱效应 + 情绪低迷 → 全面空仓
        if mc and mc.market_regime == "STRONG_BEAR" and pe:
            if pe.regime == ProfitRegime.WEAK and ctx.sentiment.overall_score < 40:
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

        # 4. 首板封板质量硬伤 (封板质量差 = 炸板概率高)
        if c.signal_type == "FIRST_BOARD":
            sq = c.factors.get("seal_quality", 0)
            if sq < 45:
                return f"封板质量差 (seal_quality={sq:.0f})"

        # 4b. 赚钱效应分层门控 (数据驱动, 替代部分经验阈值)
        pe = ctx.profit_effect
        if pe:
            pe_reason = _profit_effect_gate(c, pe)
            if pe_reason:
                return pe_reason

        # 5. 连板衰减: 高度越高, 生存率门槛越严
        #    连板可能性随高度递增而递减, 高位板需要更高的质量才值得参与
        if c.signal_type == "FOLLOW_BOARD":
            surv = c.factors.get("survival", 0)
            hm = c.factors.get("height_momentum", 0)
            # 基础门槛: survival < 30 直接过滤
            if surv < 30:
                return f"晋级率极低 (survival={surv:.0f})"
            # 高位板递增门槛: 3板要求survival≥35, 4板≥45, 5板+≥55
            height = _infer_height(hm)
            if height >= 5 and surv < 55:
                return f"{height}板晋级率不足 (survival={surv:.0f}<55)"
            if height >= 4 and surv < 45:
                return f"{height}板晋级率不足 (survival={surv:.0f}<45)"
            if height >= 3 and surv < 35:
                return f"{height}板晋级率不足 (survival={surv:.0f}<35)"
            # 高度动量过低 = 累积衰减严重, 不值得参与
            if hm < 15:
                return f"连板动量衰竭 (height_momentum={hm:.0f})"

            # 5b. 赚钱效应联动: 弱市下收紧连板门槛
            pe = ctx.profit_effect
            if pe and pe.regime in (ProfitRegime.WEAK, ProfitRegime.FROZEN):
                min_surv = 45 if height <= 3 else 60
                if surv < min_surv:
                    return (
                        f"弱赚钱效应连板门槛 "
                        f"(survival={surv:.0f}<{min_surv}, regime={pe.regime.value})"
                    )

        return None


def _profit_effect_gate(
    c: ScoredCandidate,
    pe: ProfitEffectSnapshot,
) -> str | None:
    """基于赚钱效应分层数据的门控.

    用实际次日溢价/胜率数据替代经验阈值:
    - 首板层溢价 < -1% 且胜率 < 30% → 首板信号应回避
    - 弱赚钱效应 + 首板中低分 → 过滤
    """
    if c.signal_type == "FIRST_BOARD":
        tier = pe.tier_for_height(1)
        if tier and tier.prev_count >= 5:
            # 首板层数据充足时, 用实际溢价/胜率做硬门控
            if tier.avg_premium < -2.0 and tier.win_rate < 0.35:
                return (
                    f"首板赚钱效应极差 "
                    f"(溢价={tier.avg_premium:+.1f}% 胜率={tier.win_rate:.0%})"
                )

    if c.signal_type == "FOLLOW_BOARD":
        height = _infer_height(c.factors.get("height_momentum", 0))
        tier = pe.tier_for_height(height)
        if tier and tier.prev_count >= 3:
            if tier.avg_premium < -2.0 and tier.win_rate < 0.25 and c.score < 75:
                return (
                    f"{tier.tier}赚钱效应极差 "
                    f"(溢价={tier.avg_premium:+.1f}% 胜率={tier.win_rate:.0%})"
                )

    if c.signal_type == "SECTOR_LEADER":
        height = _infer_height(c.factors.get("height_momentum", 0))
        tier = pe.tier_for_height(height)
        if tier and tier.prev_count >= 3:
            if hasattr(tier, 'broken_rate') and tier.broken_rate > 0.60:
                return (
                    f"空间板炸板率过高 "
                    f"(broken_rate={tier.broken_rate:.0%})"
                )

    # 弱 regime 下的附加门控: 非高分标的应审慎
    if pe.regime == ProfitRegime.WEAK and c.score < 65:
        return f"赚钱效应偏弱 (regime={pe.regime_score:.0f})"

    return None


def _infer_height(height_momentum: float) -> int:
    """从 height_momentum 分数反推大致连板高度.

    用于 stage1 过滤时无法直接拿到 height 的场景.
    height_momentum 越低 → 高度越高 (因为连板衰减).
    """
    # 基于 _score_height_momentum 的静态回退值:
    # 2板~90, 3板~72, 4板~50, 5板~32, 6板+~<20
    if height_momentum >= 80:
        return 2
    if height_momentum >= 60:
        return 3
    if height_momentum >= 40:
        return 4
    if height_momentum >= 25:
        return 5
    return 6
