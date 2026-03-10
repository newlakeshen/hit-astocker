"""Event-driven analysis command."""

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from hit_astocker.analyzers.event_classifier import EventClassifier
from hit_astocker.analyzers.stock_sentiment import StockSentimentAnalyzer
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.theme import APP_THEME, score_color
from hit_astocker.utils.date_utils import from_tushare_date

event_app = typer.Typer(name="event", help="Event-driven and sentiment analysis")
console = Console(theme=APP_THEME)


@event_app.callback(invoke_without_command=True)
def event(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
):
    """Show event-driven analysis and stock sentiment."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        # Event classification
        classifier = EventClassifier(conn)
        result = classifier.analyze(trade_date)

        # Market narrative
        console.print(f"\n  [bold cyan]市场叙事[/]: {result.market_narrative}")
        console.print(f"  题材集中度: {result.theme_concentration:.0%}")
        console.print()

        # Event type distribution
        _render_event_distribution(result)

        # Theme heat table
        _render_theme_heat(result)

        # Per-stock sentiment
        sentiment_analyzer = StockSentimentAnalyzer(conn)
        stock_scores = sentiment_analyzer.analyze(trade_date)
        if stock_scores:
            _render_stock_sentiment(stock_scores)


def _render_event_distribution(result) -> None:
    table = Table(title="涨停事件类型分布", header_style="bold cyan")
    table.add_column("事件类型", width=10)
    table.add_column("数量", justify="right", width=6)
    table.add_column("占比", justify="right", width=8)
    table.add_column("比例条", width=20)

    total = sum(result.event_distribution.values())
    for event_type, count in sorted(
        result.event_distribution.items(), key=lambda x: x[1], reverse=True
    ):
        pct = count / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 5)
        is_dominant = event_type == result.dominant_event_type
        style = "bold red" if is_dominant else "white"
        table.add_row(
            f"[{style}]{event_type}[/]",
            str(count),
            f"{pct:.1f}%",
            f"[{style}]{bar}[/]",
        )

    console.print(table)

    # Layer coverage breakdown
    layer_dist: dict[str, int] = {}
    for ev in result.stock_events:
        layer_dist[ev.event_layer] = layer_dist.get(ev.event_layer, 0) + 1
    if layer_dist and total > 0:
        parts = []
        for layer, cnt in sorted(layer_dist.items(), key=lambda x: -x[1]):
            label = {"ANNOUNCEMENT": "公告", "CONCEPT": "概念", "KEYWORD": "关键词"}.get(layer, layer)
            parts.append(f"{label} {cnt}({cnt / total * 100:.0f}%)")
        console.print(f"  识别层分布: {' | '.join(parts)}")

    # Policy level & order amount breakdown
    from hit_astocker.models.event_data import OrderAmountLevel, PolicyLevel
    policy_counts: dict[str, int] = {}
    amount_counts: dict[str, int] = {}
    for ev in result.stock_events:
        if ev.policy_level != PolicyLevel.UNKNOWN:
            policy_counts[ev.policy_level] = policy_counts.get(ev.policy_level, 0) + 1
        if ev.order_amount_level != OrderAmountLevel.UNKNOWN:
            amount_counts[ev.order_amount_level] = amount_counts.get(ev.order_amount_level, 0) + 1
    if policy_counts:
        pol_parts = [f"{level} {cnt}" for level, cnt in policy_counts.items()]
        console.print(f"  政策级别: {' | '.join(pol_parts)}")
    if amount_counts:
        amt_parts = [f"{level} {cnt}" for level, cnt in amount_counts.items()]
        console.print(f"  金额级别: {' | '.join(amt_parts)}")


def _render_theme_heat(result) -> None:
    if not result.theme_heats:
        return

    table = Table(title="题材热度追踪 (多维评分)", header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("题材", width=10)
    table.add_column("数量", justify="right", width=5)
    table.add_column("高度", justify="right", width=4)
    table.add_column("趋势", width=8)
    table.add_column("热度", justify="right", width=5)
    table.add_column("主线", justify="right", width=5)
    table.add_column("龙头", justify="right", width=5)
    table.add_column("扩散", justify="right", width=5)
    table.add_column("参与", justify="right", width=5)
    table.add_column("领涨", width=18)

    trend_styles = {
        "HEATING": "[bold red]升温↑[/]",
        "STABLE": "[yellow]稳定→[/]",
        "COOLING": "[bold green]降温↓[/]",
        "NEW": "[bold magenta]新热★[/]",
    }

    for i, th in enumerate(result.theme_heats[:15], 1):
        trend = trend_styles.get(th.heat_trend, th.heat_trend)
        leaders = ", ".join(th.leader_names[:3])
        height_str = f"{th.max_height}板" if th.max_height > 1 else "首板"
        table.add_row(
            str(i),
            th.theme_name[:5],
            f"{th.today_count}({th.yesterday_count})",
            height_str,
            trend,
            f"[{score_color(th.heat_score)}]{th.heat_score:.0f}[/]",
            f"[{score_color(th.height_score)}]{th.height_score:.0f}[/]",
            f"[{score_color(th.leader_score)}]{th.leader_score:.0f}[/]",
            f"[{score_color(th.expansion_score)}]{th.expansion_score:.0f}[/]",
            f"[{score_color(th.participation_score)}]{th.participation_score:.0f}[/]",
            leaders,
        )

    console.print(table)


def _render_stock_sentiment(scores) -> None:
    table = Table(title="个股情绪排行 (Top 20)", header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("量比", justify="right", width=6)
    table.add_column("封单", justify="right", width=6)
    table.add_column("竞价", justify="right", width=6)
    table.add_column("题材", justify="right", width=6)
    table.add_column("催化", justify="right", width=6)
    table.add_column("综合", justify="right", width=7)

    for i, ss in enumerate(scores[:20], 1):
        table.add_row(
            str(i),
            ss.ts_code,
            ss.name,
            f"[{score_color(ss.volume_ratio_score)}]{ss.volume_ratio_score:.0f}[/]",
            f"[{score_color(ss.seal_order_score)}]{ss.seal_order_score:.0f}[/]",
            f"[{score_color(ss.bid_activity_score)}]{ss.bid_activity_score:.0f}[/]",
            f"[{score_color(ss.theme_heat_score)}]{ss.theme_heat_score:.0f}[/]",
            f"[{score_color(ss.event_catalyst_score)}]{ss.event_catalyst_score:.0f}[/]",
            f"[{score_color(ss.composite_score)}]{ss.composite_score:.1f}[/]",
        )

    console.print(table)
