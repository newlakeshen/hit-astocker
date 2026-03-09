"""Sync command: pull data from Tushare."""

from datetime import date, datetime

import typer
from rich.console import Console
from rich.table import Table

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.fetchers.sync_orchestrator import SyncOrchestrator
from hit_astocker.utils.date_utils import from_tushare_date

sync_app = typer.Typer(name="sync", help="Sync data from Tushare")
console = Console()


@sync_app.callback(invoke_without_command=True)
def sync(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    start: str = typer.Option(None, "--start", help="Start date for range sync"),
    end: str = typer.Option(None, "--end", help="End date for range sync"),
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

        if start and end:
            start_date = from_tushare_date(start)
            end_date = from_tushare_date(end)
            console.print(f"Syncing date range: {start} ~ {end}")
            all_results = orchestrator.sync_date_range(start_date, end_date)
            total = sum(
                sum(v for v in day_results.values() if v > 0)
                for day_results in all_results.values()
            )
            console.print(f"[green]Sync complete: {len(all_results)} days, {total} total records[/]")
        else:
            if date_str:
                target = from_tushare_date(date_str)
            else:
                target = date.today()
                console.print(f"No date specified, using today: {target.strftime(TUSHARE_DATE_FMT)}")

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
