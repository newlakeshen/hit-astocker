"""Backtest command: run signal generation over historical data with T+1 validation."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hit_astocker.analyzers.signal_validator import SignalValidator
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.models.validation import SignalValidation, ValidationStats
from hit_astocker.renderers.theme import APP_THEME, pct_color, risk_color, score_color
from hit_astocker.signals.signal_generator import SignalGenerator
from hit_astocker.utils.date_utils import from_tushare_date, get_next_trading_day, get_trading_days_between

backtest_app = typer.Typer(name="backtest", help="Historical signal backtesting with T+1 validation")
console = Console(theme=APP_THEME)


@backtest_app.callback(invoke_without_command=True)
def backtest(
    start: str = typer.Option(..., "--start", "-s", help="Start date (YYYYMMDD)"),
    end: str = typer.Option(..., "--end", "-e", help="End date (YYYYMMDD)"),
    detail: bool = typer.Option(False, "--detail", help="Show per-signal detail"),
):
    """Backtest trading signals over a date range with next-day validation."""
    settings = get_settings()
    start_date = from_tushare_date(start)
    end_date = from_tushare_date(end)

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)
        generator = SignalGenerator(conn, settings)
        validator = SignalValidator(conn)

        all_signals = []
        all_validations: list[SignalValidation] = []

        trading_dates = get_trading_days_between(start_date, end_date)

        for i, d in enumerate(trading_dates):
            try:
                signals = generator.generate(d)
                all_signals.extend(signals)
            except Exception:
                continue

            if not signals:
                continue

            # T+1 validation: find next trading day
            next_d = trading_dates[i + 1] if i + 1 < len(trading_dates) else None
            if next_d is None:
                next_d = get_next_trading_day(d)

            if next_d:
                validations = validator.validate_signals(signals, next_d)
                all_validations.extend(validations)

        if not all_signals:
            console.print("[yellow]No signals generated in the given date range.[/]")
            raise typer.Exit(0)

        # Compute stats
        stats = SignalValidator.compute_stats(all_validations, len(all_signals))

        # Render summary
        _render_summary(stats, start, end)

        # Per signal-type breakdown (三套独立口径)
        if stats.by_type:
            _render_type_breakdown(stats)

        # Risk breakdown
        if stats.by_risk:
            _render_risk_breakdown(stats)

        # Score breakdown
        if stats.by_score_bucket:
            _render_score_breakdown(stats)

        # Per-signal detail (optional)
        if detail and all_validations:
            _render_detail(all_validations)


def _render_summary(stats: ValidationStats, start: str, end: str) -> None:
    table = Table(title=f"回测验证报告 ({start} ~ {end})", header_style="bold cyan")
    table.add_column("指标", style="bold")
    table.add_column("数值", justify="right")

    table.add_row("信号总数", str(stats.total_signals))
    table.add_row("已验证", str(stats.validated_count))

    if stats.validated_count > 0:
        hr_color = "bold red" if stats.hit_rate >= 0.5 else "bold green"
        table.add_row("胜率", f"[{hr_color}]{stats.hit_rate:.1%}[/]")
        table.add_row("盈利次数", f"[bold red]{stats.win_count}[/]")
        table.add_row("亏损次数", f"[bold green]{stats.loss_count}[/]")
        table.add_row("", "")
        table.add_row(
            "平均收益率",
            f"[{pct_color(stats.avg_return)}]{stats.avg_return:+.2f}%[/]",
        )
        table.add_row(
            "平均最高收益",
            f"[{pct_color(stats.avg_max_return)}]{stats.avg_max_return:+.2f}%[/]",
        )
        table.add_row(
            "平均最大回撤",
            f"[{pct_color(stats.avg_max_drawdown)}]{stats.avg_max_drawdown:+.2f}%[/]",
        )
        table.add_row(
            "累计收益",
            f"[{pct_color(stats.total_return)}]{stats.total_return:+.2f}%[/]",
        )
        table.add_row("", "")
        table.add_row(
            "单笔最大盈利",
            f"[bold red]{stats.max_single_win:+.2f}%[/]",
        )
        table.add_row(
            "单笔最大亏损",
            f"[bold green]{stats.max_single_loss:+.2f}%[/]",
        )
        table.add_row("最大连败", str(stats.consecutive_losses))

    console.print(table)


_TYPE_LABELS = {
    "FIRST_BOARD": "首板",
    "FOLLOW_BOARD": "接力",
    "SECTOR_LEADER": "龙头",
}


def _render_type_breakdown(stats: ValidationStats) -> None:
    table = Table(title="信号类型胜率对比 (独立口径)", header_style="bold cyan")
    table.add_column("类型", width=8)
    table.add_column("信号数", justify="right", width=6)
    table.add_column("盈利", justify="right", width=5)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均收益", justify="right", width=10)
    table.add_column("平均最高", justify="right", width=10)
    table.add_column("连板数", justify="right", width=6)

    for sig_type in ("FIRST_BOARD", "FOLLOW_BOARD", "SECTOR_LEADER"):
        bucket = stats.by_type.get(sig_type)
        if not bucket:
            continue
        hr_color = "bold red" if bucket.hit_rate >= 0.5 else "bold green"
        label = _TYPE_LABELS.get(sig_type, sig_type)
        table.add_row(
            label,
            str(bucket.count),
            str(bucket.win_count),
            f"[{hr_color}]{bucket.hit_rate:.1%}[/]",
            f"[{pct_color(bucket.avg_return)}]{bucket.avg_return:+.2f}%[/]",
            f"[{pct_color(bucket.avg_max_return)}]{bucket.avg_max_return:+.2f}%[/]",
            str(bucket.limit_up_count),
        )

    console.print(table)


def _render_risk_breakdown(stats: ValidationStats) -> None:
    table = Table(title="风险等级胜率分布", header_style="bold cyan")
    table.add_column("风险等级", width=10)
    table.add_column("信号数", justify="right", width=6)
    table.add_column("盈利数", justify="right", width=6)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均收益", justify="right", width=10)

    for risk_level in ("LOW", "MEDIUM", "HIGH"):
        bucket = stats.by_risk.get(risk_level)
        if not bucket:
            continue
        hr_color = "bold red" if bucket.hit_rate >= 0.5 else "bold green"
        table.add_row(
            f"[{risk_color(risk_level)}]{risk_level}[/]",
            str(bucket.count),
            str(bucket.win_count),
            f"[{hr_color}]{bucket.hit_rate:.1%}[/]",
            f"[{pct_color(bucket.avg_return)}]{bucket.avg_return:+.2f}%[/]",
        )

    console.print(table)


def _render_score_breakdown(stats: ValidationStats) -> None:
    table = Table(title="评分区间胜率分布", header_style="bold cyan")
    table.add_column("评分区间", width=10)
    table.add_column("信号数", justify="right", width=6)
    table.add_column("盈利数", justify="right", width=6)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均收益", justify="right", width=10)

    for label in ("80-100", "60-80", "40-60", "0-40"):
        bucket = stats.by_score_bucket.get(label)
        if not bucket:
            continue
        hr_color = "bold red" if bucket.hit_rate >= 0.5 else "bold green"
        table.add_row(
            label,
            str(bucket.count),
            str(bucket.win_count),
            f"[{hr_color}]{bucket.hit_rate:.1%}[/]",
            f"[{pct_color(bucket.avg_return)}]{bucket.avg_return:+.2f}%[/]",
        )

    console.print(table)


def _render_detail(validations: list[SignalValidation]) -> None:
    table = Table(title="信号验证明细 (Top 30)", header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("日期", width=10)
    table.add_column("类型", width=4)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("评分", justify="right", width=6)
    table.add_column("风险", width=6)
    table.add_column("买入价", justify="right", width=8)
    table.add_column("开盘%", justify="right", width=8)
    table.add_column("最高%", justify="right", width=8)
    table.add_column("收盘%", justify="right", width=8)
    table.add_column("结果", width=4)

    sorted_v = sorted(validations, key=lambda v: v.next_close_pct, reverse=True)
    for i, v in enumerate(sorted_v[:30], 1):
        result = "[bold red]盈[/]" if v.is_win else "[bold green]亏[/]"
        if v.is_limit_up:
            result = "[bold red]连板[/]"
        type_label = _TYPE_LABELS.get(v.signal_type, v.signal_type[:4])
        table.add_row(
            str(i),
            str(v.trade_date),
            type_label,
            v.ts_code,
            v.name,
            f"[{score_color(v.signal_score)}]{v.signal_score:.0f}[/]",
            f"[{risk_color(v.risk_level)}]{v.risk_level}[/]",
            f"{v.signal_close:.2f}",
            f"[{pct_color(v.next_open_pct)}]{v.next_open_pct:+.2f}%[/]",
            f"[{pct_color(v.next_high_pct)}]{v.next_high_pct:+.2f}%[/]",
            f"[{pct_color(v.next_close_pct)}]{v.next_close_pct:+.2f}%[/]",
            result,
        )

    console.print(table)
