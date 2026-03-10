"""Event-driven classification engine.

Parses lu_desc (涨停原因) from KPL data to classify limit-up events,
track theme persistence, and compute event-driven scores.
"""

import sqlite3
from datetime import date

from hit_astocker.models.event_data import (
    EVENT_KEYWORDS,
    EVENT_WEIGHTS,
    EventAnalysisResult,
    EventType,
    StockEvent,
    ThemeHeat,
)
from hit_astocker.repositories.kpl_repo import KplRepository
from hit_astocker.utils.date_utils import get_previous_trading_day, get_recent_trading_days


class EventClassifier:
    def __init__(self, conn: sqlite3.Connection):
        self._kpl_repo = KplRepository(conn)

    def analyze(self, trade_date: date) -> EventAnalysisResult:
        """Full event-driven analysis for a trading day."""
        records = self._kpl_repo.find_by_tag(trade_date, tag="涨停")

        # 1. Classify each stock's limit-up event
        stock_events = []
        for rec in records:
            event = self._classify_stock(rec)
            stock_events.append(event)

        # 2. Event type distribution
        distribution: dict[str, int] = {}
        for ev in stock_events:
            distribution[ev.event_type] = distribution.get(ev.event_type, 0) + 1

        dominant = max(distribution, key=distribution.get) if distribution else EventType.UNKNOWN

        # 3. Theme heat tracking
        theme_heats = self._compute_theme_heats(trade_date, records)

        # 4. Theme concentration
        total_stocks = len(stock_events)
        if total_stocks > 0 and theme_heats:
            top3_count = sum(th.today_count for th in theme_heats[:3])
            concentration = min(top3_count / total_stocks, 1.0)
        else:
            concentration = 0.0

        # 5. Market narrative
        narrative = self._build_narrative(dominant, distribution, theme_heats)

        return EventAnalysisResult(
            trade_date=trade_date,
            stock_events=tuple(stock_events),
            theme_heats=tuple(theme_heats),
            event_distribution=distribution,
            dominant_event_type=dominant,
            theme_concentration=round(concentration, 4),
            market_narrative=narrative,
        )

    def get_stock_event(self, ts_code: str, trade_date: date) -> StockEvent | None:
        """Get event classification for a single stock."""
        records = self._kpl_repo.find_by_tag(trade_date, tag="涨停")
        for rec in records:
            if rec.ts_code == ts_code:
                return self._classify_stock(rec)
        return None

    @staticmethod
    def _classify_stock(rec) -> StockEvent:
        """Classify a single stock's limit-up event from lu_desc."""
        lu_desc = rec.lu_desc or ""
        matched_types: list[str] = []

        for keyword, event_type in EVENT_KEYWORDS.items():
            if keyword in lu_desc and event_type not in matched_types:
                matched_types.append(event_type)

        if not matched_types:
            matched_types = [EventType.UNKNOWN]

        # Primary type: highest weight among matched types
        primary = max(matched_types, key=lambda t: EVENT_WEIGHTS.get(t, 0.0))
        weight = EVENT_WEIGHTS.get(primary, 0.4)

        # Parse themes
        theme_raw = rec.theme or ""
        themes = tuple(t.strip() for t in theme_raw.split("+") if t.strip())

        return StockEvent(
            ts_code=rec.ts_code,
            name=rec.name,
            lu_desc=lu_desc,
            event_type=primary,
            event_types=tuple(matched_types),
            event_weight=weight,
            theme=theme_raw,
            themes=themes,
        )

    def _compute_theme_heats(self, trade_date: date, today_records) -> list[ThemeHeat]:
        """Compute theme heat with persistence tracking."""
        # Parse today's themes
        today_themes: dict[str, list[tuple[str, str]]] = {}  # theme -> [(code, name)]
        for rec in today_records:
            if not rec.theme:
                continue
            for theme in rec.theme.split("+"):
                theme = theme.strip()
                if not theme:
                    continue
                if theme not in today_themes:
                    today_themes[theme] = []
                today_themes[theme].append((rec.ts_code, rec.name))

        # Yesterday's theme counts
        prev_date = get_previous_trading_day(trade_date)
        yesterday_themes: dict[str, int] = {}
        if prev_date:
            yesterday_themes = self._kpl_repo.get_themes_by_date(prev_date)

        # Persistence: check how many recent days each theme appeared (single query)
        recent_days = get_recent_trading_days(trade_date, 5)
        theme_day_counts = self._kpl_repo.get_themes_by_dates(recent_days)

        # Build ThemeHeat results
        heats = []
        for theme, stocks in today_themes.items():
            today_count = len(stocks)
            yesterday_count = yesterday_themes.get(theme, 0)
            persistence = theme_day_counts.get(theme, 0) + 1  # +1 for today

            # Heat trend
            if yesterday_count == 0:
                trend = "NEW"
            elif today_count > yesterday_count * 1.3:
                trend = "HEATING"
            elif today_count < yesterday_count * 0.7:
                trend = "COOLING"
            else:
                trend = "STABLE"

            # Heat score (0-100)
            heat_score = _compute_heat_score(today_count, persistence, trend)

            # Sort stocks by amount for leaders
            codes = tuple(s[0] for s in stocks[:5])
            names = tuple(s[1] for s in stocks[:5])

            heats.append(ThemeHeat(
                theme_name=theme,
                today_count=today_count,
                yesterday_count=yesterday_count,
                persistence_days=persistence,
                heat_trend=trend,
                heat_score=round(heat_score, 2),
                leader_codes=codes,
                leader_names=names,
            ))

        return sorted(heats, key=lambda h: h.heat_score, reverse=True)

    @staticmethod
    def _build_narrative(
        dominant: str,
        distribution: dict[str, int],
        theme_heats: list[ThemeHeat],
    ) -> str:
        """Build human-readable market narrative."""
        parts = []

        # Dominant event
        total = sum(distribution.values())
        if total > 0:
            dom_count = distribution.get(dominant, 0)
            dom_pct = dom_count / total * 100
            parts.append(f"主导: {dominant}({dom_pct:.0f}%)")

        # Top themes
        if theme_heats:
            top_themes = theme_heats[:3]
            theme_strs = []
            for th in top_themes:
                indicator = {"HEATING": "↑", "COOLING": "↓", "STABLE": "→", "NEW": "★"}.get(
                    th.heat_trend, ""
                )
                theme_strs.append(f"{th.theme_name}{indicator}({th.today_count})")
            parts.append("热点: " + " ".join(theme_strs))

        # Concentration warning
        if theme_heats:
            top3 = sum(th.today_count for th in theme_heats[:3])
            if top3 > 0 and total > 0:
                conc = top3 / total
                if conc > 0.6:
                    parts.append("题材高度集中")
                elif conc < 0.3:
                    parts.append("题材分散")

        return " | ".join(parts) if parts else "无明显主线"


def _compute_heat_score(today_count: int, persistence_days: int, trend: str) -> float:
    """Compute heat score for a theme (0-100).

    Factors:
    - 今日涨停数 (40%): more stocks = hotter
    - 持续天数 (35%): longer persistence = more reliable
    - 趋势 (25%): heating > stable > new > cooling
    """
    # Count score: 1 stock = 20, 3 stocks = 60, 5+ stocks = 80, 10+ = 100
    if today_count >= 10:
        count_score = 100.0
    elif today_count >= 5:
        count_score = 80.0
    elif today_count >= 3:
        count_score = 60.0
    elif today_count >= 2:
        count_score = 40.0
    else:
        count_score = 20.0

    # Persistence score: 1 day = 20, 2 days = 50, 3+ days = 80, 5+ = 100
    if persistence_days >= 5:
        persist_score = 100.0
    elif persistence_days >= 3:
        persist_score = 80.0
    elif persistence_days >= 2:
        persist_score = 50.0
    else:
        persist_score = 20.0

    # Trend score
    trend_scores = {"HEATING": 100.0, "STABLE": 70.0, "NEW": 50.0, "COOLING": 20.0}
    trend_score = trend_scores.get(trend, 50.0)

    return 0.40 * count_score + 0.35 * persist_score + 0.25 * trend_score
