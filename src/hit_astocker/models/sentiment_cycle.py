"""Sentiment cycle model — multi-day emotion phase detection.

A-share 打板 sentiment follows a recognizable cycle:
  ICE → REPAIR → FERMENT → CLIMAX → DIVERGE → RETREAT → ICE

Knowing *where* we are in the cycle is more important than the
absolute sentiment score.  A score of 50 rising from 30 (REPAIR)
has very different implications from a score of 50 falling from 70
(DIVERGE).
"""

from dataclasses import dataclass
from enum import Enum


class CyclePhase(str, Enum):
    """情绪周期六阶段."""

    ICE = "ICE"            # 冰点: 极度恐慌, 涨停少/炸板多, 赚钱效应极差
    REPAIR = "REPAIR"      # 修复: 情绪触底回升, 龙头率先企稳, 溢价由负转正
    FERMENT = "FERMENT"    # 发酵: 赚钱效应扩散, 连板高度渐升, 题材开始聚焦
    CLIMAX = "CLIMAX"      # 高潮: 涨停爆量, 一字板增多, 题材高度集中
    DIVERGE = "DIVERGE"    # 分歧: 炸板增多, 晋级率下降, 溢价开始走弱
    RETREAT = "RETREAT"    # 退潮: 全面亏钱效应, 连板断裂, 补跌加速


# ── Phase descriptions (for CLI output) ──
CYCLE_PHASE_LABELS: dict[str, str] = {
    "ICE": "冰点",
    "REPAIR": "修复",
    "FERMENT": "发酵",
    "CLIMAX": "高潮",
    "DIVERGE": "分歧",
    "RETREAT": "退潮",
}

CYCLE_PHASE_HINTS: dict[str, str] = {
    "ICE": "极度谨慎, 仅博龙头反包",
    "REPAIR": "轻仓试探, 紧止损",
    "FERMENT": "正常参与, 跟随主线",
    "CLIMAX": "只做最强确定性, 警惕见顶",
    "DIVERGE": "减仓观望, 回避首板",
    "RETREAT": "空仓等待, 不参与",
}


@dataclass(frozen=True)
class SentimentCycle:
    """多日情绪周期分析结果."""

    phase: CyclePhase
    # ── 趋势指标 ──
    score_ma3: float          # 3日情绪滑动均线
    score_ma5: float          # 5日情绪滑动均线
    score_delta: float        # 一阶导: T - T-1 (正=改善)
    score_accel: float        # 二阶导: delta_T - delta_{T-1} (正=加速改善)
    premium_trend: float      # 溢价3日趋势斜率 (正=溢价回升)
    broken_rate_trend: float  # 炸板率3日趋势斜率 (正=恶化)
    # ── 近期序列 (最新在前, 最多5日) ──
    recent_scores: tuple[float, ...]
    recent_premiums: tuple[float, ...]
    recent_broken_rates: tuple[float, ...]
    # ── 转折信号 ──
    is_turning_point: bool    # 是否处于拐点 (修复首日 / 退潮首日)
    phase_description: str    # 人可读周期描述
