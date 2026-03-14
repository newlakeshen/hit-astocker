"""赚钱效应分层模型 — 按板高度×涨跌幅类型量化打板赚钱效应.

核心思路: 打板赚钱效应不是铁板一块, 首板/2板/3板/空间板各有不同的
溢价特征和风险收益比. 把赚钱效应按高度分层量化, 替代经验阈值,
让 Stage1Filter 和 RiskAssessor 基于数据做决策而非硬编码.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class ProfitRegime(str, Enum):
    """赚钱效应 regime — 市场打板赚钱效应的强弱等级."""

    STRONG = "STRONG"      # 强赚钱效应: 多层溢价正、胜率高
    NORMAL = "NORMAL"      # 正常: 部分层有正溢价
    WEAK = "WEAK"          # 弱赚钱效应: 多层溢价负
    FROZEN = "FROZEN"      # 冰封: 全面亏钱效应


@dataclass(frozen=True)
class TierProfitEffect:
    """单一高度层的赚钱效应指标.

    指标分两部分:
    - 次日表现 (prev_*): 昨日N板 → 今日的表现 (量化赚钱效应)
    - 今日质量 (today_*): 今日N板的封板质量 (量化参与机会)
    """

    tier: str              # "首板" / "2板" / "3板" / "空间板"
    # ── 次日表现 (T-1的N板在T的表现) ──
    prev_count: int        # T-1该层样本数
    avg_premium: float     # 平均次日开盘溢价 (%)
    avg_return: float      # 平均次日收盘收益 (%)
    win_rate: float        # 次日胜率 (0-1)
    # ── 今日板质量 (T当天N板的质量) ──
    today_count: int       # T该层涨停+炸板总数
    broken_rate: float     # T该层炸板率 (0-1)
    non_yizi_rate: float   # T该层非一字率 (可参与度, 0-1)


@dataclass(frozen=True)
class ProfitEffectSnapshot:
    """赚钱效应分层快照 — 当日全量打板赚钱效应状态."""

    trade_date: date
    # 按高度分层 (总体)
    by_height: tuple[TierProfitEffect, ...]
    # 按高度 × 涨跌幅类型交叉分层
    by_height_10cm: tuple[TierProfitEffect, ...]
    by_height_20cm: tuple[TierProfitEffect, ...]
    # 总体指标
    overall_premium: float     # 总体次日溢价 (%)
    overall_win_rate: float    # 总体胜率 (0-1)
    overall_count: int         # 总样本数
    # Regime 判定
    regime: ProfitRegime
    regime_score: float        # 连续化评分 (0-100), 用于门控

    def tier_for_height(self, height: int) -> TierProfitEffect | None:
        """按实际高度查询对应层的指标."""
        tier_name = _height_to_tier(height)
        for t in self.by_height:
            if t.tier == tier_name:
                return t
        return None

    def tier_for_height_by_type(self, height: int, is_20cm: bool) -> TierProfitEffect | None:
        """按涨跌幅类型查询分层指标 (10cm 主板 / 20cm 创科板)."""
        tier_name = _height_to_tier(height)
        source = self.by_height_20cm if is_20cm else self.by_height_10cm
        for t in source:
            if t.tier == tier_name:
                return t
        return None


# ── height → tier 映射 ──

_TIER_NAMES = {1: "首板", 2: "2板", 3: "3板"}


def _height_to_tier(height: int) -> str:
    return _TIER_NAMES.get(height, "空间板")
