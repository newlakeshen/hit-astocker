"""Daily dashboard command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.models.daily_context import build_daily_context
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

        # Build context ONCE — all analyzers run here
        ctx = build_daily_context(conn, settings, trade_date)

        # Generate signals from pre-computed context (no re-computation)
        signals = SignalGenerator(conn, settings).generate_from_context(ctx)

        render_dashboard(
            console,
            ctx.sentiment,
            list(ctx.firstboard),
            ctx.lianban,
            ctx.sector,
            ctx.dragon,
            signals,
            event_result=ctx.event,
        )
