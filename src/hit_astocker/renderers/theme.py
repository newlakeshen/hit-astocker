"""Color theme for terminal output.

Chinese market convention: RED = up (涨), GREEN = down (跌).
"""

from rich.style import Style
from rich.theme import Theme

# Color constants
RED = "bold red"  # 涨/bullish
GREEN = "bold green"  # 跌/bearish
YELLOW = "bold yellow"  # Warning
WHITE = "bold white"
DIM = "dim"
CYAN = "bold cyan"
MAGENTA = "bold magenta"

# Score-based colors
SCORE_COLORS = {
    (80, 101): "bold red",      # Excellent
    (65, 80): "red",            # Good
    (50, 65): "yellow",         # Average
    (40, 50): "white",          # Neutral
    (25, 40): "green",          # Cool
    (0, 25): "bold green",      # Cold
}

RISK_COLORS = {
    "LOW": "bold green",
    "MEDIUM": "bold yellow",
    "HIGH": "bold red",
    "EXTREME": "bold red on white",
    "NO_GO": "bold white on red",
}

FLOW_COLORS = {
    "STRONG_IN": "bold red",
    "WEAK_IN": "red",
    "NEUTRAL": "white",
    "WEAK_OUT": "green",
    "STRONG_OUT": "bold green",
}

APP_THEME = Theme({
    "up": RED,
    "down": GREEN,
    "warn": YELLOW,
    "info": CYAN,
    "header": "bold cyan",
    "title": "bold white",
    "dim": DIM,
})


def score_color(score: float) -> str:
    for (low, high), color in SCORE_COLORS.items():
        if low <= score < high:
            return color
    return "white"


def risk_color(risk_level: str) -> str:
    return RISK_COLORS.get(risk_level, "white")


def pct_color(pct: float) -> str:
    if pct > 0:
        return RED
    if pct < 0:
        return GREEN
    return WHITE


def format_amount(amount: float) -> str:
    """Format amount in 万/亿."""
    if abs(amount) >= 10000:
        return f"{amount / 10000:.2f}亿"
    return f"{amount:.0f}万"
