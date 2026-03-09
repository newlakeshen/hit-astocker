"""Prediction result renderer."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hit_astocker.models.prediction import PredictionReport, StockPrediction
from hit_astocker.renderers.theme import format_amount, pct_color, score_color


def render_prediction_report(console: Console, report: PredictionReport) -> None:
    """Render the full prediction report."""
    # Header
    header = Text()
    header.append(f"\n  Hit-Astocker 买卖预测系统", style="bold cyan")
    header.append(f"  |  {report.trade_date}", style="dim")
    header.append(f"  |  市场评分: ", style="dim")
    header.append(f"{report.market_score:.1f}", style=score_color(report.market_score))
    header.append(f"  {report.market_description}\n", style="dim")
    console.print(Panel(header, border_style="cyan"))

    # Buy candidates
    if report.buy_candidates:
        console.print(_buy_table(report.buy_candidates))
        console.print()

        # Detailed factor breakdown for top 5
        console.print("[bold cyan]--- 买入候选详细因子分析 ---[/]")
        for pred in report.buy_candidates[:5]:
            _render_factor_detail(console, pred)
    else:
        console.print("[dim]  无买入候选 (市场情绪不佳或无满足条件个股)[/]")

    console.print()

    # Sell candidates
    if report.sell_candidates:
        console.print(_sell_table(report.sell_candidates))
    else:
        console.print("[dim]  无卖出候选[/]")

    console.print()

    # Summary
    console.print(
        f"  买入候选: [bold red]{len(report.buy_candidates)}[/]只  |  "
        f"卖出候选: [bold green]{len(report.sell_candidates)}[/]只"
    )


def _buy_table(candidates: tuple[StockPrediction, ...]) -> Table:
    table = Table(title="买入候选排行", show_header=True, header_style="bold red")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("板块", width=8)
    table.add_column("今日涨幅", justify="right", width=8)
    table.add_column("收盘价", justify="right", width=8)
    table.add_column("信心度", justify="right", width=7)
    table.add_column("预测涨幅", justify="right", width=8)
    table.add_column("核心理由", width=35)

    for i, p in enumerate(candidates[:20], 1):
        table.add_row(
            str(i),
            p.ts_code,
            p.name,
            p.sector[:4] if p.sector else "-",
            f"[{pct_color(p.pct_chg)}]{p.pct_chg:.2f}%[/]",
            f"{p.close:.2f}",
            f"[{score_color(p.confidence)}]{p.confidence:.1f}[/]",
            f"[bold red]+{p.predicted_pct:.1f}%[/]" if p.predicted_pct > 0 else f"{p.predicted_pct:.1f}%",
            p.reason[:35],
        )
    return table


def _sell_table(candidates: tuple[StockPrediction, ...]) -> Table:
    table = Table(title="卖出/回避候选", show_header=True, header_style="bold green")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("今日涨幅", justify="right", width=8)
    table.add_column("信心度", justify="right", width=7)
    table.add_column("预测跌幅", justify="right", width=8)
    table.add_column("风险因素", width=40)

    for i, p in enumerate(candidates[:10], 1):
        table.add_row(
            str(i),
            p.ts_code,
            p.name,
            f"[{pct_color(p.pct_chg)}]{p.pct_chg:.2f}%[/]",
            f"[{score_color(100 - p.confidence)}]{p.confidence:.1f}[/]",
            f"[bold green]{p.predicted_pct:.1f}%[/]",
            p.reason[:40],
        )
    return table


def _render_factor_detail(console: Console, pred: StockPrediction) -> None:
    """Render detailed factor breakdown for a single stock."""
    table = Table(
        title=f"{pred.name} ({pred.ts_code}) 因子详情",
        show_header=True,
        header_style="bold",
        width=80,
    )
    table.add_column("因子", width=12)
    table.add_column("评分", justify="right", width=6)
    table.add_column("权重", justify="right", width=6)
    table.add_column("贡献", justify="right", width=6)
    table.add_column("说明", width=40)

    for f in pred.factor_scores:
        contribution = f.score * f.weight
        table.add_row(
            f.name,
            f"[{score_color(f.score)}]{f.score:.0f}[/]",
            f"{f.weight:.0%}",
            f"{contribution:.1f}",
            f.description[:40],
        )

    console.print(table)
