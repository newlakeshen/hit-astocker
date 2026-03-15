"""Repository for hot money (游资) data — hm_list + hm_detail.

Key queries:
- Trader profiles with historical win rate / T+1 premium
- Per-stock seat scores for composite scoring
- Coordination detection (multi-trader on same stock)
"""

import sqlite3
from collections import defaultdict
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.hm_data import HmDetailRecord, SeatScore, TraderProfile
from hit_astocker.repositories.base import BaseRepository
from hit_astocker.utils.date_utils import get_recent_trading_days


class HmRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "hm_detail")
        self._has_data_cache: bool | None = None
        self._profiles_cache: dict[date, dict[str, TraderProfile]] = {}

    # ── basic queries ────────────────────────────────────────────────────

    def has_data(self) -> bool:
        """Check if hm_detail has any data at all (cached)."""
        if self._has_data_cache is not None:
            return self._has_data_cache
        try:
            row = self._conn.execute("SELECT 1 FROM hm_detail LIMIT 1").fetchone()
            self._has_data_cache = row is not None
        except Exception:
            self._has_data_cache = False
        return self._has_data_cache

    def find_details_by_date(self, trade_date: date) -> list[HmDetailRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT * FROM hm_detail WHERE trade_date = ?"
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return [self._to_model(r) for r in rows]

    # ── trader profiles (historical win rate) ────────────────────────────

    def compute_trader_profiles(
        self,
        trade_date: date,
        lookback_days: int = 60,
    ) -> dict[str, TraderProfile]:
        """Compute win rate + avg T+1 premium for all active traders.

        Uses hm_detail (net_amount > 0 = buy) joined with daily_bar
        LEAD() window to get next-day pct_chg.

        Performance: daily_bar scan is limited to ts_codes from hm_detail
        only (was scanning entire table before). Also cached across days
        since 60-day lookback has 98% overlap between adjacent days.

        Returns {hm_name: TraderProfile}.
        """
        # Cache: exact date match only. Approximate caching (days_diff<=30)
        # was incorrect for backtest/train which reuse the same repo instance
        # across multiple dates — profiles must be recomputed per date.
        if trade_date in self._profiles_cache:
            return self._profiles_cache[trade_date]

        recent_dates = get_recent_trading_days(trade_date, lookback_days)
        if not recent_dates:
            return {}

        start_str = recent_dates[-1].strftime(TUSHARE_DATE_FMT)
        end_str = trade_date.strftime(TUSHARE_DATE_FMT)

        # Optimized: limit daily_bar scan to only ts_codes that appear in
        # hm_detail, instead of scanning ALL stocks. This reduces the LEAD()
        # window from millions of rows to thousands.
        sql = """
            WITH trader_buys AS (
                SELECT hm_name, ts_code, trade_date
                FROM hm_detail
                WHERE trade_date >= ? AND trade_date <= ?
                  AND net_amount > 0
            ),
            relevant_codes AS (
                SELECT DISTINCT ts_code FROM trader_buys
            ),
            daily_with_next AS (
                SELECT
                    d.ts_code,
                    d.trade_date,
                    LEAD(d.pct_chg) OVER (
                        PARTITION BY d.ts_code ORDER BY d.trade_date
                    ) AS next_pct
                FROM daily_bar d
                INNER JOIN relevant_codes rc ON d.ts_code = rc.ts_code
                WHERE d.trade_date >= ?
            )
            SELECT
                tb.hm_name,
                COUNT(*) AS total_buys,
                SUM(CASE WHEN dwn.next_pct > 0 THEN 1 ELSE 0 END) AS wins,
                AVG(dwn.next_pct) AS avg_premium,
                COUNT(DISTINCT tb.trade_date) AS active_days
            FROM trader_buys tb
            LEFT JOIN daily_with_next dwn
                ON dwn.ts_code = tb.ts_code AND dwn.trade_date = tb.trade_date
            GROUP BY tb.hm_name
        """
        rows = self._conn.execute(sql, (start_str, end_str, start_str)).fetchall()

        profiles: dict[str, TraderProfile] = {}
        for r in rows:
            total = r["total_buys"] or 0
            wins = r["wins"] or 0
            profiles[r["hm_name"]] = TraderProfile(
                hm_name=r["hm_name"],
                total_buys=total,
                win_count=wins,
                win_rate=wins / max(total, 1),
                avg_premium=r["avg_premium"] or 0.0,
                active_days=r["active_days"] or 0,
            )

        self._profiles_cache[trade_date] = profiles
        return profiles

    # ── per-stock seat scores ────────────────────────────────────────────

    def compute_seat_scores(
        self,
        trade_date: date,
        profiles: dict[str, TraderProfile] | None = None,
    ) -> dict[str, SeatScore]:
        """Compute SeatScore for each stock appearing in hm_detail today.

        Parameters
        ----------
        trade_date : date
        profiles : pre-computed trader profiles (optional, avoids re-query)

        Returns {ts_code: SeatScore}.
        """
        if profiles is None:
            profiles = self.compute_trader_profiles(trade_date)

        details = self.find_details_by_date(trade_date)
        if not details:
            return {}

        # Load tags for today's traders
        tag_map = self._load_tags_by_date(trade_date)

        # Group by stock
        stock_traders: dict[str, list[HmDetailRecord]] = defaultdict(list)
        for d in details:
            stock_traders[d.ts_code].append(d)

        result: dict[str, SeatScore] = {}
        for ts_code, trades in stock_traders.items():
            # Only count traders that appear in profiles (known traders)
            buyer_profiles: list[TraderProfile] = []
            buyer_names: list[str] = []
            total_net = 0.0
            primary_tag = ""
            best_win_rate = 0.0

            for t in trades:
                total_net += t.net_amount
                prof = profiles.get(t.hm_name)
                if prof is None:
                    # Unknown trader (new / not enough history) — still count
                    buyer_names.append(t.hm_name)
                    continue
                buyer_names.append(t.hm_name)
                if t.net_amount > 0:
                    buyer_profiles.append(prof)
                if prof.win_rate > best_win_rate:
                    best_win_rate = prof.win_rate
                    primary_tag = tag_map.get(t.hm_name, t.tag or "")

            if not buyer_names:
                continue

            win_rates = [p.win_rate for p in buyer_profiles] if buyer_profiles else [0.0]
            premiums = [p.avg_premium for p in buyer_profiles] if buyer_profiles else [0.0]
            buy_count = sum(1 for t in trades if t.net_amount > 0)

            result[ts_code] = SeatScore(
                known_trader_count=len(buyer_names),
                known_trader_names=tuple(buyer_names),
                known_net_amount=total_net,
                max_win_rate=max(win_rates),
                avg_win_rate=sum(win_rates) / len(win_rates),
                is_coordinated=buy_count >= 2,
                primary_tag=primary_tag,
                avg_premium=sum(premiums) / len(premiums),
            )

        return result

    # ── internal helpers ─────────────────────────────────────────────────

    def _load_tags_by_date(self, trade_date: date) -> dict[str, str]:
        """Load hm_name -> tag mapping for a date."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT DISTINCT hm_name, tag FROM hm_detail WHERE trade_date = ? AND tag != ''"
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["hm_name"]: r["tag"] for r in rows}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> HmDetailRecord:
        return HmDetailRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            ts_name=row["ts_name"] or "",
            buy_amount=row["buy_amount"] or 0.0,
            sell_amount=row["sell_amount"] or 0.0,
            net_amount=row["net_amount"] or 0.0,
            hm_name=row["hm_name"] or "",
            hm_orgs=row["hm_orgs"] or "",
            tag=row["tag"] or "",
        )
