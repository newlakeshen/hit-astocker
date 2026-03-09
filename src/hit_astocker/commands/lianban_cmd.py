"""Consecutive board (连板) analysis command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.analyzers.lianban import LianbanAnalyzer
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.tables import lianban_table
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.utils.date_utils import from_tushare_date

lianban_app = typer.Typer(name="lianban", help="Consecutive board ladder analysis")
console = Console(theme=APP_THEME)


@lianban_app.callback(invoke_without_command=True)
def lianban(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    trend_days: int = typer.Option(10, "--trend", "-t", help="Trend lookback days"),
):
    """Show consecutive board ladder."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        result = LianbanAnalyzer(conn).analyze(trade_date, trend_days)

        console.print(lianban_table(result))

        if result.height_trend:
            trend_str = " -> ".join(str(h) for h in result.height_trend)
            console.print(f"\n  连板高度趋势 (近{trend_days}日): {trend_str}")

        if result.leader_code:
            console.print(
                f"  空间板龙头: [bold red]{result.leader_name}[/] "
                f"({result.leader_code}) [bold]{result.max_height}连板[/]"
            )

        console.print(f"  连板总数: {result.total_lianban_count}只")
        console.print(f"  平均晋级率: {result.avg_promotion_rate:.1%}")
