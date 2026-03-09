from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    tushare_token: str = ""
    db_path: Path = Path("data/hit_astocker.db")

    # Sentiment scoring weights
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

    # First board scoring weights
    first_board_seal_time_weight: float = 0.25
    first_board_seal_strength_weight: float = 0.20
    first_board_purity_weight: float = 0.20
    first_board_turnover_weight: float = 0.15
    first_board_sector_weight: float = 0.20

    # Composite scoring weights (10-factor)
    composite_sentiment_weight: float = 0.17
    composite_seal_quality_weight: float = 0.16
    composite_sector_weight: float = 0.12
    composite_lianban_survival_weight: float = 0.08
    composite_capital_flow_weight: float = 0.07
    composite_dragon_tiger_weight: float = 0.07
    composite_event_catalyst_weight: float = 0.10
    composite_stock_sentiment_weight: float = 0.10
    composite_northbound_weight: float = 0.07
    composite_technical_form_weight: float = 0.06

    # Board survival analysis
    survival_lookback_years: int = 10

    # API rate limiting
    api_calls_per_minute: int = 200

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


def get_settings() -> Settings:
    return Settings()
