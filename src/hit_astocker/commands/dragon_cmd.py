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
    """Show dragon-tiger board analysis with quantified seat profiles."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        result = DragonTigerAnalyzer(conn).analyze(trade_date)

        if result.records:
            console.print(dragon_tiger_table(result))

            # Seat coordination summary
            coordinated = [
                (code, seat)
                for code, seat in result.seat_scores.items()
                if seat.is_coordinated
            ]
            if coordinated:
                names = ", ".join(
                    f"{code}({','.join(s.known_trader_names[:2])})"
                    for code, s in coordinated[:5]
                )
                console.print(f"\n  [bold red]游资合力: {names}[/]")

            # Top win-rate seats
            top_seats = sorted(
                result.seat_scores.items(),
                key=lambda x: x[1].max_win_rate,
                reverse=True,
            )[:3]
            if top_seats:
                parts = []
                for code, seat in top_seats:
                    best = seat.known_trader_names[0] if seat.known_trader_names else "?"
                    parts.append(f"{code}({best} {seat.max_win_rate:.0%})")
                console.print(f"  [cyan]高胜率席位: {', '.join(parts)}[/]")

            # Institution summary
            inst_buy = {k: v for k, v in result.institutional_net_buy.items() if v > 0}
            if inst_buy:
                console.print(f"  机构净买入个股: {len(inst_buy)}只")
        else:
            console.print("[dim]  无龙虎榜数据[/]")
