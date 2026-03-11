"""Per-stock sentiment scoring engine (dynamic-weight).

Combines up to 9 dimensions to assess individual stock "热度" (heat/popularity).
Factors whose backing tables are empty are **excluded** from weighting and their
weight is redistributed proportionally to factors with real data.

Core 5 (always available — backed by kpl_list + daily_bar):
- Volume ratio (量比): today's volume vs recent average
- Seal order strength (封单强度): from KPL lu_limit_order
- Theme heat (题材热度): from event classifier
- Event catalyst (事件催化): from lu_desc classification
- Bid activity (竞价活跃度): from KPL bid_amount (fallback)

Optional 4 (require synced tables):
- Auction quality (竞价质量): from stk_auction (4-dimension composite)
  Replaces simple bid_activity when data available
- Popularity ranking (同花顺人气): from ths_hot
- Northbound signal (北向资金): from hsgt_top10
- Technical form (技术形态): from stk_factor_pro
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import TYPE_CHECKING

from hit_astocker.analyzers.event_classifier import EventClassifier
from hit_astocker.analyzers.technical_form import TechnicalFormAnalyzer
from hit_astocker.models.auction_data import AuctionRecord
from hit_astocker.models.event_data import StockSentimentScore
from hit_astocker.repositories.auction_repo import AuctionRepository
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.repositories.hsgt_repo import HsgtTop10Repository
from hit_astocker.repositories.kpl_repo import KplRepository, split_themes
from hit_astocker.repositories.ths_hot_repo import ThsHotRepository

if TYPE_CHECKING:
    from hit_astocker.models.daily_context import DataCoverage
    from hit_astocker.models.event_data import EventAnalysisResult


# ── Base weights (sum=1.0 when all 8 active) ──────────────────────────
# bid_activity upgraded to 0.12 (from 0.08) — auction quality is critical for 打板
_BASE_WEIGHTS: dict[str, float] = {
    "volume_ratio": 0.14,
    "seal_order": 0.13,
    "bid_activity": 0.12,
    "theme_heat": 0.11,
    "event_catalyst": 0.10,
    "popularity": 0.15,
    "northbound": 0.13,
    "technical_form": 0.12,
}


def _renormalized_weights(active_keys: set[str]) -> dict[str, float]:
    """Return weights renormalized to sum=1 for active factor keys only."""
    raw = {k: v for k, v in _BASE_WEIGHTS.items() if k in active_keys}
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in raw.items()}


class StockSentimentAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._bar_repo = DailyBarRepository(conn)
        self._kpl_repo = KplRepository(conn)
        self._event_classifier = EventClassifier(conn)
        self._ths_hot_repo = ThsHotRepository(conn)
        self._hsgt_repo = HsgtTop10Repository(conn)
        self._technical_analyzer = TechnicalFormAnalyzer(conn)
        self._auction_repo = AuctionRepository(conn)

    def analyze(
        self,
        trade_date: date,
        ts_codes: list[str] | None = None,
        coverage: DataCoverage | None = None,
        event_result: EventAnalysisResult | None = None,
    ) -> list[StockSentimentScore]:
        """Compute per-stock sentiment scores with dynamic factor weighting."""
        # Load KPL data for all limit-up stocks
        kpl_records = self._kpl_repo.find_by_tag(trade_date, tag="涨停")
        kpl_map = {rec.ts_code: rec for rec in kpl_records}

        # Event analysis for theme heat
        if event_result is None:
            event_result = self._event_classifier.analyze(trade_date)
        theme_heat_map = {th.theme_name: th.heat_score for th in event_result.theme_heats}
        event_map = {ev.ts_code: ev for ev in event_result.stock_events}

        # Determine which codes to analyze
        codes = ts_codes if ts_codes else list(kpl_map.keys())

        # Batch load: THS hot rankings
        ths_hot_map = {
            rec.ts_code: rec
            for rec in self._ths_hot_repo.find_records_by_date(trade_date)
        }

        # Batch load: Northbound capital net buyers
        hsgt_net_map = self._hsgt_repo.find_net_buyers_by_date(trade_date)

        # Batch load: Technical form scores (already uses batch internally)
        tech_scores = self._technical_analyzer.analyze(trade_date, codes)
        tech_map = {ts.ts_code: ts for ts in tech_scores}

        # Batch load: Recent daily bars for volume ratio (replaces N+1)
        bars_map = self._bar_repo.find_recent_bars_batch(codes, trade_date, count=6)

        # Batch load: Auction data (stk_auction)
        has_auction = coverage.has_auction if coverage else False
        auction_map: dict[str, AuctionRecord] = {}
        auction_history: dict[str, list[AuctionRecord]] = {}
        theme_auction_pcts: dict[str, list[float]] = {}
        if has_auction:
            auction_map = self._auction_repo.find_by_codes_on_date(codes, trade_date)
            auction_history = self._auction_repo.find_recent_auction_batch(
                codes, trade_date, count=6,
            )
            # Build theme → pct_change list for theme-rank scoring
            theme_auction_pcts = _build_theme_auction_ranks(kpl_map, auction_map)

        # ── Determine active factors ──
        has_ths_hot = coverage.has_ths_hot if coverage else len(ths_hot_map) > 0
        has_hsgt = coverage.has_hsgt if coverage else len(hsgt_net_map) > 0
        has_tech = coverage.has_stk_factor if coverage else len(tech_map) > 0

        active_keys = {"volume_ratio", "seal_order", "bid_activity", "theme_heat", "event_catalyst"}
        if has_ths_hot:
            active_keys.add("popularity")
        if has_hsgt:
            active_keys.add("northbound")
        if has_tech:
            active_keys.add("technical_form")

        weights = _renormalized_weights(active_keys)

        results = []
        for ts_code in codes:
            kpl = kpl_map.get(ts_code)
            event = event_map.get(ts_code)

            # Core factor scores (always computed)
            scores: dict[str, float] = {
                "volume_ratio": self._score_volume_ratio_from_bars(
                    bars_map.get(ts_code, []), trade_date,
                ),
                "seal_order": self._score_seal_order(kpl),
                "bid_activity": _score_auction(
                    auction_map.get(ts_code),
                    auction_history.get(ts_code, []),
                    kpl,
                    theme_auction_pcts,
                    has_auction,
                ),
                "theme_heat": self._score_theme_heat(kpl, theme_heat_map),
                "event_catalyst": self._score_event_catalyst(event),
            }

            # Optional factor scores (only when backing data exists)
            popularity_score = self._score_popularity(ts_code, ths_hot_map) if has_ths_hot else 0.0
            northbound_score = self._score_northbound(ts_code, hsgt_net_map) if has_hsgt else 0.0
            tech_form = tech_map.get(ts_code)
            technical_score = (
                tech_form.composite_score if tech_form else 50.0
            ) if has_tech else 0.0

            if has_ths_hot:
                scores["popularity"] = popularity_score
            if has_hsgt:
                scores["northbound"] = northbound_score
            if has_tech:
                scores["technical_form"] = technical_score

            # Dynamic weighted composite (only active factors contribute)
            composite = sum(weights.get(k, 0) * v for k, v in scores.items())

            name = kpl.name if kpl else ts_code
            results.append(StockSentimentScore(
                ts_code=ts_code,
                name=name,
                volume_ratio_score=round(scores["volume_ratio"], 2),
                seal_order_score=round(scores["seal_order"], 2),
                bid_activity_score=round(scores["bid_activity"], 2),
                theme_heat_score=round(scores["theme_heat"], 2),
                event_catalyst_score=round(scores["event_catalyst"], 2),
                popularity_score=round(popularity_score, 2),
                northbound_score=round(northbound_score, 2),
                technical_form_score=round(technical_score, 2),
                composite_score=round(composite, 2),
                factors={k: round(v, 2) for k, v in scores.items()},
            ))

        return sorted(results, key=lambda s: s.composite_score, reverse=True)

    @staticmethod
    def _score_volume_ratio_from_bars(bars: list, trade_date: date) -> float:
        """Score volume ratio from pre-loaded bar data."""
        if len(bars) < 2:
            return 50.0

        today_bar = bars[-1]
        if today_bar.trade_date != trade_date:
            return 50.0

        prev_bars = bars[:-1]
        if not prev_bars:
            return 50.0

        avg_vol = sum(b.vol for b in prev_bars) / len(prev_bars)
        if avg_vol <= 0:
            return 50.0

        volume_ratio = today_bar.vol / avg_vol

        if volume_ratio >= 4.0:
            return 100.0
        if volume_ratio >= 3.0:
            return 90.0
        if volume_ratio >= 2.0:
            return 75.0
        if volume_ratio >= 1.5:
            return 60.0
        if volume_ratio >= 1.0:
            return 45.0
        return 25.0

    @staticmethod
    def _score_seal_order(kpl) -> float:
        """Score based on lu_limit_order (封单金额)."""
        if not kpl or kpl.lu_limit_order <= 0:
            return 30.0

        order = kpl.lu_limit_order
        if order >= 50000:
            return 100.0
        if order >= 20000:
            return 85.0
        if order >= 10000:
            return 70.0
        if order >= 5000:
            return 55.0
        return 35.0

    @staticmethod
    def _score_theme_heat(kpl, theme_heat_map: dict[str, float]) -> float:
        """Score based on the stock's theme heat."""
        if not kpl or not kpl.theme:
            return 30.0

        themes = split_themes(kpl.theme)
        if not themes:
            return 30.0

        max_heat = max(theme_heat_map.get(t, 30.0) for t in themes)
        return max_heat

    @staticmethod
    def _score_event_catalyst(event) -> float:
        """Score based on event classification weight."""
        if not event:
            return 40.0
        return event.event_weight * 100

    @staticmethod
    def _score_popularity(ts_code: str, ths_hot_map: dict) -> float:
        """Score based on 同花顺热股排名.

        排名越高 = 市场关注度越高 = 打板跟风盘越多.
        Top 10 = 100, Top 20 = 85, Top 50 = 70, Top 100 = 55, 未上榜 = 30
        """
        rec = ths_hot_map.get(ts_code)
        if not rec:
            return 30.0

        rank = rec.rank
        if rank <= 10:
            return 100.0
        if rank <= 20:
            return 85.0
        if rank <= 50:
            return 70.0
        if rank <= 100:
            return 55.0
        return 40.0

    @staticmethod
    def _score_northbound(ts_code: str, hsgt_net_map: dict[str, float]) -> float:
        """Score based on 北向资金净买入.

        北向在十大成交股中 + 净买入 = 聪明钱认可信号.
        净买入>1亿 = 100, >5000万 = 85, >0 = 70, 净卖出 = 30, 未出现 = 45
        """
        net = hsgt_net_map.get(ts_code)
        if net is None:
            return 45.0  # Not in top 10 = neutral

        if net >= 10000:  # > 1亿 (万元)
            return 100.0
        if net >= 5000:  # > 5000万
            return 85.0
        if net > 0:
            return 70.0
        if net > -5000:
            return 35.0
        return 20.0  # Heavy selling


# ── Auction quality scoring (4-dimension composite) ──────────────────

def _score_auction(
    auction: AuctionRecord | None,
    history: list[AuctionRecord],
    kpl,
    theme_auction_pcts: dict[str, list[float]],
    has_auction: bool,
) -> float:
    """Score auction quality from 4 dimensions when stk_auction data available.

    When stk_auction not synced, falls back to KPL bid_amount.

    Sub-dimensions:
      1. 竞价高开幅度 (30%): 涨停股当日竞价 gap → 隔夜需求强度
      2. 竞价成交额   (25%): 绝对金额 → 机构参与度
      3. 竞价量比     (25%): 相对历史竞价量 → 异常关注信号
      4. 题材内分位   (20%): 同题材涨停股中竞价排名 → 辨识度
    """
    if not has_auction or auction is None:
        # Fallback: KPL bid_amount (backward compat)
        return _score_bid_activity_kpl(kpl)

    gap = _score_auction_gap(auction.pct_change)
    amount = _score_auction_amount(auction.amount)
    vol_ratio = _score_auction_vol_ratio(auction, history)
    theme_rank = _score_auction_theme_rank(auction, kpl, theme_auction_pcts)

    return round(gap * 0.30 + amount * 0.25 + vol_ratio * 0.25 + theme_rank * 0.20, 2)


def _score_bid_activity_kpl(kpl) -> float:
    """Original KPL-based bid activity (fallback when no stk_auction)."""
    if not kpl or kpl.bid_amount <= 0:
        return 30.0
    bid = kpl.bid_amount
    if bid >= 10000:
        return 100.0
    if bid >= 5000:
        return 80.0
    if bid >= 2000:
        return 60.0
    if bid >= 1000:
        return 45.0
    return 30.0


def _score_auction_gap(pct_change: float) -> float:
    """竞价高开幅度: 涨停股当日开盘 gap 反映隔夜资金承接强度.

    对打板股:
      低开(<-1%) → 弱: 隔夜资金不认可, 承接差
      平开(-1%~+1%) → 中性: 基础承接
      小高开(+1%~+3%) → 强: 需求旺盛, 理想状态
      高开(+3%~+5%) → 很强: 强势竞价, 但追高风险升
      大幅高开(>+5%) → 过热: 溢价过高, 日内回落概率增
    """
    if pct_change < -3.0:
        return 10.0
    if pct_change < -1.0:
        return 30.0
    if pct_change < 1.0:
        return 50.0
    if pct_change < 3.0:
        return 80.0
    if pct_change < 5.0:
        return 70.0
    return 55.0  # 大幅高开过热, 打板反而不利


def _score_auction_amount(amount: float) -> float:
    """竞价成交额 (万元): 绝对金额反映机构参与和流动性."""
    if amount >= 20000:
        return 100.0
    if amount >= 10000:
        return 90.0
    if amount >= 5000:
        return 75.0
    if amount >= 2000:
        return 60.0
    if amount >= 1000:
        return 45.0
    return 30.0


def _score_auction_vol_ratio(
    today: AuctionRecord,
    history: list[AuctionRecord],
) -> float:
    """竞价量比: 今日竞价量 / 近 N 日均竞价量.

    异常放量竞价 = 资金集中抢筹信号.
    """
    if not history or today.vol <= 0:
        return 50.0  # 无历史 → 中性

    # Exclude today from history (history includes today as last element)
    prev = [r for r in history if r.trade_date < today.trade_date]
    if not prev:
        return 50.0

    avg_vol = sum(r.vol for r in prev) / len(prev)
    if avg_vol <= 0:
        return 50.0

    ratio = today.vol / avg_vol
    if ratio >= 4.0:
        return 100.0
    if ratio >= 3.0:
        return 90.0
    if ratio >= 2.0:
        return 75.0
    if ratio >= 1.5:
        return 60.0
    if ratio >= 1.0:
        return 45.0
    return 25.0


def _score_auction_theme_rank(
    auction: AuctionRecord,
    kpl,
    theme_auction_pcts: dict[str, list[float]],
) -> float:
    """题材内竞价分位: 同题材涨停股中, 本股竞价高开的百分位排名.

    龙头股在竞价阶段就会展现辨识度 (高开幅度领先同题材).
    Top 20% → 100, Top 40% → 75, Top 60% → 55, Bottom 40% → 35
    """
    if not kpl or not kpl.theme:
        return 50.0  # 无题材信息 → 中性

    themes = split_themes(kpl.theme)
    if not themes:
        return 50.0

    # Use the best rank across all themes
    best_percentile = 0.5  # default: median
    for theme in themes:
        pcts = theme_auction_pcts.get(theme)
        if not pcts or len(pcts) < 2:
            continue
        # Count how many stocks have lower pct_change
        below = sum(1 for p in pcts if p < auction.pct_change)
        percentile = below / len(pcts)  # 0=worst, 1=best
        best_percentile = max(best_percentile, percentile)

    if best_percentile >= 0.80:
        return 100.0
    if best_percentile >= 0.60:
        return 75.0
    if best_percentile >= 0.40:
        return 55.0
    return 35.0


def _build_theme_auction_ranks(
    kpl_map: dict, auction_map: dict[str, AuctionRecord],
) -> dict[str, list[float]]:
    """Build theme → [pct_change values] mapping for theme-rank scoring.

    Groups all limit-up stocks by their themes, collecting each stock's
    auction pct_change for intra-theme percentile ranking.
    """
    result: dict[str, list[float]] = {}
    for ts_code, kpl in kpl_map.items():
        if not kpl.theme:
            continue
        auction = auction_map.get(ts_code)
        if auction is None:
            continue
        for theme in split_themes(kpl.theme):
            if theme not in result:
                result[theme] = []
            result[theme].append(auction.pct_change)
    return result
