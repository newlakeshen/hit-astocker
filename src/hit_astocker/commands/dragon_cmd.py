"""Dragon-tiger board analysis command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.analyzers.dragon_tiger import DragonTigerAnalyzer
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.tables import dragon_tiger_table
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.utils.date_utils import from_tushare_date

dragon_app = typer.Typer(name="dragon", help="Dragon-tiger board analysis")
console = Console(theme=APP_THEME)


@dragon_app.callback(invoke_without_command=True)
def dragon(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
):
    """Show dragon-tiger board analysis."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        result = DragonTigerAnalyzer(conn).analyze(trade_date)

        if result.records:
            console.print(dragon_tiger_table(result))

            if result.cooperation_flags:
                console.print(f"\n  [bold red]游资合力个股: {', '.join(result.cooperation_flags)}[/]")

            # Institution summary
            if result.institutional_net_buy:
                inst_buy = {k: v for k, v in result.institutional_net_buy.items() if v > 0}
                if inst_buy:
                    console.print(f"  机构净买入个股: {len(inst_buy)}只")
        else:
            console.print("[dim]  无龙虎榜数据[/]")
