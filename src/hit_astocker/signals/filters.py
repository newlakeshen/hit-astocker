"""Pre-filters for candidate stocks."""

from hit_astocker.models.limit_data import LimitRecord
from hit_astocker.utils.stock_filter import should_exclude


def filter_candidates(
    records: list[LimitRecord],
    max_total_mv: float = 0,
) -> list[LimitRecord]:
    """Filter out ST, BJ, and optionally mega-cap stocks."""
    return [
        r for r in records
        if not should_exclude(r.ts_code, r.name, max_total_mv, r.total_mv)
    ]
