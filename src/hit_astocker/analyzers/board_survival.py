"""连板生存率分析器.

Uses historical limit_step data to compute survival rates at each board height.
P(height N+1 | height N) based on all available history (up to 10 years).
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from hit_astocker.config.constants import TUSHARE_DATE_FMT


@dataclass(frozen=True)
class BoardSurvivalStats:
    """各高度连板生存率统计."""

    height: int  # 当前高度 N
    total_count: int  # 历史上达到高度N的总次数
    survived_count: int  # 其中晋级到N+1的次数
    survival_rate: float  # 晋级概率 P(N+1 | N)
    avg_pct_chg_next: float  # 晋级次日平均涨幅


@dataclass(frozen=True)
class SurvivalModel:
    """连板生存率模型."""

    stats: tuple[BoardSurvivalStats, ...]  # 各高度统计
    overall_survival_rate: float  # 全局平均晋级率
    data_start_date: str  # 数据起始日期
    data_end_date: str  # 数据截止日期
    total_samples: int  # 总样本数


class BoardSurvivalAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def compute_model(self, end_date: date, lookback_years: int = 10) -> SurvivalModel:
        """Compute survival rates from historical data.

        Uses all limit_step data up to end_date, going back lookback_years.
        Optimized: single SQL query with CTE replaces ~5000 per-day queries.
        Thread-safe: no temp tables or DDL, pure read-only query.
        """
        end_str = end_date.strftime(TUSHARE_DATE_FMT)
        # Safe leap-year handling: clamp to last day of month
        start_year = end_date.year - lookback_years
        try:
            start_date = date(start_year, end_date.month, end_date.day)
        except ValueError:
            # Feb 29 in non-leap year → use Feb 28
            start_date = date(start_year, end_date.month, 28)
        start_str = start_date.strftime(TUSHARE_DATE_FMT)

        # Single CTE-based query: build consecutive date pairs inline,
        # then join limit_step to itself across adjacent trading days.
        survival_sql = """
            WITH trading_dates AS (
                SELECT DISTINCT trade_date,
                       LEAD(trade_date) OVER (ORDER BY trade_date) AS next_date
                FROM limit_step
                WHERE trade_date >= ? AND trade_date <= ?
            )
            SELECT
                a.nums AS height,
                COUNT(*) AS total_count,
                SUM(CASE WHEN b.nums = a.nums + 1 THEN 1 ELSE 0 END) AS survived_count
            FROM limit_step a
            INNER JOIN trading_dates td ON a.trade_date = td.trade_date
            LEFT JOIN limit_step b
                ON a.ts_code = b.ts_code AND b.trade_date = td.next_date
            WHERE td.next_date IS NOT NULL
            GROUP BY a.nums
            ORDER BY a.nums
        """
        rows = self._conn.execute(survival_sql, (start_str, end_str)).fetchall()

        if not rows:
            return SurvivalModel(
                stats=(), overall_survival_rate=0.0,
                data_start_date=start_str, data_end_date=end_str, total_samples=0,
            )

        # Build stats
        stats = []
        total_all = 0
        survived_all = 0
        for row in rows:
            h = row["height"]
            total = row["total_count"]
            survived = row["survived_count"]
            rate = survived / max(total, 1)
            total_all += total
            survived_all += survived
            stats.append(BoardSurvivalStats(
                height=h,
                total_count=total,
                survived_count=survived,
                survival_rate=round(rate, 4),
                avg_pct_chg_next=0.0,
            ))

        overall = survived_all / max(total_all, 1)

        return SurvivalModel(
            stats=tuple(stats),
            overall_survival_rate=round(overall, 4),
            data_start_date=start_str,
            data_end_date=end_str,
            total_samples=total_all,
        )

    def get_survival_rate(self, end_date: date, height: int, lookback_years: int = 10) -> float:
        """Get survival rate for a specific board height. Cached-friendly single query."""
        end_str = end_date.strftime(TUSHARE_DATE_FMT)
        start_date = date(end_date.year - lookback_years, end_date.month, end_date.day)
        start_str = start_date.strftime(TUSHARE_DATE_FMT)

        # Count stocks at this height across all dates in range
        sql = """
            SELECT COUNT(*) as total FROM limit_step
            WHERE trade_date >= ? AND trade_date <= ? AND nums = ?
        """
        total_row = self._conn.execute(sql, (start_str, end_str, height)).fetchone()
        total = total_row[0] if total_row else 0

        if total == 0:
            return 0.0

        # Count those that survived to height+1 the next trading day
        # This requires joining consecutive dates
        survived_sql = """
            SELECT COUNT(*) as survived
            FROM limit_step a
            INNER JOIN limit_step b
                ON a.ts_code = b.ts_code
                AND b.nums = a.nums + 1
                AND b.trade_date = (
                    SELECT MIN(trade_date) FROM limit_step
                    WHERE trade_date > a.trade_date AND trade_date <= ?
                )
            WHERE a.trade_date >= ? AND a.trade_date <= ? AND a.nums = ?
        """
        survived_row = self._conn.execute(
            survived_sql, (end_str, start_str, end_str, height)
        ).fetchone()
        survived = survived_row[0] if survived_row else 0

        return round(survived / max(total, 1), 4)

    def score_position(self, height: int, model: SurvivalModel) -> float:
        """Convert survival rate at given height to a 0-100 score for composite scoring.

        Higher survival rate = higher score (more favorable position).
        First board (height=1) uses the 1→2 survival rate.
        """
        target_height = max(height, 1)
        for stat in model.stats:
            if stat.height == target_height:
                # Scale: survival rate 0.5+ = 80+, 0.3-0.5 = 50-80, <0.3 = 20-50
                rate = stat.survival_rate
                if rate >= 0.5:
                    return 80.0 + (rate - 0.5) / 0.5 * 20.0
                if rate >= 0.3:
                    return 50.0 + (rate - 0.3) / 0.2 * 30.0
                return 20.0 + rate / 0.3 * 30.0

        # No data for this height: use conservative default
        return 40.0
