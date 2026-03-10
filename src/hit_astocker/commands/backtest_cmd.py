"""Backtest command: realistic board-hitting simulation with friction costs.

Execution modes:
  AUCTION        — 复盘选股→次日竞价买 (T+1 open)
  WEAK_TO_STRONG — 弱转强开盘买 (T+1 open, only if open < T close)
  RE_SEAL        — 回封买 (T+1 close, only if board re-sealed)

Friction:
  滑点 / 佣金 / 印花税 / 竞价溢价上限 / 排板成交率

Trade lifecycle: T signal → T+1 buy → T+2 sell (A-share T+1 rule).
"""

import logging
import math

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hit_astocker.analyzers.backtest_engine import BacktestEngine, compute_backtest_stats
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.models.daily_context import DataCoverage, build_daily_context, table_has_data
from hit_astocker.models.backtest import (
    BacktestConfig,
    BacktestStats,
    ExecutionMode,
    SkippedSignal,
    TradeResult,
)
from hit_astocker.renderers.theme import APP_THEME, pct_color, risk_color, score_color
from hit_astocker.signals.signal_generator import SignalGenerator
from hit_astocker.utils.date_utils import (
    from_tushare_date,
    get_next_trading_day,
    get_trading_days_between,
)

logger = logging.getLogger(__name__)

backtest_app = typer.Typer(name="backtest", help="真实打板回测 (三种执行方式 + 摩擦成本)")
console = Console(theme=APP_THEME)

_MODE_LABELS = {
    "AUCTION": "竞价买",
    "WEAK_TO_STRONG": "弱转强",
    "RE_SEAL": "回封买",
}

_EXIT_LABELS = {
    "STOP_LOSS": "止损",
    "TAKE_PROFIT": "兑现",
    "CLOSE": "收盘",
    "YIZI_HELD": "封死",
}

_TYPE_LABELS = {
    "FIRST_BOARD": "首板",
    "FOLLOW_BOARD": "接力",
    "SECTOR_LEADER": "龙头",
}

_SKIP_LABELS = {
    "YIZI_CANT_BUY": "一字板不可买",
    "NO_WEAKNESS": "开盘未弱",
    "NO_RESEAL": "未回封",
    "NO_T1_BAR": "无T+1数据",
    "NO_T2_BAR": "无T+2数据",
    "PREMIUM_TOO_HIGH": "溢价超限",
    "LOW_FILL_RATE": "换手过低",
}


@backtest_app.callback(invoke_without_command=True)
def backtest(
    start: str = typer.Option(..., "--start", "-s", help="起始日期 (YYYYMMDD)"),
    end: str = typer.Option(..., "--end", "-e", help="结束日期 (YYYYMMDD)"),
    mode: str = typer.Option(
        "AUCTION", "--mode", "-m",
        help="执行方式: AUCTION / WEAK_TO_STRONG / RE_SEAL",
    ),
    stop_loss: float = typer.Option(-7.0, "--stop-loss", help="止损线 (%%, 负数)"),
    take_profit: float = typer.Option(5.0, "--take-profit", help="止盈线 (%%, 正数)"),
    slippage: float = typer.Option(10.0, "--slippage", help="滑点 (基点, 单边)"),
    max_premium: float = typer.Option(7.0, "--max-premium", help="竞价溢价上限 (%%)"),
    no_dynamic_stops: bool = typer.Option(False, "--no-dynamic-stops", help="禁用动态止损止盈"),
    detail: bool = typer.Option(False, "--detail", help="显示逐笔明细"),
):
    """真实打板回测: T信号 → T+1买入 → T+2卖出, 含摩擦成本."""
    settings = get_settings()
    start_date = from_tushare_date(start)
    end_date = from_tushare_date(end)

    try:
        exec_mode = ExecutionMode(mode.upper())
    except ValueError:
        console.print(
            f"[bold red]无效执行方式: {mode}[/]"
            "  (可选: AUCTION / WEAK_TO_STRONG / RE_SEAL)"
        )
        raise typer.Exit(1)

    if stop_loss >= 0:
        console.print("[bold red]止损线必须为负数 (如 -7.0)[/]")
        raise typer.Exit(1)
    if take_profit <= 0:
        console.print("[bold red]止盈线必须为正数 (如 5.0)[/]")
        raise typer.Exit(1)

    config = BacktestConfig(
        execution_mode=exec_mode,
        stop_loss_pct=stop_loss,
        take_profit_pct=take_profit,
        slippage_bps=slippage,
        max_open_premium_pct=max_premium,
        dynamic_stops=not no_dynamic_stops,
    )

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        # One-time data coverage check
        coverage = DataCoverage(
            has_ths_hot=table_has_data(conn, "ths_hot"),
            has_hsgt=table_has_data(conn, "hsgt_top10"),
            has_stk_factor=table_has_data(conn, "stk_factor_pro"),
            has_hm=table_has_data(conn, "hm_detail"),
        )
        if coverage.missing_sources:
            missing = ", ".join(coverage.missing_sources)
            console.print(
                f"[yellow]  ⚠ 数据缺失: {missing}[/]\n"
                "[dim]  对应因子已从评分权重中剔除。[/]\n"
            )

        generator = SignalGenerator(conn, settings)
        engine = BacktestEngine(conn)

        all_trades: list[TradeResult] = []
        all_skipped: list[SkippedSignal] = []
        total_signals = 0

        trading_dates = get_trading_days_between(start_date, end_date)

        for d in trading_dates:
            try:
                ctx = build_daily_context(conn, settings, d)
                signals = generator.generate_from_context(ctx)
            except Exception as exc:
                logger.warning("信号生成失败 [%s]: %s", d, exc)
                continue

            if not signals:
                continue

            t1 = get_next_trading_day(d)
            t2 = get_next_trading_day(t1) if t1 else None
            if not t1 or not t2:
                skip_r = "NO_T1_BAR" if t1 is None else "NO_T2_BAR"
                for sig in signals:
                    all_skipped.append(SkippedSignal(
                        trade_date=sig.trade_date,
                        ts_code=sig.ts_code,
                        name=sig.name,
                        signal_score=sig.composite_score,
                        skip_reason=skip_r,
                    ))
                total_signals += len(signals)
                continue

            total_signals += len(signals)
            day_result = engine.simulate_day(signals, config, d, t1, t2)
            all_trades.extend(day_result.trades)
            all_skipped.extend(day_result.skipped)

        if total_signals == 0:
            console.print("[yellow]回测区间内无信号生成[/]")
            raise typer.Exit(0)

        stats = compute_backtest_stats(all_trades, all_skipped, total_signals)

        _render_config(config, start, end)
        _render_summary(stats)

        if stats.by_exit:
            _render_exit_breakdown(stats)

        if stats.skip_summary:
            _render_skip_breakdown(stats)

        if stats.by_type:
            _render_type_breakdown(stats)

        if stats.by_risk:
            _render_risk_breakdown(stats)

        if stats.by_score:
            _render_score_breakdown(stats)

        if detail and all_trades:
            _render_detail(all_trades)


# ── Render functions ─────────────────────────────────────────────


def _render_config(config: BacktestConfig, start: str, end: str) -> None:
    mode_label = _MODE_LABELS.get(config.execution_mode.value, config.execution_mode.value)
    cost_bps = (config.commission_rate * 2 + config.stamp_duty_rate) * 10000
    dynamic_str = ""
    if config.dynamic_stops:
        fb_sl, fb_tp = config.effective_stops("FIRST_BOARD")
        fl_sl, fl_tp = config.effective_stops("FOLLOW_BOARD")
        sl_sl, sl_tp = config.effective_stops("SECTOR_LEADER")
        dynamic_str = (
            f"\n动态止损 [bold cyan]ON[/]: "
            f"首板{fb_sl:+.0f}%/{fb_tp:+.0f}%  "
            f"接力{fl_sl:+.0f}%/{fl_tp:+.0f}%  "
            f"龙头{sl_sl:+.0f}%/{sl_tp:+.0f}%"
        )
    text = (
        f"区间 {start} ~ {end}  |  "
        f"模式 [bold cyan]{mode_label}[/]  |  "
        f"止损 [bold green]{config.stop_loss_pct:+.1f}%[/]  |  "
        f"止盈 [bold red]{config.take_profit_pct:+.1f}%[/]\n"
        f"滑点 {config.slippage_bps:.0f}bp  |  "
        f"手续费 {cost_bps:.0f}bp/笔  |  "
        f"溢价上限 {config.max_open_premium_pct:.0f}%  |  "
        f"回封换手 ≥{config.min_reseal_turnover:.0f}%"
        + dynamic_str
    )
    console.print(Panel(text, title="回测配置", border_style="cyan"))


def _render_summary(stats: BacktestStats) -> None:
    table = Table(title="回测结果总览", header_style="bold cyan")
    table.add_column("指标", style="bold")
    table.add_column("数值", justify="right")

    table.add_row("信号总数", str(stats.total_signals))
    table.add_row("成交笔数", f"[bold]{stats.traded_count}[/]")
    table.add_row("跳过笔数", f"[dim]{stats.skipped_count}[/]")

    if stats.traded_count > 0:
        hr_color = "bold red" if stats.hit_rate >= 0.5 else "bold green"
        table.add_row("", "")
        table.add_row("胜率", f"[{hr_color}]{stats.hit_rate:.1%}[/]")
        table.add_row("盈利次数", f"[bold red]{stats.win_count}[/]")
        table.add_row("亏损次数", f"[bold green]{stats.loss_count}[/]")
        table.add_row("", "")
        table.add_row("平均净盈亏", f"[{pct_color(stats.avg_pnl)}]{stats.avg_pnl:+.2f}%[/]")
        table.add_row("累计净盈亏", f"[{pct_color(stats.total_pnl)}]{stats.total_pnl:+.2f}%[/]")
        table.add_row("平均摩擦成本", f"[dim]{stats.avg_cost:.2f}%/笔[/]")
        table.add_row("单笔最大盈利", f"[bold red]{stats.max_win:+.2f}%[/]")
        table.add_row("单笔最大亏损", f"[bold green]{stats.max_loss:+.2f}%[/]")
        pf_color = "bold red" if stats.profit_factor >= 1.0 else "bold green"
        pf_str = "INF" if math.isinf(stats.profit_factor) else f"{stats.profit_factor:.2f}"
        if math.isnan(stats.profit_factor):
            pf_str = "N/A"
        table.add_row("盈亏比", f"[{pf_color}]{pf_str}[/]")
        table.add_row("最大连亏", str(stats.consecutive_losses))

    console.print(table)


def _render_exit_breakdown(stats: BacktestStats) -> None:
    table = Table(title="出场方式分布", header_style="bold cyan")
    table.add_column("出场方式", width=10)
    table.add_column("笔数", justify="right", width=6)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均盈亏", justify="right", width=10)
    table.add_column("累计盈亏", justify="right", width=10)

    for reason in ("TAKE_PROFIT", "CLOSE", "STOP_LOSS", "YIZI_HELD"):
        bucket = stats.by_exit.get(reason)
        if not bucket:
            continue
        label = _EXIT_LABELS.get(reason, reason)
        hr_color = "bold red" if bucket.hit_rate >= 0.5 else "bold green"
        table.add_row(
            label,
            str(bucket.count),
            f"[{hr_color}]{bucket.hit_rate:.1%}[/]",
            f"[{pct_color(bucket.avg_pnl)}]{bucket.avg_pnl:+.2f}%[/]",
            f"[{pct_color(bucket.total_pnl)}]{bucket.total_pnl:+.2f}%[/]",
        )

    console.print(table)


def _render_skip_breakdown(stats: BacktestStats) -> None:
    table = Table(title="跳过原因分布", header_style="bold cyan")
    table.add_column("原因", width=16)
    table.add_column("笔数", justify="right", width=6)

    for reason, count in stats.skip_summary.items():
        label = _SKIP_LABELS.get(reason, reason)
        table.add_row(label, str(count))

    console.print(table)


def _render_type_breakdown(stats: BacktestStats) -> None:
    table = Table(title="信号类型对比", header_style="bold cyan")
    table.add_column("类型", width=8)
    table.add_column("笔数", justify="right", width=6)
    table.add_column("盈利", justify="right", width=5)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均盈亏", justify="right", width=10)
    table.add_column("累计盈亏", justify="right", width=10)

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
            f"[{pct_color(bucket.avg_pnl)}]{bucket.avg_pnl:+.2f}%[/]",
            f"[{pct_color(bucket.total_pnl)}]{bucket.total_pnl:+.2f}%[/]",
        )

    console.print(table)


def _render_risk_breakdown(stats: BacktestStats) -> None:
    table = Table(title="风险等级分布", header_style="bold cyan")
    table.add_column("风险", width=10)
    table.add_column("笔数", justify="right", width=6)
    table.add_column("盈利", justify="right", width=5)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均盈亏", justify="right", width=10)

    for risk in ("LOW", "MEDIUM", "HIGH"):
        bucket = stats.by_risk.get(risk)
        if not bucket:
            continue
        hr_color = "bold red" if bucket.hit_rate >= 0.5 else "bold green"
        table.add_row(
            f"[{risk_color(risk)}]{risk}[/]",
            str(bucket.count),
            str(bucket.win_count),
            f"[{hr_color}]{bucket.hit_rate:.1%}[/]",
            f"[{pct_color(bucket.avg_pnl)}]{bucket.avg_pnl:+.2f}%[/]",
        )

    console.print(table)


def _render_score_breakdown(stats: BacktestStats) -> None:
    table = Table(title="评分区间分布", header_style="bold cyan")
    table.add_column("评分", width=10)
    table.add_column("笔数", justify="right", width=6)
    table.add_column("盈利", justify="right", width=5)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均盈亏", justify="right", width=10)

    for label in ("80-100", "60-80", "40-60", "0-40"):
        bucket = stats.by_score.get(label)
        if not bucket:
            continue
        hr_color = "bold red" if bucket.hit_rate >= 0.5 else "bold green"
        table.add_row(
            label,
            str(bucket.count),
            str(bucket.win_count),
            f"[{hr_color}]{bucket.hit_rate:.1%}[/]",
            f"[{pct_color(bucket.avg_pnl)}]{bucket.avg_pnl:+.2f}%[/]",
        )

    console.print(table)


def _render_detail(trades: list[TradeResult]) -> None:
    table = Table(title="逐笔明细 (盈亏排序, Top 30)", header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("信号日", width=10)
    table.add_column("类型", width=4)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("评分", justify="right", width=5)
    table.add_column("买入价", justify="right", width=8)
    table.add_column("卖出价", justify="right", width=8)
    table.add_column("出场", width=4)
    table.add_column("净盈亏", justify="right", width=8)
    table.add_column("成本", justify="right", width=6)

    sorted_t = sorted(trades, key=lambda t: t.pnl_pct, reverse=True)
    for i, t in enumerate(sorted_t[:30], 1):
        type_label = _TYPE_LABELS.get(t.signal_type, t.signal_type[:4])
        exit_label = _EXIT_LABELS.get(t.exit_reason, t.exit_reason[:4])
        table.add_row(
            str(i),
            str(t.trade_date),
            type_label,
            t.ts_code,
            t.name,
            f"[{score_color(t.signal_score)}]{t.signal_score:.0f}[/]",
            f"{t.entry_price:.2f}",
            f"{t.exit_price:.2f}",
            exit_label,
            f"[{pct_color(t.pnl_pct)}]{t.pnl_pct:+.2f}%[/]",
            f"[dim]{t.cost_pct:.2f}%[/]",
        )

    console.print(table)
