"""Sync command: pull data from Tushare."""

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.fetchers.sync_orchestrator import SyncOrchestrator
from hit_astocker.utils.date_utils import from_tushare_date, shift_years

sync_app = typer.Typer(name="sync", help="Sync data from Tushare")
console = Console()


@sync_app.callback(invoke_without_command=True)
def sync(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    start: str = typer.Option(None, "--start", help="Start date for range sync"),
    end: str = typer.Option(None, "--end", help="End date for range sync"),
    years: int | None = typer.Option(
        None,
        "--years",
        help="Sync trailing N years ending at --date/today",
    ),
    api: str = typer.Option(None, "--api", help="Specific API to sync"),
):
    """Sync market data from Tushare Pro."""
    settings = get_settings()
    if not settings.tushare_token:
        console.print("[red]Error: TUSHARE_TOKEN not set. Check .env file.[/]")
        raise typer.Exit(1)

    apis = [api] if api else None

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        orchestrator = SyncOrchestrator(settings, conn)

        # Ensure trade calendar is populated (fetches from Tushare if empty)
        orchestrator.ensure_trade_calendar()

        range_start, range_end = _resolve_sync_range(date_str, start, end, years)

        if range_start and range_end:
            start_date = range_start
            end_date = range_end
            day_span = (end_date - start_date).days
            console.print(
                "Syncing date range: "
                f"{start_date.strftime(TUSHARE_DATE_FMT)} ~ "
                f"{end_date.strftime(TUSHARE_DATE_FMT)}"
            )

            if day_span > 5:
                # Use bulk batch mode for large ranges (>5 days)
                results = orchestrator.sync_date_range_bulk(start_date, end_date, apis)
                total = sum(v for v in results.values() if v > 0)
                console.print(f"[green]Sync complete: {total} total records[/]")
            else:
                # Small range: use per-day mode
                all_results = orchestrator.sync_date_range(start_date, end_date)
                total = sum(
                    sum(v for v in day_results.values() if v > 0)
                    for day_results in all_results.values()
                )
                console.print(
                    f"[green]Sync complete: {len(all_results)} days, {total} total records[/]"
                )
        else:
            if date_str:
                target = from_tushare_date(date_str)
            else:
                target = date.today()
                console.print(
                    f"No date specified, using today: {target.strftime(TUSHARE_DATE_FMT)}"
                )

            console.print(f"Syncing data for {target.strftime(TUSHARE_DATE_FMT)}...")
            results = orchestrator.sync_date(target, apis)

            # Summary table
            table = Table(title="Sync Results", show_header=True, header_style="bold cyan")
            table.add_column("API", width=20)
            table.add_column("Records", justify="right", width=10)
            table.add_column("Status", width=10)

            for api_name, count in results.items():
                if count < 0:
                    table.add_row(api_name, "-", "[red]FAILED[/]")
                elif count == 0:
                    table.add_row(api_name, "0", "[yellow]EMPTY[/]")
                else:
                    table.add_row(api_name, str(count), "[green]OK[/]")

            console.print(table)


def _resolve_sync_range(
    date_str: str | None,
    start: str | None,
    end: str | None,
    years: int | None,
) -> tuple[date | None, date | None]:
    if start and end:
        return from_tushare_date(start), from_tushare_date(end)

    if start or end:
        console.print("[red]Error: --start and --end must be provided together.[/]")
        raise typer.Exit(1)

    if years is None:
        return None, None

    if years <= 0:
        console.print("[red]Error: --years must be a positive integer.[/]")
        raise typer.Exit(1)

    end_date = from_tushare_date(date_str) if date_str else date.today()
    start_date = shift_years(end_date, -years)
    return start_date, end_date
