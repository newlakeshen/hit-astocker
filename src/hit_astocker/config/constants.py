"""Trading constants for A-stock market."""

# Limit-up percentages by board type
MAIN_BOARD_LIMIT_PCT = 10.0  # 主板涨停比例
GEM_LIMIT_PCT = 20.0  # 创业板涨停比例 (Growth Enterprise Market)
STAR_LIMIT_PCT = 20.0  # 科创板涨停比例 (STAR Market)
ST_LIMIT_PCT = 5.0  # ST股涨停比例
BJ_LIMIT_PCT = 30.0  # 北交所涨停比例

# Trading hours
MARKET_OPEN = "09:30"
MORNING_CLOSE = "11:30"
AFTERNOON_OPEN = "13:00"
MARKET_CLOSE = "15:00"

# Seal time quality buckets (for first-board scoring)
SEAL_TIME_EXCELLENT = "10:00"  # Before 10:00 = excellent
SEAL_TIME_GOOD = "10:30"  # 10:00-10:30 = good
SEAL_TIME_AVERAGE = "13:00"  # 10:30-13:00 = average
# After 13:00 = weak

SEAL_TIME_SCORES = {
    "excellent": 100,  # Before 10:00
    "good": 75,  # 10:00-10:30
    "average": 50,  # 10:30-13:00
    "weak": 25,  # After 13:00
}

# Board purity scores (by open_times)
PURITY_SCORES = {
    0: 100,  # One-shot seal (一封到底)
    1: 70,  # Opened once
    2: 40,  # Opened twice
}
PURITY_DEFAULT_SCORE = 15  # 3+ opens

# Risk level labels
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_EXTREME = "EXTREME"
RISK_NO_GO = "NO_GO"

# Market sentiment descriptions
SENTIMENT_LABELS = {
    (80, 101): "极度狂热 (Extreme Frenzy)",
    (65, 80): "高涨 (Bullish)",
    (50, 65): "偏暖 (Warm)",
    (40, 50): "中性 (Neutral)",
    (25, 40): "偏冷 (Cool)",
    (10, 25): "冰点 (Freezing)",
    (0, 10): "极度恐慌 (Extreme Panic)",
}

# Date format used by Tushare
TUSHARE_DATE_FMT = "%Y%m%d"

# Maximum consecutive height normalization
MAX_HEIGHT_NORM = 7  # 7+ boards = 100 score

# Minimum trading days for new stock filter
NEW_STOCK_MIN_DAYS = 60
