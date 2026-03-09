"""Sentiment analysis command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.analyzers.sentiment import SentimentAnalyzer
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.tables import sentiment_table
from hit_astocker.renderers.theme import APP_THEME, pct_color, score_color
from hit_astocker.utils.date_utils import from_tushare_date, get_recent_trading_days

sentiment_app = typer.Typer(name="sentiment", help="Market sentiment analysis")
console = Console(theme=APP_THEME)


@sentiment_app.callback(invoke_without_command=True)
def sentiment(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    days: int = typer.Option(5, "--days", "-n", help="Trailing days for trend"),
):
    """Show market sentiment analysis."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        analyzer = SentimentAnalyzer(conn, settings)

        # Current day
        current = analyzer.analyze(trade_date)
        console.print(sentiment_table(current))

        # Market context (大盘联动)
        ctx = current.market_context
        if ctx:
            console.print(f"\n  大盘环境: [{score_color(50 + ctx.regime_score / 2)}]{ctx.market_regime}[/]"
                          f"  上证 [{pct_color(ctx.sh_pct_chg)}]{ctx.sh_pct_chg:+.2f}%[/]"
                          f"  创业板 [{pct_color(ctx.gem_pct_chg)}]{ctx.gem_pct_chg:+.2f}%[/]"
                          f"  MA5比 {ctx.sh_ma5_ratio:.4f}  MA20比 {ctx.sh_ma20_ratio:.4f}")

        # Trailing trend
        if days > 1:
            recent = get_recent_trading_days(trade_date, days - 1)
            console.print(f"\n  近{days}日情绪趋势:")
            for d in reversed(recent):
                try:
                    s = analyzer.analyze(d)
                    bar = "█" * int(s.overall_score / 5)
                    console.print(
                        f"  {d}  [{score_color(s.overall_score)}]{bar} {s.overall_score:.1f}[/]  {s.description}"
                    )
                except Exception:
                    console.print(f"  {d}  [dim]无数据[/]")

            bar = "█" * int(current.overall_score / 5)
            console.print(
                f"  {trade_date}  [{score_color(current.overall_score)}]{bar} {current.overall_score:.1f}[/]  {current.description}  [bold]<-- 当日[/]"
            )
