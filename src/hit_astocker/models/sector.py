from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class SectorStrength:
    ts_code: str  # 板块代码
    name: str  # 板块名称
    trade_date: date
    days: int  # 上榜天数
    up_stat: str  # 连板高度
    cons_nums: int  # 连板股票数
    up_nums: int  # 涨停股票数
    pct_chg: float  # 涨跌幅
    rank: str  # 热度排名


@dataclass(frozen=True)
class SectorRotationResult:
    trade_date: date
    top_sectors: tuple[SectorStrength, ...]
    continuing_sectors: tuple[str, ...]  # 连续上榜板块名
    new_sectors: tuple[str, ...]  # 新进板块名
    dropped_sectors: tuple[str, ...]  # 掉出板块名
    rotation_detected: bool
    sector_leaders: dict[str, tuple[str, ...]] = field(default_factory=dict)  # sector -> leader codes
