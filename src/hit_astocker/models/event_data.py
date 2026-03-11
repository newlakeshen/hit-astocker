"""Event-driven and sentiment data models."""

import math
import re
from dataclasses import dataclass, field
from datetime import date


class EventType:
    """涨停原因事件类型分类."""

    POLICY = "政策面"  # 政策利好、国家战略
    EARNINGS = "业绩面"  # 业绩预增、扭亏为盈
    CONCEPT = "概念炒作"  # 热点概念、题材炒作
    RESTRUCTURE = "重组并购"  # 资产重组、收购
    TECHNICAL = "技术面"  # 突破形态、超跌反弹
    CAPITAL = "资金面"  # 主力资金流入
    INDUSTRY = "行业面"  # 行业景气度
    NEWS = "消息面"  # 突发新闻、公告
    UNKNOWN = "未知"


class PolicyLevel:
    """政策级别 — 同类型政策内部也有强弱."""

    STATE = "国家级"       # 国务院/央行/总书记 — 最强, 持续性最长
    MINISTRY = "部委级"    # 发改委/工信部/证监会 — 强
    INDUSTRY = "行业级"    # 行业规划/战略 — 中等
    LOCAL = "地方级"       # 地方补贴/通知 — 较弱
    UNKNOWN = "未知"


class OrderAmountLevel:
    """订单/合同金额级别 — 金额决定事件含金量."""

    MEGA = "超大单"   # ≥10亿 — 重大合同, S级催化
    LARGE = "大单"    # ≥1亿 — 显著影响, A级
    MEDIUM = "中单"   # ≥5000万 — 一般影响, B级
    SMALL = "小单"    # <5000万 — 影响有限, C级
    UNKNOWN = "未知"  # 金额未知


# ── 政策级别关键词 ──
_POLICY_LEVEL_KEYWORDS: dict[str, list[str]] = {
    PolicyLevel.STATE: [
        "国务院", "中央", "央行", "总书记", "常委会", "政治局",
        "降息", "降准", "全面深化", "国家主席",
    ],
    PolicyLevel.MINISTRY: [
        "发改委", "工信部", "财政部", "科技部", "商务部", "证监会",
        "银保监", "国资委", "住建部", "交通部", "农业部", "生态环境部",
    ],
    PolicyLevel.INDUSTRY: [
        "规划", "战略", "行动方案", "指导意见", "发展纲要",
        "改革", "试点", "示范区",
    ],
    PolicyLevel.LOCAL: [
        "补贴", "通知", "省", "市政府", "地方",
    ],
}


def detect_policy_level(text: str) -> str:
    """从文本中识别政策级别 (优先返回最高级别)."""
    for level in (PolicyLevel.STATE, PolicyLevel.MINISTRY,
                  PolicyLevel.INDUSTRY, PolicyLevel.LOCAL):
        for kw in _POLICY_LEVEL_KEYWORDS[level]:
            if kw in text:
                return level
    return PolicyLevel.UNKNOWN


def parse_amount_wan(text: str) -> float | None:
    """从中文文本中解析金额, 归一化为万元.

    支持: 5.2亿, 3000万, 12亿元, 约8000万, 1.5亿元合同 等.
    Returns None if no amount found.
    """
    # 亿 (larger unit, try first)
    m = re.search(r"(\d+(?:\.\d+)?)\s*亿", text)
    if m:
        return float(m.group(1)) * 10000  # 亿 → 万

    # 万
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", text)
    if m:
        return float(m.group(1))

    return None


def detect_order_amount_level(text: str) -> tuple[str, float | None]:
    """从文本中识别订单/合同金额级别.

    Returns (level, amount_wan).
    """
    amount = parse_amount_wan(text)
    if amount is None:
        return OrderAmountLevel.UNKNOWN, None
    if amount >= 100000:  # ≥10亿
        return OrderAmountLevel.MEGA, amount
    if amount >= 10000:   # ≥1亿
        return OrderAmountLevel.LARGE, amount
    if amount >= 5000:    # ≥5000万
        return OrderAmountLevel.MEDIUM, amount
    return OrderAmountLevel.SMALL, amount


# ── 金额级别 → 事件权重乘数 ──
_AMOUNT_GRADE_MAP: dict[str, float] = {
    OrderAmountLevel.MEGA: 1.0,    # 超大单: S级
    OrderAmountLevel.LARGE: 0.85,  # 大单: A级
    OrderAmountLevel.MEDIUM: 0.70, # 中单: B级
    OrderAmountLevel.SMALL: 0.55,  # 小单: C级
    OrderAmountLevel.UNKNOWN: 0.65, # 金额未知: B-级
}

# ── 政策级别 → 半衰期调整 (更高级别政策持续更久) ──
_POLICY_HALF_LIFE_MULTIPLIER: dict[str, float] = {
    PolicyLevel.STATE: 2.0,     # 国家级: 半衰期翻倍
    PolicyLevel.MINISTRY: 1.5,  # 部委级: 1.5倍
    PolicyLevel.INDUSTRY: 1.0,  # 行业级: 标准
    PolicyLevel.LOCAL: 0.7,     # 地方级: 衰减更快
    PolicyLevel.UNKNOWN: 1.0,
}


# 关键词 -> 事件类型映射
EVENT_KEYWORDS: dict[str, str] = {
    # 政策面
    "政策": EventType.POLICY,
    "国家": EventType.POLICY,
    "国务院": EventType.POLICY,
    "发改委": EventType.POLICY,
    "补贴": EventType.POLICY,
    "规划": EventType.POLICY,
    "战略": EventType.POLICY,
    "改革": EventType.POLICY,
    "央行": EventType.POLICY,
    "财政": EventType.POLICY,
    "降息": EventType.POLICY,
    "降准": EventType.POLICY,
    # 业绩面
    "业绩": EventType.EARNINGS,
    "净利润": EventType.EARNINGS,
    "营收": EventType.EARNINGS,
    "预增": EventType.EARNINGS,
    "扭亏": EventType.EARNINGS,
    "高送转": EventType.EARNINGS,
    "分红": EventType.EARNINGS,
    "季报": EventType.EARNINGS,
    "年报": EventType.EARNINGS,
    # 重组并购
    "重组": EventType.RESTRUCTURE,
    "收购": EventType.RESTRUCTURE,
    "并购": EventType.RESTRUCTURE,
    "借壳": EventType.RESTRUCTURE,
    "注入": EventType.RESTRUCTURE,
    "资产": EventType.RESTRUCTURE,
    # 概念炒作
    "概念": EventType.CONCEPT,
    "题材": EventType.CONCEPT,
    "热点": EventType.CONCEPT,
    "龙头": EventType.CONCEPT,
    "板块": EventType.CONCEPT,
    # 技术面
    "超跌": EventType.TECHNICAL,
    "反弹": EventType.TECHNICAL,
    "突破": EventType.TECHNICAL,
    "新高": EventType.TECHNICAL,
    # 资金面
    "主力": EventType.CAPITAL,
    "北向": EventType.CAPITAL,
    "外资": EventType.CAPITAL,
    "融资": EventType.CAPITAL,
    "机构": EventType.CAPITAL,
    "基金": EventType.CAPITAL,
    # 行业面
    "行业": EventType.INDUSTRY,
    "景气": EventType.INDUSTRY,
    "供需": EventType.INDUSTRY,
    "涨价": EventType.INDUSTRY,
    "产能": EventType.INDUSTRY,
    # 消息面
    "公告": EventType.NEWS,
    "中标": EventType.NEWS,
    "签约": EventType.NEWS,
    "合作": EventType.NEWS,
    "订单": EventType.NEWS,
}

# 事件类型基础强度 (peak weight, 无衰减时的上限)
EVENT_BASE_STRENGTH: dict[str, float] = {
    EventType.POLICY: 1.0,       # 政策面最强
    EventType.RESTRUCTURE: 0.95, # 重组并购持续性强
    EventType.EARNINGS: 0.85,    # 业绩面有基本面支撑
    EventType.INDUSTRY: 0.80,    # 行业面持续性好
    EventType.NEWS: 0.75,        # 消息面催化
    EventType.CONCEPT: 0.65,     # 概念炒作短期为主
    EventType.CAPITAL: 0.60,     # 资金面可能只是跟风
    EventType.TECHNICAL: 0.50,   # 技术面最弱
    EventType.UNKNOWN: 0.40,     # 未知原因
}

# 向后兼容: 旧代码引用 EVENT_WEIGHTS 的地方不受影响
EVENT_WEIGHTS = EVENT_BASE_STRENGTH

# ── 事件衰减半衰期 (天数) ──
# 半衰期 = 事件影响力衰减到 50% 所需的交易日数
# 政策/重组: 长尾效应 (市场反复炒作); 概念/消息: 短命 (一两天就过气)
EVENT_DECAY_HALF_LIVES: dict[str, float] = {
    EventType.POLICY: 5.0,       # 政策面: 5个交易日半衰 (国家级可持续)
    EventType.RESTRUCTURE: 7.0,  # 重组并购: 7天半衰 (流程长, 反复发酵)
    EventType.EARNINGS: 3.0,     # 业绩面: 3天半衰 (市场消化快)
    EventType.INDUSTRY: 4.0,     # 行业面: 4天半衰 (景气周期较持续)
    EventType.NEWS: 2.0,         # 消息面: 2天半衰 (来得快去得快)
    EventType.CONCEPT: 1.5,      # 概念炒作: 1.5天半衰 (最短命)
    EventType.CAPITAL: 1.0,      # 资金面: 1天半衰 (资金来去无踪)
    EventType.TECHNICAL: 1.0,    # 技术面: 1天半衰
    EventType.UNKNOWN: 1.0,      # 未知: 1天半衰
}

# ── 事件级别关键词 → 级别乘数 ──
# 同一事件类型内部也有强弱: 国务院发文 >> 地方补贴; 净利润翻倍 >> 小幅预增
# 级别: S=1.0 (重磅), A=0.85 (较强), B=0.70 (一般), C=0.55 (偏弱)
EVENT_GRADE_KEYWORDS: dict[str, list[tuple[str, float]]] = {
    EventType.POLICY: [
        # S级: 国家级/央行/部委
        ("国务院", 1.0), ("央行", 1.0), ("降息", 1.0), ("降准", 1.0),
        ("发改委", 0.95), ("财政", 0.90),
        # A级: 部委/规划
        ("规划", 0.85), ("战略", 0.85), ("改革", 0.85),
        # B级: 普通政策
        ("政策", 0.70), ("补贴", 0.70),
    ],
    EventType.EARNINGS: [
        # S级: 大幅增长
        ("扭亏", 1.0), ("预增", 0.95), ("翻倍", 1.0), ("暴增", 1.0),
        # A级: 业绩改善
        ("高送转", 0.85), ("净利润", 0.85),
        # B级: 常规
        ("业绩", 0.70), ("营收", 0.70), ("分红", 0.65),
        ("季报", 0.60), ("年报", 0.60),
    ],
    EventType.RESTRUCTURE: [
        # S级: 重大重组
        ("借壳", 1.0), ("注入", 0.95),
        # A级: 并购重组
        ("并购", 0.85), ("重组", 0.85), ("收购", 0.80),
        # B级: 资产相关
        ("资产", 0.70), ("股权转让", 0.70),
    ],
    EventType.NEWS: [
        # A级: 重大合同/订单
        ("中标", 0.85), ("订单", 0.85), ("签约", 0.80),
        # B级: 一般消息
        ("合作", 0.70), ("公告", 0.60), ("专利", 0.65),
    ],
}


def compute_event_weight(
    event_type: str,
    trading_days_since: int = 0,
    event_text: str = "",
    policy_level: str = PolicyLevel.UNKNOWN,
    order_amount_level: str = OrderAmountLevel.UNKNOWN,
) -> float:
    """动态事件权重 = 基础强度 × 事件级别 × 时间衰减.

    Parameters
    ----------
    event_type : 事件类型 (EventType.*)
    trading_days_since : 事件发布距今的**交易日**数 (0=当日)
    event_text : 公告标题/涨停原因, 用于匹配事件级别
    policy_level : 政策级别 (仅政策面事件有效)
    order_amount_level : 订单/合同金额级别 (仅消息面事件有效)

    Returns
    -------
    float : 动态权重 (0-1), 已乘以衰减
    """
    base = EVENT_BASE_STRENGTH.get(event_type, 0.40)

    # ── 1. 事件级别 (grade) ──
    grade = 0.70  # 默认 B 级
    grade_keywords = EVENT_GRADE_KEYWORDS.get(event_type, [])
    for keyword, kw_grade in grade_keywords:
        if keyword in event_text:
            grade = max(grade, kw_grade)  # 取最高匹配级别

    # 消息面 (NEWS): 用金额级别覆盖关键词级别 (金额更客观)
    if event_type == EventType.NEWS and order_amount_level != OrderAmountLevel.UNKNOWN:
        amount_grade = _AMOUNT_GRADE_MAP.get(order_amount_level, 0.65)
        grade = max(grade, amount_grade)

    # ── 2. 时间衰减 (exponential half-life decay, 交易日制) ──
    half_life = EVENT_DECAY_HALF_LIVES.get(event_type, 1.0)
    # 政策面: 按政策级别调整半衰期 (国家级持续更久)
    if event_type == EventType.POLICY:
        half_life *= _POLICY_HALF_LIFE_MULTIPLIER.get(policy_level, 1.0)

    if trading_days_since <= 0:
        decay = 1.0
    else:
        # decay = 0.5 ^ (trading_days / half_life)
        decay = math.pow(0.5, trading_days_since / half_life)

    return round(min(1.0, base * grade * decay), 4)


@dataclass(frozen=True)
class StockEvent:
    """单只股票的涨停事件分类结果 (三层识别)."""

    ts_code: str
    name: str
    lu_desc: str  # 原始涨停原因
    event_type: str  # 主事件类型
    event_types: tuple[str, ...]  # 所有命中的事件类型
    event_weight: float  # 事件权重 (0-1)
    theme: str  # 题材
    themes: tuple[str, ...]  # 拆分后的多题材
    # ── 三层识别增强 ──
    event_layer: str = "KEYWORD"  # ANNOUNCEMENT / CONCEPT / KEYWORD / LLM
    ann_title: str = ""  # 触发公告标题 (Layer 1)
    concepts: tuple[str, ...] = ()  # 所属概念 (Layer 2)
    diffusion_rate: float = 0.0  # 板块扩散率 (Layer 3, 0-1)
    # ── 事件强度建模 (v14) ──
    policy_level: str = PolicyLevel.UNKNOWN  # 政策级别 (仅政策面有效)
    order_amount_level: str = OrderAmountLevel.UNKNOWN  # 金额级别 (仅消息面有效)
    order_amount_wan: float | None = None  # 解析出的金额 (万元)


@dataclass(frozen=True)
class ThemeHeat:
    """题材热度追踪结果."""

    theme_name: str
    today_count: int  # 今日涨停股票数
    yesterday_count: int  # 昨日涨停股票数
    persistence_days: int  # 连续上榜天数
    heat_trend: str  # HEATING / STABLE / COOLING / NEW
    heat_score: float  # 综合热度评分 (0-100)
    leader_codes: tuple[str, ...]  # 龙头股票代码 (按高度+封单排序)
    leader_names: tuple[str, ...]  # 龙头股票名称
    # ── 生命周期 + 拥挤度 (v12) ──
    lifecycle: str = "NEW"        # NEW / HEATING / PEAK / FADING
    crowding_ratio: float = 0.0   # 拥挤度: 涨停数/板块成分总数 (0-1, 高=危险)
    crowding_penalty: float = 0.0 # 拥挤度惩罚 (0-30, 从热度中扣除)
    # ── 多维热度子分 (v13) ──
    max_height: int = 1           # 主线最高连板高度 (default=首板)
    height_score: float = 0.0     # 主线高度得分 (0-100)
    leader_score: float = 0.0     # 龙头强度得分 (0-100)
    expansion_score: float = 0.0  # 扩散速度得分 (0-100)
    participation_score: float = 0.0  # 可参与度得分 (0-100, 非一字板占比)


@dataclass(frozen=True)
class EventAnalysisResult:
    """事件驱动分析完整结果."""

    trade_date: date
    stock_events: tuple[StockEvent, ...]
    theme_heats: tuple[ThemeHeat, ...]
    # 事件类型分布
    event_distribution: dict[str, int]  # event_type -> count
    dominant_event_type: str  # 当日主导事件类型
    # 题材集中度
    theme_concentration: float  # top 3 themes / total (0-1, 越高越集中)
    market_narrative: str  # 今日市场叙事总结


@dataclass(frozen=True)
class StockSentimentScore:
    """个股情绪评分 (8因子增强版)."""

    ts_code: str
    name: str
    # 原始5因子
    volume_ratio_score: float  # 量比得分 (0-100)
    seal_order_score: float  # 封单强度得分 (0-100)
    bid_activity_score: float  # 竞价活跃度得分 (0-100)
    theme_heat_score: float  # 所属题材热度得分 (0-100)
    event_catalyst_score: float  # 事件催化得分 (0-100)
    # 新增3因子
    popularity_score: float = 50.0  # 同花顺热度排名得分 (0-100)
    northbound_score: float = 50.0  # 北向资金信号得分 (0-100)
    technical_form_score: float = 50.0  # 技术形态得分 (0-100)
    # 综合
    composite_score: float = 0.0  # 综合情绪得分 (0-100)
    factors: dict[str, float] = field(default_factory=dict)
