from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    NO_GO = "NO_GO"


class SignalType(str, Enum):
    FIRST_BOARD = "FIRST_BOARD"  # 首板打板
    FOLLOW_BOARD = "FOLLOW_BOARD"  # 连板跟进
    SECTOR_LEADER = "SECTOR_LEADER"  # 板块龙头


@dataclass(frozen=True)
class TradingSignal:
    trade_date: date
    ts_code: str
    name: str
    signal_type: SignalType
    composite_score: float  # 综合评分 (0-100)
    risk_level: RiskLevel
    position_hint: str  # FULL / HALF / QUARTER / ZERO
    factors: dict[str, float] = field(default_factory=dict)  # 各因子得分
    reason: str = ""  # 信号理由
    score_source: str = "rules"  # "rules" (规则打分) / "model" (ML模型)
