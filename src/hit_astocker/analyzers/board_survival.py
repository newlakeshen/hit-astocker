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
        """
        end_str = end_date.strftime(TUSHARE_DATE_FMT)
        start_date = date(end_date.year - lookback_years, end_date.month, end_date.day)
        start_str = start_date.strftime(TUSHARE_DATE_FMT)

        # Get all trading dates with limit_step data
        dates_sql = """
            SELECT DISTINCT trade_date FROM limit_step
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """
        date_rows = self._conn.execute(dates_sql, (start_str, end_str)).fetchall()
        trading_dates = [r["trade_date"] for r in date_rows]

        if len(trading_dates) < 2:
            return SurvivalModel(
                stats=(), overall_survival_rate=0.0,
                data_start_date=start_str, data_end_date=end_str, total_samples=0,
            )

        # Build date-pair adjacency: for each consecutive trading day pair,
        # count stocks at height N on day[i] that appear at height N+1 on day[i+1]
        height_survival: dict[int, tuple[int, int]] = {}  # height -> (total, survived)

        for i in range(len(trading_dates) - 1):
            today = trading_dates[i]
            tomorrow = trading_dates[i + 1]

            # Get stocks at each height today
            today_sql = "SELECT ts_code, nums FROM limit_step WHERE trade_date = ?"
            today_rows = self._conn.execute(today_sql, (today,)).fetchall()

            # Get stocks at each height tomorrow
            tomorrow_sql = "SELECT ts_code, nums FROM limit_step WHERE trade_date = ?"
            tomorrow_rows = self._conn.execute(tomorrow_sql, (tomorrow,)).fetchall()
            tomorrow_map = {r["ts_code"]: r["nums"] for r in tomorrow_rows}

            for row in today_rows:
                h = row["nums"]
                code = row["ts_code"]
                total, survived = height_survival.get(h, (0, 0))
                total += 1
                # Check if this stock survived to h+1 tomorrow
                next_h = tomorrow_map.get(code, 0)
                if next_h == h + 1:
                    survived += 1
                height_survival[h] = (total, survived)

        # Build stats
        stats = []
        total_all = 0
        survived_all = 0
        for h in sorted(height_survival.keys()):
            total, survived = height_survival[h]
            rate = survived / max(total, 1)
            total_all += total
            survived_all += survived
            stats.append(BoardSurvivalStats(
                height=h,
                total_count=total,
                survived_count=survived,
                survival_rate=round(rate, 4),
                avg_pct_chg_next=0.0,  # Would need daily_bar data to compute
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
