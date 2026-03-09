"""Sector rotation analysis command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.analyzers.sector_rotation import SectorRotationAnalyzer
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.tables import sector_table
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.utils.date_utils import from_tushare_date

sector_app = typer.Typer(name="sector", help="Sector rotation analysis")
console = Console(theme=APP_THEME)


@sector_app.callback(invoke_without_command=True)
def sector(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    top_n: int = typer.Option(10, "--top", "-n", help="Number of top sectors"),
):
    """Show sector rotation analysis."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        result = SectorRotationAnalyzer(conn).analyze(trade_date, top_n)

        console.print(sector_table(result))

        if result.rotation_detected:
            console.print("\n  [yellow]! 检测到板块轮动![/]")

        if result.new_sectors:
            console.print(f"  新进板块: [bold]{', '.join(result.new_sectors)}[/]")
        if result.dropped_sectors:
            console.print(f"  掉出板块: [dim]{', '.join(result.dropped_sectors)}[/]")
        if result.continuing_sectors:
            console.print(f"  持续板块: [bold red]{', '.join(result.continuing_sectors)}[/]")

        # Show sector leaders
        for sector_name, codes in result.sector_leaders.items():
            if codes:
                console.print(f"  {sector_name} 龙头: {', '.join(codes[:3])}")
