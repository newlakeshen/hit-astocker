"""Daily dashboard command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.analyzers.dragon_tiger import DragonTigerAnalyzer
from hit_astocker.analyzers.event_classifier import EventClassifier
from hit_astocker.analyzers.firstboard import FirstBoardAnalyzer
from hit_astocker.analyzers.lianban import LianbanAnalyzer
from hit_astocker.analyzers.sector_rotation import SectorRotationAnalyzer
from hit_astocker.analyzers.sentiment import SentimentAnalyzer
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.dashboard import render_dashboard
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.signals.signal_generator import SignalGenerator
from hit_astocker.utils.date_utils import from_tushare_date

daily_app = typer.Typer(name="daily", help="Full daily analysis dashboard")
console = Console(theme=APP_THEME)


@daily_app.callback(invoke_without_command=True)
def daily(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
):
    """Show full daily analysis dashboard."""
    settings = get_settings()

    if date_str:
        trade_date = from_tushare_date(date_str)
    else:
        trade_date = date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        # Check if data exists
        from hit_astocker.repositories.limit_repo import LimitListRepository
        repo = LimitListRepository(conn)
        counts = repo.count_by_type(trade_date)
        if sum(counts.values()) == 0:
            console.print(f"[yellow]No data for {trade_date}. Run 'hit-astocker sync -d {date_str or trade_date.strftime('%Y%m%d')}' first.[/]")
            raise typer.Exit(1)

        # Run analyses sequentially (single connection — not thread-safe)
        sentiment = SentimentAnalyzer(conn, settings).analyze(trade_date)
        firstboard = FirstBoardAnalyzer(conn, settings).analyze(trade_date)
        lianban = LianbanAnalyzer(conn).analyze(trade_date)
        sector = SectorRotationAnalyzer(conn).analyze(trade_date)
        dragon = DragonTigerAnalyzer(conn).analyze(trade_date)
        event_result = EventClassifier(conn).analyze(trade_date)
        signals = SignalGenerator(conn, settings).generate(trade_date)

        render_dashboard(
            console, sentiment, firstboard, lianban, sector, dragon, signals,
            event_result=event_result,
        )
