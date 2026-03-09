"""Money flow analysis command."""

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from hit_astocker.analyzers.flow_factors import FlowFactorEngine
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.theme import APP_THEME, format_amount, score_color
from hit_astocker.repositories.moneyflow_detail_repo import MoneyFlowDetailRepository
from hit_astocker.utils.date_utils import from_tushare_date

flow_app = typer.Typer(name="flow", help="Money flow factor analysis")
console = Console(theme=APP_THEME)


@flow_app.callback(invoke_without_command=True)
def flow(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    code: str = typer.Option(None, "--code", "-c", help="Specific stock code"),
    top_n: int = typer.Option(20, "--top", "-n", help="Top N by main force inflow"),
):
    """Analyze money flow factors for stocks."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        engine = FlowFactorEngine(conn)

        if code:
            # Single stock detailed analysis
            result = engine.compute_factors(code, trade_date)
            if result is None:
                console.print(f"[yellow]No flow data for {code} on {trade_date}[/]")
                raise typer.Exit(1)

            table = Table(
                title=f"{result.name} ({result.ts_code}) 资金流因子",
                header_style="bold cyan",
            )
            table.add_column("因子", width=12)
            table.add_column("评分", justify="right", width=6)
            table.add_column("权重", justify="right", width=6)
            table.add_column("说明", width=45)

            for f in [
                result.main_force_momentum, result.smart_money, result.order_structure,
                result.flow_price_divergence, result.accumulation,
                result.volume_price, result.flow_consistency,
            ]:
                table.add_row(
                    f.name,
                    f"[{score_color(f.score)}]{f.score:.0f}[/]",
                    f"{f.weight:.0%}",
                    f.description,
                )

            console.print(table)
            console.print(f"  综合评分: [{score_color(result.composite_score)}]{result.composite_score:.1f}[/]")
            direction = "看多" if result.direction_bias > 0 else "看空"
            console.print(f"  方向偏好: {direction} ({result.direction_bias:+.1f})")
        else:
            # Top N stocks by main force inflow
            detail_repo = MoneyFlowDetailRepository(conn)
            top_inflow = detail_repo.find_top_main_force_inflow(trade_date, top_n)

            if not top_inflow:
                console.print(f"[yellow]No flow data for {trade_date}[/]")
                raise typer.Exit(1)

            codes = [f.ts_code for f in top_inflow]
            results = engine.batch_compute(codes, trade_date)
            results.sort(key=lambda r: r.composite_score, reverse=True)

            table = Table(title=f"资金流因子排行 ({trade_date})", header_style="bold cyan")
            table.add_column("#", justify="right", width=3)
            table.add_column("代码", width=10)
            table.add_column("名称", width=8)
            table.add_column("主力净流入", justify="right", width=10)
            table.add_column("主力动量", justify="right", width=7)
            table.add_column("聪明钱", justify="right", width=6)
            table.add_column("吸筹", justify="right", width=6)
            table.add_column("量价", justify="right", width=6)
            table.add_column("一致性", justify="right", width=6)
            table.add_column("综合", justify="right", width=6)
            table.add_column("方向", width=6)

            for i, r in enumerate(results[:top_n], 1):
                today_flow = next((f for f in top_inflow if f.ts_code == r.ts_code), None)
                main_net = today_flow.main_force_net if today_flow else 0
                direction = "[bold red]看多[/]" if r.direction_bias > 0 else "[bold green]看空[/]"
                table.add_row(
                    str(i),
                    r.ts_code,
                    r.name,
                    format_amount(main_net),
                    f"[{score_color(r.main_force_momentum.score)}]{r.main_force_momentum.score:.0f}[/]",
                    f"[{score_color(r.smart_money.score)}]{r.smart_money.score:.0f}[/]",
                    f"[{score_color(r.accumulation.score)}]{r.accumulation.score:.0f}[/]",
                    f"[{score_color(r.volume_price.score)}]{r.volume_price.score:.0f}[/]",
                    f"[{score_color(r.flow_consistency.score)}]{r.flow_consistency.score:.0f}[/]",
                    f"[{score_color(r.composite_score)}]{r.composite_score:.0f}[/]",
                    direction,
                )

            console.print(table)
