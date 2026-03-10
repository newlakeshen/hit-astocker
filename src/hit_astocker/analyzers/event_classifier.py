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
    EVENT_BASE_STRENGTH,
    EVENT_KEYWORDS,
    EventAnalysisResult,
    EventType,
    StockEvent,
    ThemeHeat,
    compute_event_weight,
)
from hit_astocker.models.kpl_data import KplRecord
from hit_astocker.models.limit_data import LimitDirection, LimitRecord
from hit_astocker.repositories.ann_repo import AnnouncementRepository
from hit_astocker.repositories.concept_repo import ConceptRepository, ThsMemberRepository
from hit_astocker.repositories.kpl_repo import KplRepository, split_themes
from hit_astocker.repositories.limit_repo import LimitListRepository
from hit_astocker.repositories.limit_step_repo import LimitStepRepository
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
        self._step_repo = LimitStepRepository(conn)
        self._limit_repo = LimitListRepository(conn)
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
                rec, ann_map, concept_map, limit_up_set, trade_date,
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
                return self._classify_stock_3layer(
                    rec, ann_map, concept_map, limit_up_set, trade_date,
                )
        return None

    def _classify_stock_3layer(
        self,
        rec,
        ann_map: dict,
        concept_map: dict,
        limit_up_set: set[str],
        trade_date: date,
    ) -> StockEvent:
        """3-layer classification priority with dynamic event weight decay.

        L1 (公告触发): announcement → highest confidence, weight decays by days since pub.
        L2 (题材主线): concept membership → classify by concept type.
        L3 (关键词+扩散): keyword matching + diffusion scoring.
        """
        code = rec.ts_code
        lu_desc = rec.lu_desc or ""
        theme_raw = rec.theme or ""
        themes = tuple(split_themes(theme_raw))

        # Parse concepts
        concepts = tuple(concept_map.get(code, []))

        # Compute diffusion rate for primary concept
        diffusion_rate = self._compute_diffusion(concepts, limit_up_set)

        # ── Layer 1: Announcement-based (dynamic decay) ──
        anns = ann_map.get(code, [])
        if anns:
            event_type = self._classify_from_announcements(anns)
            if event_type != EventType.UNKNOWN:
                ann = anns[0]
                ann_title = ann.title or ""
                # 计算公告距今交易日数
                days_since = (trade_date - ann.ann_date).days
                weight = compute_event_weight(
                    event_type, days_since, ann_title,
                )
                return StockEvent(
                    ts_code=code,
                    name=rec.name,
                    lu_desc=lu_desc,
                    event_type=event_type,
                    event_types=(event_type,),
                    event_weight=weight,
                    theme=theme_raw,
                    themes=themes,
                    event_layer="ANNOUNCEMENT",
                    ann_title=ann_title,
                    concepts=concepts,
                    diffusion_rate=diffusion_rate,
                )

        # ── Layer 2: Concept-based (no decay, concepts are structural) ──
        if concepts:
            event_type = self._classify_from_concepts(concepts)
            if event_type != EventType.UNKNOWN:
                weight = compute_event_weight(
                    event_type, 0, " ".join(concepts),
                )
                return StockEvent(
                    ts_code=code,
                    name=rec.name,
                    lu_desc=lu_desc,
                    event_type=event_type,
                    event_types=(event_type,),
                    event_weight=weight,
                    theme=theme_raw,
                    themes=themes,
                    event_layer="CONCEPT",
                    concepts=concepts,
                    diffusion_rate=diffusion_rate,
                )

        # ── Layer 3: Keyword matching (no decay, inferred from today's data) ──
        matched_types = self._match_keywords(lu_desc)
        if not matched_types:
            matched_types = self._match_theme_keywords(themes)

        if not matched_types:
            matched_types = [EventType.UNKNOWN]

        primary = max(
            matched_types,
            key=lambda t: EVENT_BASE_STRENGTH.get(t, 0.0),
        )
        weight = compute_event_weight(primary, 0, lu_desc)

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
        """Compute multi-dimensional theme heat.

        6 dimensions:
        - 主线高度 (25%): max board height from limit_step → 辨别真主线 vs 跟风首板堆
        - 龙头强度 (20%): leader seal quality (封单/封板时间/开板次数)
        - 扩散速度 (15%): count acceleration (today vs yesterday delta + direction)
        - 涨停家数 (15%): raw count (diminishing returns)
        - 持续天数 (15%): persistence with lifecycle bonus
        - 可参与度 (10%): non-yizi ratio (open_times > 0 → can actually buy)
        """
        # ── 1. Group stocks by theme ──
        today_themes: dict[str, list[tuple[str, str]]] = {}
        for rec in today_records:
            if not rec.theme:
                continue
            for theme in split_themes(rec.theme):
                if theme not in today_themes:
                    today_themes[theme] = []
                today_themes[theme].append((rec.ts_code, rec.name))

        # ── 2. Batch-load board heights + limit_list_d for all stocks ──
        stock_heights = self._step_repo.get_stock_heights(trade_date)
        limit_records = self._limit_repo.find_records_by_date(trade_date)
        limit_map: dict[str, LimitRecord] = {
            r.ts_code: r for r in limit_records if r.limit == LimitDirection.UP
        }

        # ── 3. Build KPL record map for seal quality (lu_limit_order) ──
        kpl_map: dict[str, KplRecord] = {rec.ts_code: rec for rec in today_records}

        # ── 4. Historical data for persistence / trend / lifecycle ──
        prev_date = get_previous_trading_day(trade_date)
        yesterday_themes: dict[str, int] = {}
        if prev_date:
            yesterday_themes = self._kpl_repo.get_themes_by_date(prev_date)

        recent_days = get_recent_trading_days(trade_date, 5)
        theme_day_counts = self._kpl_repo.get_themes_by_dates(recent_days)

        t_minus_2_themes: dict[str, int] = {}
        if len(recent_days) >= 2:
            t_minus_2_themes = self._kpl_repo.get_themes_by_date(recent_days[1])

        # ── 5. Compute per-theme multi-dimensional scores ──
        heats = []
        for theme, stocks in today_themes.items():
            codes = [s[0] for s in stocks]
            today_count = len(stocks)
            yesterday_count = yesterday_themes.get(theme, 0)
            t2_count = t_minus_2_themes.get(theme, 0)
            persistence = theme_day_counts.get(theme, 0) + 1

            # Trend
            if yesterday_count == 0:
                trend = "NEW"
            elif today_count > yesterday_count * 1.3:
                trend = "HEATING"
            elif today_count < yesterday_count * 0.7:
                trend = "COOLING"
            else:
                trend = "STABLE"

            lifecycle = _determine_lifecycle(
                today_count, yesterday_count, t2_count, persistence, trend,
            )

            # Crowding
            limit_up_codes = set(codes)
            crowding_ratio, crowding_penalty = self._compute_crowding(
                theme, limit_up_codes, today_count,
            )

            # ── Dimension 1: 主线高度 (max board height in this theme) ──
            theme_heights = {c: stock_heights.get(c, 1) for c in codes}
            max_height = max(theme_heights.values()) if theme_heights else 1
            height_score = _score_max_height(max_height)

            # ── Dimension 2: 龙头强度 (best leader's seal quality) ──
            leader_score = _score_leader_strength(codes, limit_map, kpl_map)

            # ── Dimension 3: 扩散速度 (expansion acceleration) ──
            expansion_score = _score_expansion(
                today_count, yesterday_count, t2_count, trend,
            )

            # ── Dimension 4: 涨停家数 (count, diminishing returns) ──
            count_score = _score_count(today_count)

            # ── Dimension 5: 持续天数 (persistence + lifecycle bonus) ──
            persist_score = _score_persistence(persistence, lifecycle)

            # ── Dimension 6: 可参与度 (non-yizi ratio) ──
            participation_score = _score_participation(codes, limit_map)

            # ── Weighted composite ──
            heat_score = (
                0.25 * height_score
                + 0.20 * leader_score
                + 0.15 * expansion_score
                + 0.15 * count_score
                + 0.15 * persist_score
                + 0.10 * participation_score
            )
            heat_score = max(0, heat_score - crowding_penalty)

            # ── Sort leaders by height DESC → seal quality DESC ──
            sorted_stocks = sorted(
                stocks,
                key=lambda s: (
                    stock_heights.get(s[0], 1),
                    _get_seal_quality(s[0], limit_map, kpl_map),
                ),
                reverse=True,
            )
            leader_codes = tuple(s[0] for s in sorted_stocks[:5])
            leader_names = tuple(s[1] for s in sorted_stocks[:5])

            heats.append(ThemeHeat(
                theme_name=theme,
                today_count=today_count,
                yesterday_count=yesterday_count,
                persistence_days=persistence,
                heat_trend=trend,
                heat_score=round(heat_score, 2),
                leader_codes=leader_codes,
                leader_names=leader_names,
                lifecycle=lifecycle,
                crowding_ratio=round(crowding_ratio, 4),
                crowding_penalty=round(crowding_penalty, 2),
                max_height=max_height,
                height_score=round(height_score, 2),
                leader_score=round(leader_score, 2),
                expansion_score=round(expansion_score, 2),
                participation_score=round(participation_score, 2),
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


def _score_max_height(max_height: int) -> float:
    """主线高度得分: 高度越高 → 主线越强.

    1板(首板)→20, 2板→45, 3板→65, 4板→80, 5板→90, 6+板→100.
    A股打板核心: 高度=空间=人气, 3板以上才算有辨识度的主线.
    """
    thresholds = {1: 20.0, 2: 45.0, 3: 65.0, 4: 80.0, 5: 90.0}
    if max_height >= 6:
        return 100.0
    return thresholds.get(max_height, 20.0)


def _score_leader_strength(
    codes: list[str],
    limit_map: dict[str, LimitRecord],
    kpl_map: dict[str, KplRecord],
) -> float:
    """龙头强度得分: 取板块内最强个股的封板质量.

    综合: 封单金额(40%) + 封板时间(30%) + 开板次数少(30%).
    只有龙头强 → 板块才有持续性和号召力.
    """
    best = 0.0
    for code in codes:
        best = max(best, _get_seal_quality(code, limit_map, kpl_map))
    return best


def _get_seal_quality(
    code: str,
    limit_map: dict[str, LimitRecord],
    kpl_map: dict[str, KplRecord],
) -> float:
    """单只股票的封板质量得分 (0-100)."""
    lr = limit_map.get(code)
    kr = kpl_map.get(code)

    # ── 封单金额子分 (40%) ──
    seal_amount = 0.0
    if lr is not None:
        seal_amount = lr.limit_amount or 0.0
    elif kr is not None:
        seal_amount = kr.lu_limit_order or 0.0
    # 封单 5000万→40, 1亿→60, 3亿→80, 5亿+→100
    if seal_amount >= 50000:
        seal_score = 100.0
    elif seal_amount >= 30000:
        seal_score = 80.0
    elif seal_amount >= 10000:
        seal_score = 60.0
    elif seal_amount >= 5000:
        seal_score = 40.0
    else:
        seal_score = 20.0

    # ── 封板时间子分 (30%) ──
    time_score = 50.0  # default
    if lr is not None and lr.first_time:
        ft = lr.first_time
        # 10:00前→100, 10:30前→80, 11:00前→60, 13:30前→40, else→20
        if ft <= "10:00:00":
            time_score = 100.0
        elif ft <= "10:30:00":
            time_score = 80.0
        elif ft <= "11:00:00":
            time_score = 60.0
        elif ft <= "13:30:00":
            time_score = 40.0
        else:
            time_score = 20.0

    # ── 开板次数子分 (30%) ──
    # open_times only available from limit_list_d (LimitRecord), not KPL
    open_times = lr.open_times if lr is not None else 0
    # 0次→100, 1次→70, 2次→40, 3+次→20
    if open_times == 0:
        open_score = 100.0
    elif open_times == 1:
        open_score = 70.0
    elif open_times == 2:
        open_score = 40.0
    else:
        open_score = 20.0

    return 0.40 * seal_score + 0.30 * time_score + 0.30 * open_score


def _score_expansion(
    today_count: int,
    yesterday_count: int,
    t2_count: int,
    trend: str,
) -> float:
    """扩散速度得分: 不只看数量, 更看加速度.

    连续放量扩散(today > yesterday > t2) → 最高分.
    首日爆发(NEW 且 count >= 3) → 高分 (可能是新主线启动).
    缩量→低分; 持续缩量→最低分.
    """
    if trend == "NEW":
        # 首日: 看爆发规模
        if today_count >= 5:
            return 85.0
        if today_count >= 3:
            return 70.0
        return 40.0

    if yesterday_count <= 0:
        return 40.0

    # 扩散比 = today / yesterday
    ratio = today_count / yesterday_count

    # 加速度 (二阶): 今天扩散比 vs 昨天扩散比
    # 需要 t2_count >= 2 避免小样本噪声放大
    if t2_count >= 2 and yesterday_count >= 2:
        prev_ratio = yesterday_count / t2_count
        accel = ratio - prev_ratio
    else:
        accel = 0.0

    # Base: expansion ratio → score
    if ratio >= 2.0:
        base = 95.0   # 翻倍扩散
    elif ratio >= 1.5:
        base = 80.0   # 显著扩散
    elif ratio >= 1.1:
        base = 65.0   # 小幅扩散
    elif ratio >= 0.8:
        base = 45.0   # 基本持平
    elif ratio >= 0.5:
        base = 25.0   # 明显萎缩
    else:
        base = 10.0   # 大幅萎缩

    # Acceleration bonus/penalty (max ±15)
    accel_adj = min(max(accel * 20, -15), 15)

    return min(100.0, max(0.0, base + accel_adj))


def _score_count(today_count: int) -> float:
    """涨停家数得分 (diminishing returns).

    1→15, 2→30, 3→50, 5→70, 8→85, 10+→100.
    Diminishing returns: 从5家开始边际递减.
    """
    if today_count >= 10:
        return 100.0
    if today_count >= 8:
        return 85.0
    if today_count >= 5:
        return 70.0
    if today_count >= 3:
        return 50.0
    if today_count >= 2:
        return 30.0
    return 15.0


def _score_persistence(persistence_days: int, lifecycle: str) -> float:
    """持续天数得分 + 生命周期加成.

    持续天数: 1→15, 2→40, 3→65, 4→80, 5+→90.
    HEATING阶段+5, PEAK-5, FADING-15 (持续但衰退 ≠ 好题材).
    """
    if persistence_days >= 5:
        base = 90.0
    elif persistence_days >= 4:
        base = 80.0
    elif persistence_days >= 3:
        base = 65.0
    elif persistence_days >= 2:
        base = 40.0
    else:
        base = 15.0

    lifecycle_adj = {"HEATING": 5.0, "NEW": 0.0, "PEAK": -5.0, "FADING": -15.0}
    adj = lifecycle_adj.get(lifecycle, 0.0)

    return min(100.0, max(0.0, base + adj))


def _score_participation(codes: list[str], limit_map: dict[str, LimitRecord]) -> float:
    """可参与度得分: 非一字板占比.

    一字板(open_times=0 且 首封极早) → 散户无法买入 → 不可参与.
    非一字板占比越高 → 实际可操作性越强.
    全部一字→20, 50%一字→60, 全部可参与→100.
    """
    if not codes:
        return 50.0

    participatable = 0
    checked = 0
    for code in codes:
        lr = limit_map.get(code)
        if lr is None:
            continue
        checked += 1
        open_times = lr.open_times or 0
        first_time = lr.first_time or ""
        # 一字板判定: 0次开板 + 首封在09:25前(集合竞价直接封住)
        is_yizi = open_times == 0 and first_time <= "09:25:00"
        if not is_yizi:
            participatable += 1

    if checked == 0:
        return 50.0

    ratio = participatable / checked
    # 0%→20, 25%→40, 50%→60, 75%→80, 100%→100
    return 20.0 + ratio * 80.0
