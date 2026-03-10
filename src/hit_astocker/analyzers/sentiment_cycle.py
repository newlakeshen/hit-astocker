"""Sentiment cycle detector — multi-day trend analysis.

Runs lightweight sentiment scoring for recent 5 trading days to determine
the current phase of the A-share 打板 emotion cycle.  The core insight:
same absolute score with different *direction* means different strategy.

Uses only limit_list_d / limit_step / daily_bar — data that is always
available when the user has synced even once.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.sentiment_cycle import CYCLE_PHASE_LABELS, CyclePhase, SentimentCycle
from hit_astocker.repositories.limit_repo import LimitListRepository
from hit_astocker.repositories.limit_step_repo import LimitStepRepository
from hit_astocker.utils.date_utils import get_recent_trading_days


@dataclass
class _DayMetrics:
    """Lightweight per-day metrics for cycle detection."""

    score: float          # simplified sentiment score (0-100)
    broken_rate: float    # 炸板率 (0-1)
    premium: float        # placeholder (filled when available)
    max_height: int       # 最高连板高度


class SentimentCycleDetector:
    """Detect current emotion-cycle phase from multi-day data."""

    def __init__(self, conn: sqlite3.Connection):
        self._limit_repo = LimitListRepository(conn)
        self._step_repo = LimitStepRepository(conn)

    def detect(self, trade_date: date, current: SentimentScore) -> SentimentCycle:
        """Detect cycle phase using today's full score + recent lightweight metrics."""
        recent_days = get_recent_trading_days(trade_date, 4)  # T-1 … T-4

        # Collect metrics: today (index 0) + 4 historical days
        history: list[_DayMetrics] = []
        for d in recent_days:
            history.append(self._compute_light_metrics(d))

        # Build score / premium / broken_rate series (newest first)
        scores = [current.overall_score] + [m.score for m in history]
        premiums = [current.prev_limit_up_premium] + [m.premium for m in history]
        broken_rates = [current.broken_rate] + [m.broken_rate for m in history]

        n = len(scores)

        # ── Moving averages ──
        ma3 = sum(scores[:min(3, n)]) / min(3, n)
        ma5 = sum(scores[:min(5, n)]) / min(5, n)

        # ── First & second derivative ──
        delta = scores[0] - scores[1] if n >= 2 else 0.0
        prev_delta = scores[1] - scores[2] if n >= 3 else 0.0
        accel = delta - prev_delta

        # ── Premium trend (3-day linear slope) ──
        premium_trend = _simple_slope(premiums[:min(3, n)])

        # ── Broken-rate trend (3-day linear slope, positive = worsening) ──
        broken_rate_trend = _simple_slope(broken_rates[:min(3, n)])

        # ── Phase determination ──
        phase = self._determine_phase(
            current=scores[0],
            delta=delta,
            accel=accel,
            ma3=ma3,
            broken_rate=broken_rates[0],
            broken_rate_trend=broken_rate_trend,
            premium_trend=premium_trend,
            premium=premiums[0],
        )

        # ── Turning point detection ──
        prev_phase = self._determine_phase(
            current=scores[1] if n >= 2 else scores[0],
            delta=prev_delta,
            accel=0.0,
            ma3=sum(scores[1:min(4, n)]) / min(3, max(1, n - 1)) if n >= 2 else scores[0],
            broken_rate=broken_rates[1] if n >= 2 else broken_rates[0],
            broken_rate_trend=0.0,
            premium_trend=0.0,
            premium=premiums[1] if n >= 2 else premiums[0],
        ) if n >= 2 else phase

        is_turning = phase != prev_phase and phase in (
            CyclePhase.REPAIR, CyclePhase.RETREAT, CyclePhase.DIVERGE,
        )

        desc = self._build_description(phase, delta, premium_trend, broken_rate_trend)

        return SentimentCycle(
            phase=phase,
            score_ma3=round(ma3, 2),
            score_ma5=round(ma5, 2),
            score_delta=round(delta, 2),
            score_accel=round(accel, 2),
            premium_trend=round(premium_trend, 2),
            broken_rate_trend=round(broken_rate_trend, 4),
            recent_scores=tuple(round(s, 2) for s in scores),
            recent_premiums=tuple(round(p, 2) for p in premiums),
            recent_broken_rates=tuple(round(b, 4) for b in broken_rates),
            is_turning_point=is_turning,
            phase_description=desc,
        )

    # ── Lightweight metrics (no auction, no market context) ──────────

    def _compute_light_metrics(self, trade_date: date) -> _DayMetrics:
        """Compute core metrics from always-available data (limit + step)."""
        counts = self._limit_repo.count_by_type(trade_date)
        up = counts.get("U", 0)
        down = counts.get("D", 0)
        broken = counts.get("Z", 0)

        up_down_ratio = up / max(down, 1)
        broken_rate = broken / max(up + broken, 1)

        max_height = self._step_repo.get_max_height(trade_date)

        # Recovery rate
        recovery, stayed = self._limit_repo.count_recovery(trade_date)
        recovery_rate = recovery / max(recovery + stayed, 1)

        # Simplified composite — mirrors the top 3 most informative factors
        f_ratio = min(up_down_ratio / 5.0 * 100, 100)
        f_broken = recovery_rate * 60 + (1 - broken_rate) * 40
        f_height = min(max_height / 7 * 100, 100)

        score = f_ratio * 0.35 + f_broken * 0.40 + f_height * 0.25

        # Premium: compute if previous day exists
        premium = self._compute_light_premium(trade_date)

        return _DayMetrics(
            score=round(score, 2),
            broken_rate=round(broken_rate, 4),
            premium=round(premium, 2),
            max_height=max_height,
        )

    @staticmethod
    def _compute_light_premium(_trade_date: date) -> float:
        """Return 0.0 — premium for historical days is not computed here.

        Today's premium comes from SentimentScore.prev_limit_up_premium
        (passed via `current` parameter).  Historical premiums are left as 0
        to avoid adding a DailyBarRepository dependency; the trend slope is
        therefore driven primarily by today's value vs zeros.
        """
        return 0.0

    # ── Phase determination logic ────────────────────────────────────

    @staticmethod
    def _determine_phase(
        *,
        current: float,
        delta: float,
        accel: float,
        ma3: float,
        broken_rate: float,
        broken_rate_trend: float,
        premium_trend: float,
        premium: float,
    ) -> CyclePhase:
        """Determine emotion cycle phase from quantitative signals.

        Priority order handles ambiguous cases (e.g., score=50 but falling).
        """
        # ── ICE: clearly terrible sentiment ──
        if current < 25 or (current < 35 and broken_rate > 0.5):
            return CyclePhase.ICE

        # ── RETREAT: falling into danger zone ──
        if current < 40 and delta < -3:
            return CyclePhase.RETREAT

        # ── REPAIR: rising from low base ──
        if current < 50 and delta > 3 and ma3 < 45:
            return CyclePhase.REPAIR

        # ── CLIMAX: high score, stable or rising ──
        if current >= 70 and delta >= -5:
            return CyclePhase.CLIMAX

        # ── DIVERGE: score dropping from elevated level ──
        if current >= 45 and delta < -5:
            return CyclePhase.DIVERGE

        # ── DIVERGE: broken rate worsening while score still OK ──
        if current >= 50 and broken_rate_trend > 0.05 and delta < 0:
            return CyclePhase.DIVERGE

        # ── DIVERGE: moderate decline in mid-range (blind spot for -3 to -5) ──
        if 45 <= current < 55 and delta < -3:
            return CyclePhase.DIVERGE

        # ── FERMENT: rising toward high level ──
        if delta > 0 and current >= 45:
            return CyclePhase.FERMENT

        # ── Fallback by absolute level ──
        if current >= 65:
            return CyclePhase.CLIMAX
        if current >= 45:
            return CyclePhase.FERMENT
        if current >= 30:
            if delta > 0:
                return CyclePhase.REPAIR
            return CyclePhase.RETREAT
        return CyclePhase.ICE

    @staticmethod
    def _build_description(
        phase: CyclePhase,
        delta: float,
        premium_trend: float,
        broken_rate_trend: float,
    ) -> str:
        """Build human-readable phase description."""
        parts = []
        parts.append(f"周期: {CYCLE_PHASE_LABELS.get(phase.value, phase.value)}")

        if delta > 5:
            parts.append("情绪快速回暖")
        elif delta > 0:
            parts.append("情绪小幅改善")
        elif delta < -5:
            parts.append("情绪快速恶化")
        elif delta < 0:
            parts.append("情绪小幅走弱")
        else:
            parts.append("情绪持平")

        if premium_trend > 1.0:
            parts.append("溢价回升")
        elif premium_trend < -1.0:
            parts.append("溢价走弱")

        if broken_rate_trend > 0.05:
            parts.append("炸板率上升")
        elif broken_rate_trend < -0.05:
            parts.append("炸板率下降")

        return " | ".join(parts)


def _simple_slope(values: list[float]) -> float:
    """Compute simple linear slope of a time series (newest first).

    Positive = increasing over time (values[0] > values[-1]).
    """
    n = len(values)
    if n < 2:
        return 0.0
    # values[0] is newest, values[-1] is oldest
    return (values[0] - values[-1]) / (n - 1)
