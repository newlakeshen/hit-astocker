"""First-board analysis command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.analyzers.firstboard import FirstBoardAnalyzer
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.tables import firstboard_table
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.utils.date_utils import from_tushare_date

firstboard_app = typer.Typer(name="firstboard", help="First-board (首板) analysis")
console = Console(theme=APP_THEME)


@firstboard_app.callback(invoke_without_command=True)
def firstboard(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    top_n: int = typer.Option(20, "--top", "-n", help="Top N results"),
):
    """Show first-board analysis ranking."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        results = FirstBoardAnalyzer(conn, settings).analyze(trade_date)

        if results:
            console.print(firstboard_table(results[:top_n]))
            console.print(f"\n  共 {len(results)} 只首板, 显示前 {min(top_n, len(results))} 只")
        else:
            console.print("[dim]  无首板数据[/]")
