"""Feature builder — converts factor dicts to fixed-length feature vectors for ML.

Produces a consistent feature representation across all signal types,
handling missing factors and adding context features (cycle phase, signal type).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hit_astocker.models.sentiment_cycle import CyclePhase

if TYPE_CHECKING:
    from hit_astocker.models.daily_context import DataCoverage
    from hit_astocker.models.sentiment_cycle import SentimentCycle
    from hit_astocker.signals.composite_scorer import ScoredCandidate

# ── Factor features (0-100 scale, shared + type-specific) ──
FACTOR_COLUMNS: tuple[str, ...] = (
    # Common (all signal types)
    "sentiment",
    "sector",
    "capital_flow",
    "dragon_tiger",
    "event_catalyst",
    "stock_sentiment",
    "northbound",
    "technical_form",
    "auction_quality",
    # FIRST_BOARD specific
    "seal_quality",
    # FOLLOW_BOARD specific
    "survival",
    "height_momentum",
    # SECTOR_LEADER specific
    "theme_heat",
    "leader_position",
)

# ── Context features ──
CONTEXT_COLUMNS: tuple[str, ...] = (
    "cycle_phase",            # ordinal 0-5
    "sig_first_board",        # one-hot
    "sig_follow_board",
    "sig_sector_leader",
    "has_northbound_data",    # data availability
    "has_technical_data",
    "has_auction_data",
)

ALL_COLUMNS: tuple[str, ...] = FACTOR_COLUMNS + CONTEXT_COLUMNS

# Ordinal encoding for cycle phase (higher = more dangerous)
_PHASE_ORD: dict[CyclePhase, float] = {
    CyclePhase.ICE: 0.0,
    CyclePhase.REPAIR: 1.0,
    CyclePhase.FERMENT: 2.0,
    CyclePhase.CLIMAX: 3.0,
    CyclePhase.DIVERGE: 4.0,
    CyclePhase.RETREAT: 5.0,
}


def build_feature_vector(
    factors: dict[str, float],
    signal_type: str,
    cycle: SentimentCycle | None = None,
    coverage: DataCoverage | None = None,
) -> list[float]:
    """Convert factor dict + context to fixed-length feature vector.

    Parameters
    ----------
    factors : factor scores from ScoredCandidate.factors (only non-None values)
    signal_type : FIRST_BOARD / FOLLOW_BOARD / SECTOR_LEADER
    cycle : current sentiment cycle (for phase encoding)
    coverage : data coverage flags

    Returns
    -------
    list[float] : feature vector of length len(ALL_COLUMNS)
    """
    vec: list[float] = []

    # Factor features: use 0.0 for missing (type-specific factors not in this type)
    for col in FACTOR_COLUMNS:
        vec.append(factors.get(col, 0.0))

    # Context features
    vec.append(_PHASE_ORD.get(cycle.phase, 2.0) if cycle else 2.0)
    vec.append(1.0 if signal_type == "FIRST_BOARD" else 0.0)
    vec.append(1.0 if signal_type == "FOLLOW_BOARD" else 0.0)
    vec.append(1.0 if signal_type == "SECTOR_LEADER" else 0.0)
    vec.append(1.0 if coverage and coverage.has_hsgt else 0.0)
    vec.append(1.0 if coverage and coverage.has_stk_factor else 0.0)
    vec.append(1.0 if coverage and coverage.has_auction else 0.0)

    return vec


def build_feature_matrix(
    candidates: list[ScoredCandidate],
    cycle: SentimentCycle | None = None,
    coverage: DataCoverage | None = None,
) -> list[list[float]]:
    """Build feature matrix for a batch of candidates."""
    return [
        build_feature_vector(c.factors, c.signal_type, cycle, coverage)
        for c in candidates
    ]
