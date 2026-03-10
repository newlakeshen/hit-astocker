"""Hot money (游资) data models.

hm_list — static trader roster with associated broker seats.
hm_detail — daily trading detail per trader per stock.
SeatScore — quantified per-stock seat analysis for scoring.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HmTrader:
    """A known hot money trader from hm_list."""

    hm_name: str
    desc: str
    orgs: str  # comma-separated associated broker seats


@dataclass(frozen=True)
class HmDetailRecord:
    """Single hot money trade record from hm_detail."""

    trade_date: date
    ts_code: str
    ts_name: str
    buy_amount: float  # 买入金额 (元)
    sell_amount: float  # 卖出金额 (元)
    net_amount: float  # 净买卖额 (元)
    hm_name: str
    hm_orgs: str
    tag: str


@dataclass(frozen=True)
class TraderProfile:
    """Historical stats for a single hot money trader (lookback window)."""

    hm_name: str
    total_buys: int  # number of net-buy trades
    win_count: int  # T+1 pct_chg > 0
    win_rate: float  # win_count / total_buys
    avg_premium: float  # average T+1 pct_chg
    active_days: int  # distinct trading days in window


@dataclass(frozen=True)
class SeatScore:
    """Quantified hot money analysis for a single stock on a single day."""

    known_trader_count: int
    known_trader_names: tuple[str, ...]
    known_net_amount: float  # total net from known traders (元)
    max_win_rate: float  # best trader's historical win rate (0-1)
    avg_win_rate: float  # average win rate of involved traders
    is_coordinated: bool  # 2+ known traders on buy side
    primary_tag: str  # tag from the highest-win-rate trader
    avg_premium: float  # avg historical T+1 premium of involved traders
