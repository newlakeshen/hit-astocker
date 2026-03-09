"""Prediction command: generate buy/sell stock recommendations."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.analyzers.predictor import StockPredictor
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.prediction_view import render_prediction_report
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.utils.date_utils import from_tushare_date

predict_app = typer.Typer(name="predict", help="Stock buy/sell prediction")
console = Console(theme=APP_THEME)


@predict_app.callback(invoke_without_command=True)
def predict(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    top_n: int = typer.Option(20, "--top", "-n", help="Top N candidates"),
):
    """Generate buy/sell stock predictions based on money flow factors."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        # Check if detailed flow data exists
        from hit_astocker.repositories.moneyflow_detail_repo import MoneyFlowDetailRepository
        detail_repo = MoneyFlowDetailRepository(conn)
        count = detail_repo.count_by_date(trade_date.strftime("%Y%m%d"))
        if count == 0:
            console.print(
                f"[yellow]No detailed money flow data for {trade_date}. "
                f"Run 'hit-astocker sync -d {date_str or trade_date.strftime('%Y%m%d')}' first.[/]"
            )
            raise typer.Exit(1)

        predictor = StockPredictor(conn, settings)
        report = predictor.predict(trade_date, top_n)

        render_prediction_report(console, report)
