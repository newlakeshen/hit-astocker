"""Full daily dashboard renderer."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hit_astocker.models.analysis_result import FirstBoardResult, LianbanResult
from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.models.event_data import EventAnalysisResult
from hit_astocker.models.sector import SectorRotationResult
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.signal import TradingSignal
from hit_astocker.renderers.tables import (
    dragon_tiger_table,
    firstboard_table,
    lianban_table,
    sector_table,
    sentiment_table,
    signal_table,
)
from hit_astocker.renderers.theme import APP_THEME, pct_color, score_color


def render_dashboard(
    console: Console,
    sentiment: SentimentScore,
    firstboard: list[FirstBoardResult],
    lianban: LianbanResult,
    sector: SectorRotationResult,
    dragon: DragonTigerResult,
    signals: list[TradingSignal],
    event_result: EventAnalysisResult | None = None,
) -> None:
    """Render the full daily dashboard."""
    # Header with market context
    header = Text()
    header.append(f"\n  Hit-Astocker 打板分析系统", style="bold cyan")
    header.append(f"  |  {sentiment.trade_date}", style="dim")
    header.append(f"  |  综合情绪: ", style="dim")
    header.append(
        f"{sentiment.overall_score:.1f}",
        style=score_color(sentiment.overall_score),
    )
    header.append(f"  {sentiment.description}", style="dim")

    # Market context line
    ctx = sentiment.market_context
    if ctx:
        header.append(f"\n  大盘: ", style="dim")
        header.append(f"{ctx.market_regime}", style=score_color(50 + ctx.regime_score / 2))
        header.append(f"  上证 ", style="dim")
        header.append(f"{ctx.sh_pct_chg:+.2f}%", style=pct_color(ctx.sh_pct_chg))
        header.append(f"  创业板 ", style="dim")
        header.append(f"{ctx.gem_pct_chg:+.2f}%", style=pct_color(ctx.gem_pct_chg))

    header.append("\n")
    console.print(Panel(header, border_style="cyan"))

    # Sentiment overview
    console.print(sentiment_table(sentiment))
    console.print()

    # Event-driven analysis (市场叙事 + 题材热度)
    if event_result:
        _render_event_summary(console, event_result)

    # Lianban ladder
    console.print(lianban_table(lianban))
    if lianban.height_trend:
        trend_str = " -> ".join(str(h) for h in lianban.height_trend)
        console.print(f"  连板高度趋势: {trend_str}", style="dim")
    if lianban.leader_code:
        console.print(
            f"  空间板龙头: [bold red]{lianban.leader_name}[/] ({lianban.leader_code}) "
            f"[bold]{lianban.max_height}连板[/]"
        )
    console.print()

    # Sector rotation
    console.print(sector_table(sector))
    if sector.rotation_detected:
        console.print("  [yellow]! 检测到板块轮动[/]")
    console.print()

    # First board analysis
    if firstboard:
        console.print(firstboard_table(firstboard))
        console.print()

    # Dragon-tiger board
    if dragon.records:
        console.print(dragon_tiger_table(dragon))
        console.print()

    # Trading signals
    if signals:
        console.print(signal_table(signals))
    else:
        console.print("[dim]  无打板信号 (市场情绪不佳或无满足条件个股)[/]")

    console.print()


def _render_event_summary(console: Console, event_result: EventAnalysisResult) -> None:
    """Render compact event-driven summary within the dashboard."""
    # Market narrative
    console.print(f"  [bold cyan]市场叙事[/]: {event_result.market_narrative}")

    # Top 5 theme heats (compact)
    if event_result.theme_heats:
        table = Table(title="题材热度 Top 5", header_style="bold cyan", show_lines=False)
        table.add_column("题材", width=10)
        table.add_column("数量", justify="right", width=4)
        table.add_column("持续", justify="right", width=5)
        table.add_column("趋势", width=6)
        table.add_column("热度", justify="right", width=5)

        trend_labels = {
            "HEATING": "[bold red]↑升[/]",
            "STABLE": "[yellow]→稳[/]",
            "COOLING": "[bold green]↓降[/]",
            "NEW": "[magenta]★新[/]",
        }

        for th in event_result.theme_heats[:5]:
            table.add_row(
                th.theme_name[:5],
                str(th.today_count),
                f"{th.persistence_days}天",
                trend_labels.get(th.heat_trend, ""),
                f"[{score_color(th.heat_score)}]{th.heat_score:.0f}[/]",
            )
        console.print(table)

    console.print()
