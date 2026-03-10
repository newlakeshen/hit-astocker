from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

_WEIGHT_TOLERANCE = 0.001  # allow tiny float rounding error


class Settings(BaseSettings):
    tushare_token: str = ""
    db_path: Path = Path("data/hit_astocker.db")

    # Sentiment scoring weights (5-factor, sum=1)
    sentiment_up_down_ratio_weight: float = 0.30
    sentiment_broken_rate_weight: float = 0.25
    sentiment_promotion_rate_weight: float = 0.20
    sentiment_max_height_weight: float = 0.15
    sentiment_first_board_trend_weight: float = 0.10

    # Risk thresholds
    risk_extreme_score: float = 20.0
    risk_high_score: float = 40.0
    risk_medium_score: float = 65.0
    risk_extreme_broken_rate: float = 0.6
    risk_high_broken_rate: float = 0.5

    # Signal thresholds
    signal_min_sentiment: float = 60.0
    signal_min_first_board_score: float = 70.0
    signal_top_sector_count: int = 3

    # First board scoring weights (5-factor, sum=1)
    first_board_seal_time_weight: float = 0.25
    first_board_seal_strength_weight: float = 0.20
    first_board_purity_weight: float = 0.20
    first_board_turnover_weight: float = 0.15
    first_board_sector_weight: float = 0.20

    # ── FIRST_BOARD 首板弱转强/回封 (10-factor, sum=1) ──
    # 核心: 封板质量决定首板打板成功率
    fb_sentiment_weight: float = 0.12
    fb_seal_quality_weight: float = 0.22
    fb_sector_weight: float = 0.12
    fb_survival_weight: float = 0.06
    fb_capital_flow_weight: float = 0.08
    fb_dragon_tiger_weight: float = 0.05
    fb_event_catalyst_weight: float = 0.10
    fb_stock_sentiment_weight: float = 0.08
    fb_northbound_weight: float = 0.05
    fb_technical_form_weight: float = 0.12

    # ── FOLLOW_BOARD 2-3板接力 (10-factor, sum=1) ──
    # 核心: 连板生存率 + 高度动能决定接力成功率
    fl_sentiment_weight: float = 0.10
    fl_survival_weight: float = 0.22
    fl_height_momentum_weight: float = 0.15
    fl_sector_weight: float = 0.10
    fl_capital_flow_weight: float = 0.05
    fl_dragon_tiger_weight: float = 0.08
    fl_event_catalyst_weight: float = 0.05
    fl_stock_sentiment_weight: float = 0.12
    fl_northbound_weight: float = 0.05
    fl_technical_form_weight: float = 0.08

    # ── SECTOR_LEADER 空间板龙头 (10-factor, sum=1) ──
    # 核心: 板块热度 + 龙头地位决定空间板高度
    sl_sentiment_weight: float = 0.10
    sl_theme_heat_weight: float = 0.22
    sl_leader_position_weight: float = 0.15
    sl_sector_weight: float = 0.08
    sl_capital_flow_weight: float = 0.08
    sl_dragon_tiger_weight: float = 0.10
    sl_event_catalyst_weight: float = 0.12
    sl_stock_sentiment_weight: float = 0.07
    sl_northbound_weight: float = 0.05
    sl_technical_form_weight: float = 0.03

    # Board survival analysis
    survival_lookback_years: int = 10

    # API settings
    api_batch_size: int = 50
    api_timeout: int = 120

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _check_weight_sums(self) -> "Settings":
        groups = {
            "sentiment": [
                self.sentiment_up_down_ratio_weight,
                self.sentiment_broken_rate_weight,
                self.sentiment_promotion_rate_weight,
                self.sentiment_max_height_weight,
                self.sentiment_first_board_trend_weight,
            ],
            "first_board": [
                self.first_board_seal_time_weight,
                self.first_board_seal_strength_weight,
                self.first_board_purity_weight,
                self.first_board_turnover_weight,
                self.first_board_sector_weight,
            ],
            "fb (FIRST_BOARD)": [
                self.fb_sentiment_weight, self.fb_seal_quality_weight,
                self.fb_sector_weight, self.fb_survival_weight,
                self.fb_capital_flow_weight, self.fb_dragon_tiger_weight,
                self.fb_event_catalyst_weight, self.fb_stock_sentiment_weight,
                self.fb_northbound_weight, self.fb_technical_form_weight,
            ],
            "fl (FOLLOW_BOARD)": [
                self.fl_sentiment_weight, self.fl_survival_weight,
                self.fl_height_momentum_weight, self.fl_sector_weight,
                self.fl_capital_flow_weight, self.fl_dragon_tiger_weight,
                self.fl_event_catalyst_weight, self.fl_stock_sentiment_weight,
                self.fl_northbound_weight, self.fl_technical_form_weight,
            ],
            "sl (SECTOR_LEADER)": [
                self.sl_sentiment_weight, self.sl_theme_heat_weight,
                self.sl_leader_position_weight, self.sl_sector_weight,
                self.sl_capital_flow_weight, self.sl_dragon_tiger_weight,
                self.sl_event_catalyst_weight, self.sl_stock_sentiment_weight,
                self.sl_northbound_weight, self.sl_technical_form_weight,
            ],
        }
        for name, weights in groups.items():
            total = sum(weights)
            if abs(total - 1.0) > _WEIGHT_TOLERANCE:
                raise ValueError(
                    f"{name} weights sum to {total:.4f}, expected 1.0"
                )
        return self


def get_settings() -> Settings:
    return Settings()
