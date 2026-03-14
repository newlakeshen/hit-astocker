"""Market sentiment scoring engine (9-factor enhanced).

Factors:
1. up_down_ratio (涨跌停比)
2. broken_recovery (炸板/修复率)
3. promotion_rate (总晋级率)
4. height_promotion (高位晋级率: 2→3, 3→4)
5. max_height (连板高度)
6. prev_premium (昨日涨停次日溢价)
7. yizi_ratio (一字板占比)
8. board_structure (首板结构: 10cm/20cm)
9. auction_strength (竞价强弱)
"""

import sqlite3
from datetime import date

from hit_astocker.analyzers.market_context import MarketContextAnalyzer
from hit_astocker.config.constants import MAX_HEIGHT_NORM, SENTIMENT_LABELS
from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.index_data import MarketContext
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.repositories.auction_repo import AuctionRepository
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.repositories.limit_repo import LimitListRepository
from hit_astocker.repositories.limit_step_repo import LimitStepRepository
from hit_astocker.utils.date_utils import get_previous_trading_day


class SentimentAnalyzer:
    def __init__(
        self, conn: sqlite3.Connection, settings: Settings | None = None,
        *, limit_repo=None, step_repo=None,
    ):
        self._limit_repo = limit_repo or LimitListRepository(conn)
        self._step_repo = step_repo or LimitStepRepository(conn)
        self._bar_repo = DailyBarRepository(conn)
        self._auction_repo = AuctionRepository(conn)
        self._market_ctx_analyzer = MarketContextAnalyzer(conn)
        self._settings = settings or get_settings()

    def analyze(self, trade_date: date) -> SentimentScore:
        s = self._settings

        # ── Raw data collection ──
        counts = self._limit_repo.count_by_type(trade_date)
        up_count = counts.get("U", 0)
        down_count = counts.get("D", 0)
        broken_count_raw = counts.get("Z", 0)

        up_down_ratio = up_count / max(down_count, 1)
        broken_rate = broken_count_raw / max(up_count + broken_count_raw, 1)

        # 连板分析
        max_height = self._step_repo.get_max_height(trade_date)
        height_counts = self._step_repo.get_height_counts(trade_date)
        total_lianban = sum(height_counts.values())
        avg_height = (
            sum(h * c for h, c in height_counts.items()) / max(total_lianban, 1)
        )

        # 总晋级率 + 高位晋级率 (deduplicated: single pair of stock_heights calls)
        promotion_rate, promo_2to3, promo_3to4 = self._compute_all_promotions(trade_date)

        # 炸板修复率
        recovery_count, broken_stayed = self._limit_repo.count_recovery(trade_date)
        total_broken_event = recovery_count + broken_stayed
        broken_recovery_rate = recovery_count / max(total_broken_event, 1)

        # 一字板
        yizi_count = self._limit_repo.count_yizi(trade_date)
        yizi_ratio = yizi_count / max(up_count, 1)

        # 10cm/20cm 结构
        board_type = self._limit_repo.count_by_board_type(trade_date)

        # 昨日涨停次日溢价
        prev_premium = self._compute_prev_premium(trade_date)

        # 竞价强弱
        auction_stats = self._auction_repo.compute_auction_stats(trade_date)
        auction_avg_pct = auction_stats.get("avg_pct", 0.0)
        auction_up_ratio = auction_stats.get("up_ratio", 0.0)

        # ── Factor scoring (each 0-100) ──

        # F1: 涨跌停比 — 5:1 = 100
        f_ratio = min(up_down_ratio / 5.0 * 100, 100)

        # F2: 炸板修复率 — 高修复 = 好; 同时惩罚高炸板率
        f_broken_recovery = broken_recovery_rate * 60 + (1 - broken_rate) * 40

        # F3: 总晋级率
        f_promo = promotion_rate * 100

        # F4: 高位晋级率 — 2→3 和 3→4 的平均
        avg_high_promo = (promo_2to3 + promo_3to4) / 2
        f_height_promo = min(avg_high_promo / 0.5 * 100, 100)  # 50%晋级=100

        # F5: 连板高度
        f_height = min(max_height / MAX_HEIGHT_NORM * 100, 100)

        # F6: 昨日涨停次日溢价 — [-3%, +5%] → [0, 100]
        f_premium = max(0, min(100, (prev_premium + 3) / 8 * 100))

        # F7: 一字板占比 — 适中最好 (10-25% = 100, 太高说明无参与机会)
        if yizi_ratio <= 0.25:
            f_yizi = min(yizi_ratio / 0.25 * 100, 100)
        else:
            # 超过25%开始递减 (一字太多 = 无法参与)
            f_yizi = max(0, 100 - (yizi_ratio - 0.25) / 0.25 * 60)

        # F8: 首板结构 — 20cm 占比高说明市场偏好题材股
        total_up_board = board_type["10cm_up"] + board_type["20cm_up"]
        if total_up_board > 0:
            ratio_20cm = board_type["20cm_up"] / total_up_board
            # 20cm涨停多 → 题材活跃; 10cm涨停多 → 价值轮动
            # 评分基于总量 + 结构
            volume_score = min(total_up_board / 40 * 60, 60)  # 40个涨停=60分
            diversity_score = min(ratio_20cm / 0.4 * 40, 40)  # 20cm占40%=满分
            f_board_struct = volume_score + diversity_score
        else:
            f_board_struct = 0

        # F9: 竞价强弱 — 平均涨幅 + 高开比例
        pct_part = max(0, min(60, (auction_avg_pct + 1) / 3 * 60))  # [-1%,+2%]→[0,60]
        up_part = auction_up_ratio * 40  # 100%高开=40分
        f_auction = pct_part + up_part

        # ── Weighted composite ──
        factor_scores = {
            "ratio": f_ratio,
            "broken_recovery": f_broken_recovery,
            "promotion": f_promo,
            "height_promotion": f_height_promo,
            "height": f_height,
            "premium": f_premium,
            "yizi": f_yizi,
            "board_structure": f_board_struct,
            "auction": f_auction if auction_stats else None,
        }
        factor_weights = {
            "ratio": s.sentiment_up_down_ratio_weight,
            "broken_recovery": s.sentiment_broken_recovery_weight,
            "promotion": s.sentiment_promotion_rate_weight,
            "height_promotion": s.sentiment_height_promotion_weight,
            "height": s.sentiment_max_height_weight,
            "premium": s.sentiment_prev_premium_weight,
            "yizi": s.sentiment_yizi_ratio_weight,
            "board_structure": s.sentiment_board_structure_weight,
            "auction": s.sentiment_auction_strength_weight,
        }
        money_effect = self._weighted_factor_score(factor_scores, factor_weights)

        # Market context adjustment
        market_ctx = self._market_ctx_analyzer.analyze(trade_date)
        money_effect = self._apply_market_adjustment(money_effect, market_ctx)
        overall = max(0, min(100, money_effect))

        risk_level = self._determine_risk(overall, broken_rate)
        description = self._describe_market(overall)

        return SentimentScore(
            trade_date=trade_date,
            limit_up_count=up_count,
            limit_down_count=down_count,
            broken_count=broken_count_raw,
            up_down_ratio=round(up_down_ratio, 2),
            broken_rate=round(broken_rate, 4),
            max_consecutive_height=max_height,
            avg_consecutive_height=round(avg_height, 2),
            promotion_rate=round(promotion_rate, 4),
            money_effect_score=round(money_effect, 2),
            overall_score=round(overall, 2),
            risk_level=risk_level,
            description=description,
            prev_limit_up_premium=round(prev_premium, 2),
            recovery_count=recovery_count,
            broken_recovery_rate=round(broken_recovery_rate, 4),
            yizi_count=yizi_count,
            yizi_ratio=round(yizi_ratio, 4),
            limit_up_10cm=board_type["10cm_up"],
            limit_up_20cm=board_type["20cm_up"],
            broken_10cm=board_type["10cm_broken"],
            broken_20cm=board_type["20cm_broken"],
            promo_rate_2to3=round(promo_2to3, 4),
            promo_rate_3to4=round(promo_3to4, 4),
            auction_avg_pct=round(auction_avg_pct, 2),
            auction_up_ratio=round(auction_up_ratio, 4),
            market_context=market_ctx,
        )

    def _compute_all_promotions(self, trade_date: date) -> tuple[float, float, float]:
        """Compute (总晋级率, 2→3晋级率, 3→4晋级率).

        Merged from _compute_promotion_rate + _compute_height_promotion
        to eliminate redundant get_stock_heights calls (was 4 SQL → now 2).
        """
        prev_date = get_previous_trading_day(trade_date)
        if prev_date is None:
            return 0.0, 0.0, 0.0

        yesterday_heights = self._step_repo.get_stock_heights(prev_date)
        if not yesterday_heights:
            return 0.0, 0.0, 0.0

        today_heights = self._step_repo.get_stock_heights(trade_date)

        # Overall promotion rate
        promoted = sum(
            1
            for code, prev_h in yesterday_heights.items()
            if today_heights.get(code) == prev_h + 1
        )
        promotion_rate = promoted / len(yesterday_heights)

        # Height-specific promotions
        def _promo(from_h: int) -> float:
            candidates = [c for c, h in yesterday_heights.items() if h == from_h]
            if not candidates:
                return 0.0
            p = sum(1 for c in candidates if today_heights.get(c) == from_h + 1)
            return p / len(candidates)

        return promotion_rate, _promo(2), _promo(3)

    def _compute_prev_premium(self, trade_date: date) -> float:
        """Compute average premium of yesterday's limit-up stocks at today's open.

        prev_premium = avg((T open - T-1 close) / T-1 close * 100)
        """
        prev_date = get_previous_trading_day(trade_date)
        if prev_date is None:
            return 0.0

        prev_closes = self._limit_repo.get_prev_limit_up_closes(prev_date)
        if not prev_closes:
            return 0.0

        # Batch load today's bars for these stocks
        codes = list(prev_closes.keys())
        today_bars = self._bar_repo.find_recent_bars_batch(codes, trade_date, count=1)

        premiums = []
        for code, prev_close in prev_closes.items():
            bars = today_bars.get(code, [])
            if not bars or prev_close <= 0:
                continue
            today_bar = bars[-1]
            if today_bar.trade_date != trade_date:
                continue
            premium = (today_bar.open - prev_close) / prev_close * 100
            premiums.append(premium)

        return sum(premiums) / len(premiums) if premiums else 0.0

    @staticmethod
    def _weighted_factor_score(
        scores: dict[str, float | None],
        weights: dict[str, float],
    ) -> float:
        available = [(key, score) for key, score in scores.items() if score is not None]
        if not available:
            return 0.0
        total_weight = sum(weights[key] for key, _ in available)
        if total_weight <= 0:
            return 0.0
        return sum(weights[key] / total_weight * score for key, score in available)

    def _determine_risk(self, score: float, broken_rate: float) -> str:
        s = self._settings
        if score < s.risk_extreme_score or broken_rate > s.risk_extreme_broken_rate:
            return "EXTREME"
        if score < s.risk_high_score or broken_rate > s.risk_high_broken_rate:
            return "HIGH"
        if score < s.risk_medium_score:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _apply_market_adjustment(score: float, ctx: MarketContext | None) -> float:
        """Adjust sentiment score based on market index context."""
        if ctx is None:
            return score

        adjustment = 0.0
        avg_pct = (ctx.sh_pct_chg + ctx.gem_pct_chg) / 2
        if avg_pct <= -2.0:
            adjustment -= 15.0
        elif avg_pct <= -1.0:
            adjustment -= 8.0
        elif avg_pct >= 2.0:
            adjustment += 10.0
        elif avg_pct >= 1.0:
            adjustment += 5.0

        if ctx.sh_ma20_ratio >= 1.02:
            adjustment += 5.0
        elif ctx.sh_ma20_ratio <= 0.97:
            adjustment -= 8.0

        return score + adjustment

    @staticmethod
    def _describe_market(score: float) -> str:
        for (low, high), label in SENTIMENT_LABELS.items():
            if low <= score < high:
                return label
        return "未知 (Unknown)"
