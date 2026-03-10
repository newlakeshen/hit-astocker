"""Event-driven classification engine (3-layer architecture).

Layer 1 — 公告触发 (anns_d): match company announcements to event types.
Layer 2 — 题材主线 (concept_detail): classify by concept membership.
Layer 3 — 板块扩散 (ths_member + keyword fallback): diffusion tracking
           and keyword-based classification.
"""

import logging
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
from hit_astocker.repositories.ann_repo import AnnouncementRepository
from hit_astocker.repositories.concept_repo import ConceptRepository, ThsMemberRepository
from hit_astocker.repositories.kpl_repo import KplRepository, split_themes
from hit_astocker.utils.date_utils import get_previous_trading_day, get_recent_trading_days

logger = logging.getLogger(__name__)

# ── Layer 1: Announcement type → event type mapping ──
_ANN_TYPE_MAP: dict[str, str] = {
    "业绩预告": EventType.EARNINGS,
    "业绩快报": EventType.EARNINGS,
    "年报": EventType.EARNINGS,
    "季报": EventType.EARNINGS,
    "分红": EventType.EARNINGS,
    "高送转": EventType.EARNINGS,
    "资产重组": EventType.RESTRUCTURE,
    "收购": EventType.RESTRUCTURE,
    "并购": EventType.RESTRUCTURE,
    "股权转让": EventType.RESTRUCTURE,
    "定增": EventType.CAPITAL,
    "增减持": EventType.CAPITAL,
    "回购": EventType.CAPITAL,
    "中标": EventType.NEWS,
    "签约": EventType.NEWS,
    "合同": EventType.NEWS,
    "订单": EventType.NEWS,
    "合作": EventType.NEWS,
    "专利": EventType.NEWS,
}

# ── Layer 1: Announcement title keyword → event type ──
_ANN_TITLE_KEYWORDS: dict[str, str] = {
    "业绩": EventType.EARNINGS,
    "净利润": EventType.EARNINGS,
    "营收": EventType.EARNINGS,
    "预增": EventType.EARNINGS,
    "扭亏": EventType.EARNINGS,
    "分红": EventType.EARNINGS,
    "重组": EventType.RESTRUCTURE,
    "收购": EventType.RESTRUCTURE,
    "并购": EventType.RESTRUCTURE,
    "借壳": EventType.RESTRUCTURE,
    "中标": EventType.NEWS,
    "签约": EventType.NEWS,
    "合作": EventType.NEWS,
    "订单": EventType.NEWS,
    "回购": EventType.CAPITAL,
    "增持": EventType.CAPITAL,
    "减持": EventType.CAPITAL,
    "政策": EventType.POLICY,
    "补贴": EventType.POLICY,
}

# ── Layer 2: Concept category patterns ──
_CONCEPT_POLICY_KEYWORDS = frozenset({
    "碳中和", "一带一路", "国企改革", "新基建", "数字经济",
    "东数西算", "军民融合", "自主可控", "乡村振兴", "共同富裕",
})
_CONCEPT_INDUSTRY_KEYWORDS = frozenset({
    "化工", "钢铁", "煤炭", "有色", "石油", "电力", "建材", "医药",
    "汽车", "纺织", "食品", "白酒", "农业", "畜禽", "航运",
})


class EventClassifier:
    def __init__(self, conn: sqlite3.Connection):
        self._kpl_repo = KplRepository(conn)
        self._ann_repo = AnnouncementRepository(conn)
        self._concept_repo = ConceptRepository(conn)
        self._ths_member_repo = ThsMemberRepository(conn)
        self._conn = conn

    def analyze(self, trade_date: date) -> EventAnalysisResult:
        """Full event-driven analysis for a trading day (3-layer)."""
        records = self._kpl_repo.find_by_tag(trade_date, tag="涨停")
        ts_codes = [r.ts_code for r in records]

        # Pre-load batch data for all 3 layers
        ann_map = self._ann_repo.find_by_codes_recent(ts_codes, trade_date, lookback_days=3)
        concept_map = self._concept_repo.find_concepts_for_codes(ts_codes)
        limit_up_set = set(ts_codes)

        # 1. Classify each stock via 3-layer priority
        stock_events = []
        for rec in records:
            event = self._classify_stock_3layer(
                rec, ann_map, concept_map, limit_up_set,
            )
            stock_events.append(event)

        # 2. Event type distribution
        distribution: dict[str, int] = {}
        for ev in stock_events:
            distribution[ev.event_type] = distribution.get(ev.event_type, 0) + 1

        dominant = max(distribution, key=distribution.get) if distribution else EventType.UNKNOWN

        # 3. Layer distribution (how many classified by each layer)
        layer_dist: dict[str, int] = {}
        for ev in stock_events:
            layer_dist[ev.event_layer] = layer_dist.get(ev.event_layer, 0) + 1

        # 4. Theme heat tracking
        theme_heats = self._compute_theme_heats(trade_date, records)

        # 5. Theme concentration
        total_stocks = len(stock_events)
        if total_stocks > 0 and theme_heats:
            top3_count = sum(th.today_count for th in theme_heats[:3])
            concentration = min(top3_count / total_stocks, 1.0)
        else:
            concentration = 0.0

        # 6. Market narrative (enhanced with layer info)
        narrative = self._build_narrative(dominant, distribution, theme_heats, layer_dist)

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
        ann_map = self._ann_repo.find_by_codes_recent([ts_code], trade_date, lookback_days=3)
        concept_map = self._concept_repo.find_concepts_for_codes([ts_code])
        limit_up_set = {r.ts_code for r in records}

        for rec in records:
            if rec.ts_code == ts_code:
                return self._classify_stock_3layer(rec, ann_map, concept_map, limit_up_set)
        return None

    def _classify_stock_3layer(
        self,
        rec,
        ann_map: dict,
        concept_map: dict,
        limit_up_set: set[str],
    ) -> StockEvent:
        """3-layer classification priority.

        L1 (公告触发): If stock has matching recent announcement → highest confidence.
        L2 (题材主线): If stock belongs to a concept → classify by concept type.
        L3 (关键词+扩散): Fall back to lu_desc keyword matching + diffusion scoring.
        """
        code = rec.ts_code
        lu_desc = rec.lu_desc or ""
        theme_raw = rec.theme or ""
        themes = tuple(split_themes(theme_raw))

        # Parse concepts
        concepts = tuple(concept_map.get(code, []))

        # Compute diffusion rate for primary concept
        diffusion_rate = self._compute_diffusion(concepts, limit_up_set)

        # ── Layer 1: Announcement-based ──
        anns = ann_map.get(code, [])
        if anns:
            event_type = self._classify_from_announcements(anns)
            if event_type != EventType.UNKNOWN:
                ann_title = anns[0].title
                return StockEvent(
                    ts_code=code,
                    name=rec.name,
                    lu_desc=lu_desc,
                    event_type=event_type,
                    event_types=(event_type,),
                    event_weight=EVENT_WEIGHTS.get(event_type, 0.75),
                    theme=theme_raw,
                    themes=themes,
                    event_layer="ANNOUNCEMENT",
                    ann_title=ann_title,
                    concepts=concepts,
                    diffusion_rate=diffusion_rate,
                )

        # ── Layer 2: Concept-based ──
        if concepts:
            event_type = self._classify_from_concepts(concepts)
            if event_type != EventType.UNKNOWN:
                return StockEvent(
                    ts_code=code,
                    name=rec.name,
                    lu_desc=lu_desc,
                    event_type=event_type,
                    event_types=(event_type,),
                    event_weight=EVENT_WEIGHTS.get(event_type, 0.65),
                    theme=theme_raw,
                    themes=themes,
                    event_layer="CONCEPT",
                    concepts=concepts,
                    diffusion_rate=diffusion_rate,
                )

        # ── Layer 3: Keyword matching (enhanced) ──
        matched_types = self._match_keywords(lu_desc)
        if not matched_types:
            # Also try theme names as keywords (catches 人工智能/化工 etc.)
            matched_types = self._match_theme_keywords(themes)

        if not matched_types:
            matched_types = [EventType.UNKNOWN]

        primary = max(matched_types, key=lambda t: EVENT_WEIGHTS.get(t, 0.0))
        weight = EVENT_WEIGHTS.get(primary, 0.4)

        return StockEvent(
            ts_code=code,
            name=rec.name,
            lu_desc=lu_desc,
            event_type=primary,
            event_types=tuple(matched_types),
            event_weight=weight,
            theme=theme_raw,
            themes=themes,
            event_layer="KEYWORD",
            concepts=concepts,
            diffusion_rate=diffusion_rate,
        )

    @staticmethod
    def _classify_from_announcements(anns: list) -> str:
        """L1: Classify from announcement type + title keywords."""
        for ann in anns:
            # First try ann_type direct mapping
            if ann.ann_type:
                for pattern, event_type in _ANN_TYPE_MAP.items():
                    if pattern in ann.ann_type:
                        return event_type

            # Then try title keyword matching
            title = ann.title or ""
            for keyword, event_type in _ANN_TITLE_KEYWORDS.items():
                if keyword in title:
                    return event_type

        return EventType.UNKNOWN

    @staticmethod
    def _classify_from_concepts(concepts: list[str]) -> str:
        """L2: Classify event type from concept membership."""
        for concept in concepts:
            # Policy concepts
            for kw in _CONCEPT_POLICY_KEYWORDS:
                if kw in concept:
                    return EventType.POLICY
            # Industry concepts
            for kw in _CONCEPT_INDUSTRY_KEYWORDS:
                if kw in concept:
                    return EventType.INDUSTRY
        # If concept exists but doesn't match known categories → CONCEPT
        return EventType.CONCEPT

    def _compute_diffusion(
        self,
        concepts: tuple[str, ...],
        limit_up_set: set[str],
    ) -> float:
        """L3: Compute diffusion rate — ratio of concept members that are limit-up.

        Uses concept_detail membership as primary source; falls back to
        ths_member if available.
        """
        if not concepts:
            return 0.0

        # Try concept_detail first
        primary_concept = concepts[0]
        members = self._concept_repo.get_concept_members(primary_concept)

        if not members and self._ths_member_repo.has_data():
            # Fallback: check ths_member
            # (ths_member uses concept index codes, not names — skip if mismatch)
            pass

        if not members:
            return 0.0

        limit_up_members = sum(1 for m in members if m in limit_up_set)
        return limit_up_members / len(members)

    @staticmethod
    def _match_keywords(lu_desc: str) -> list[str]:
        """Match lu_desc against EVENT_KEYWORDS dictionary."""
        matched: list[str] = []
        for keyword, event_type in EVENT_KEYWORDS.items():
            if keyword in lu_desc and event_type not in matched:
                matched.append(event_type)
        return matched

    @staticmethod
    def _match_theme_keywords(themes: tuple[str, ...]) -> list[str]:
        """Try to classify from theme names (catches 人工智能/化工 etc.)."""
        matched: list[str] = []
        for theme in themes:
            for kw in _CONCEPT_POLICY_KEYWORDS:
                if kw in theme and EventType.POLICY not in matched:
                    matched.append(EventType.POLICY)
                    break
            for kw in _CONCEPT_INDUSTRY_KEYWORDS:
                if kw in theme and EventType.INDUSTRY not in matched:
                    matched.append(EventType.INDUSTRY)
                    break
            # Generic concept keywords
            for keyword, event_type in EVENT_KEYWORDS.items():
                if keyword in theme and event_type not in matched:
                    matched.append(event_type)
        # If themes exist but nothing matched → at least CONCEPT
        if not matched and themes:
            matched.append(EventType.CONCEPT)
        return matched

    def _compute_theme_heats(self, trade_date: date, today_records) -> list[ThemeHeat]:
        """Compute theme heat with persistence, lifecycle, and crowding."""
        today_themes: dict[str, list[tuple[str, str]]] = {}
        for rec in today_records:
            if not rec.theme:
                continue
            for theme in split_themes(rec.theme):
                if theme not in today_themes:
                    today_themes[theme] = []
                today_themes[theme].append((rec.ts_code, rec.name))

        prev_date = get_previous_trading_day(trade_date)
        yesterday_themes: dict[str, int] = {}
        if prev_date:
            yesterday_themes = self._kpl_repo.get_themes_by_date(prev_date)

        recent_days = get_recent_trading_days(trade_date, 5)
        theme_day_counts = self._kpl_repo.get_themes_by_dates(recent_days)

        # Pre-fetch T-2 theme counts for lifecycle detection
        t_minus_2_themes: dict[str, int] = {}
        if len(recent_days) >= 2:
            t_minus_2_themes = self._kpl_repo.get_themes_by_date(recent_days[1])

        heats = []
        for theme, stocks in today_themes.items():
            today_count = len(stocks)
            yesterday_count = yesterday_themes.get(theme, 0)
            t2_count = t_minus_2_themes.get(theme, 0)
            persistence = theme_day_counts.get(theme, 0) + 1

            if yesterday_count == 0:
                trend = "NEW"
            elif today_count > yesterday_count * 1.3:
                trend = "HEATING"
            elif today_count < yesterday_count * 0.7:
                trend = "COOLING"
            else:
                trend = "STABLE"

            # ── Lifecycle: NEW → HEATING → PEAK → FADING ──
            lifecycle = _determine_lifecycle(
                today_count, yesterday_count, t2_count, persistence, trend,
            )

            # ── Crowding: 涨停数/板块成分股数 ──
            limit_up_codes = {s[0] for s in stocks}
            crowding_ratio, crowding_penalty = self._compute_crowding(
                theme, limit_up_codes, today_count,
            )

            heat_score = _compute_heat_score(today_count, persistence, trend)
            # Apply crowding penalty (high crowding → lower effective heat)
            heat_score = max(0, heat_score - crowding_penalty)

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
                lifecycle=lifecycle,
                crowding_ratio=round(crowding_ratio, 4),
                crowding_penalty=round(crowding_penalty, 2),
            ))

        return sorted(heats, key=lambda h: h.heat_score, reverse=True)

    def _compute_crowding(
        self,
        theme: str,
        limit_up_codes: set[str],
        today_count: int,
    ) -> tuple[float, float]:
        """Compute crowding ratio and penalty for a theme.

        拥挤度 = 涨停股数 / 板块成分股总数
        高拥挤 (>50%) 意味着板块内大部分股票已涨停, 次日大概率分歧.
        """
        # Try concept membership for sector size
        members = self._concept_repo.get_concept_members(theme)
        if not members or len(members) < 3:
            # No concept data or too small → no penalty
            return 0.0, 0.0

        ratio = len(limit_up_codes & set(members)) / len(members)

        # Penalty curve: gentle below 30%, steep above 50%
        if ratio > 0.60:
            penalty = 25.0  # 极度拥挤: 重罚
        elif ratio > 0.50:
            penalty = 18.0
        elif ratio > 0.40:
            penalty = 10.0
        elif ratio > 0.30:
            penalty = 5.0
        else:
            penalty = 0.0

        return ratio, penalty

    @staticmethod
    def _build_narrative(
        dominant: str,
        distribution: dict[str, int],
        theme_heats: list[ThemeHeat],
        layer_dist: dict[str, int],
    ) -> str:
        """Build human-readable market narrative with layer coverage."""
        parts = []

        total = sum(distribution.values())
        if total > 0:
            dom_count = distribution.get(dominant, 0)
            dom_pct = dom_count / total * 100
            parts.append(f"主导: {dominant}({dom_pct:.0f}%)")

        if theme_heats:
            top_themes = theme_heats[:3]
            theme_strs = []
            for th in top_themes:
                indicator = {"HEATING": "↑", "COOLING": "↓", "STABLE": "→", "NEW": "★"}.get(
                    th.heat_trend, ""
                )
                theme_strs.append(f"{th.theme_name}{indicator}({th.today_count})")
            parts.append("热点: " + " ".join(theme_strs))

        # Layer coverage info
        if layer_dist and total > 0:
            ann_pct = layer_dist.get("ANNOUNCEMENT", 0) / total * 100
            cpt_pct = layer_dist.get("CONCEPT", 0) / total * 100
            kw_pct = layer_dist.get("KEYWORD", 0) / total * 100
            unknown_count = distribution.get(EventType.UNKNOWN, 0)
            parts.append(f"识别: 公告{ann_pct:.0f}% 概念{cpt_pct:.0f}% 关键词{kw_pct:.0f}% 未知{unknown_count}")

        if theme_heats:
            top3 = sum(th.today_count for th in theme_heats[:3])
            if top3 > 0 and total > 0:
                conc = top3 / total
                if conc > 0.6:
                    parts.append("题材高度集中")
                elif conc < 0.3:
                    parts.append("题材分散")

        return " | ".join(parts) if parts else "无明显主线"


def _determine_lifecycle(
    today_count: int,
    yesterday_count: int,
    t2_count: int,
    persistence: int,
    trend: str,
) -> str:
    """Determine theme lifecycle phase.

    NEW:     首日出现 (persistence=1)
    HEATING: 涨停数连续增长 (today > yesterday > t2)
    PEAK:    涨停数开始回落但仍有基数 (today < yesterday AND yesterday >= t2)
    FADING:  连续回落或极度萎缩 (today << yesterday)
    """
    if persistence <= 1:
        return "NEW"

    if trend == "COOLING" and yesterday_count > 0:
        if today_count < yesterday_count * 0.5:
            return "FADING"
        return "PEAK"

    if trend == "HEATING":
        return "HEATING"

    # STABLE: check if yesterday was growing
    if yesterday_count >= t2_count and today_count >= yesterday_count:
        return "HEATING"
    if yesterday_count > today_count:
        return "PEAK"

    return "HEATING"  # default for stable/growing


def _compute_heat_score(today_count: int, persistence_days: int, trend: str) -> float:
    """Compute heat score for a theme (0-100)."""
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

    if persistence_days >= 5:
        persist_score = 100.0
    elif persistence_days >= 3:
        persist_score = 80.0
    elif persistence_days >= 2:
        persist_score = 50.0
    else:
        persist_score = 20.0

    trend_scores = {"HEATING": 100.0, "STABLE": 70.0, "NEW": 50.0, "COOLING": 20.0}
    trend_score = trend_scores.get(trend, 50.0)

    return 0.40 * count_score + 0.35 * persist_score + 0.25 * trend_score
