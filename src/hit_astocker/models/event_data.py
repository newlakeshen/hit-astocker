"""Event-driven and sentiment data models."""

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

# 事件类型权重：强催化 > 弱催化
EVENT_WEIGHTS: dict[str, float] = {
    EventType.POLICY: 1.0,  # 政策面最强
    EventType.RESTRUCTURE: 0.95,  # 重组并购持续性强
    EventType.EARNINGS: 0.85,  # 业绩面有基本面支撑
    EventType.INDUSTRY: 0.80,  # 行业面持续性好
    EventType.NEWS: 0.75,  # 消息面催化
    EventType.CONCEPT: 0.65,  # 概念炒作短期为主
    EventType.CAPITAL: 0.60,  # 资金面可能只是跟风
    EventType.TECHNICAL: 0.50,  # 技术面最弱
    EventType.UNKNOWN: 0.40,  # 未知原因
}


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
    event_layer: str = "KEYWORD"  # ANNOUNCEMENT / CONCEPT / KEYWORD
    ann_title: str = ""  # 触发公告标题 (Layer 1)
    concepts: tuple[str, ...] = ()  # 所属概念 (Layer 2)
    diffusion_rate: float = 0.0  # 板块扩散率 (Layer 3, 0-1)


@dataclass(frozen=True)
class ThemeHeat:
    """题材热度追踪结果."""

    theme_name: str
    today_count: int  # 今日涨停股票数
    yesterday_count: int  # 昨日涨停股票数
    persistence_days: int  # 连续上榜天数
    heat_trend: str  # HEATING / STABLE / COOLING / NEW
    heat_score: float  # 综合热度评分 (0-100)
    leader_codes: tuple[str, ...]  # 龙头股票代码
    leader_names: tuple[str, ...]  # 龙头股票名称


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
