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
import sqlite3
from dataclasses import dataclass
from datetime import date

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hit_astocker.analyzers.backtest_engine import BacktestEngine, compute_backtest_stats
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.models.backtest import (
    BacktestConfig,
    BacktestStats,
    ExecutionMode,
    SkippedSignal,
    TradeResult,
)
from hit_astocker.models.daily_context import DailyContextCaches, build_daily_context
from hit_astocker.renderers.theme import APP_THEME, pct_color, risk_color, score_color
from hit_astocker.signals.signal_generator import SignalGenerator
from hit_astocker.utils.date_utils import (
    from_tushare_date,
    get_next_trading_day,
    get_trading_days_between,
    shift_years,
    to_tushare_date,
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

_OPTIONAL_COVERAGE_SOURCES = (
    ("ths_hot", "同花顺热股", "trade_date"),
    ("hsgt_top10", "北向资金", "trade_date"),
    ("stk_factor_pro", "技术因子", "trade_date"),
    ("hm_detail", "游资席位", "trade_date"),
    ("stk_auction", "集合竞价", "trade_date"),
    ("anns_d", "公告", "ann_date"),
)


@dataclass(frozen=True)
class CoverageBucket:
    label: str
    covered_days: int
    total_days: int

    @property
    def ratio(self) -> float:
        return self.covered_days / self.total_days if self.total_days else 0.0


@dataclass(frozen=True)
class BacktestRangeCoverage:
    requested_days: int
    executable_days: int
    buckets: tuple[CoverageBucket, ...]


@dataclass(frozen=True)
class ResolvedBacktestWindow:
    start_date: date
    end_date: date
    start_label: str
    end_label: str
    requested_years: int | None = None
    truncated: bool = False
    available_start: date | None = None
    available_end: date | None = None


@backtest_app.callback(invoke_without_command=True)
def backtest(
    start: str | None = typer.Option(None, "--start", "-s", help="起始日期 (YYYYMMDD)"),
    end: str | None = typer.Option(None, "--end", "-e", help="结束日期 (YYYYMMDD)"),
    years: int = typer.Option(6, "--years", help="未指定起止日期时，默认回测近 N 年"),
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
        window = _resolve_backtest_window(conn, start, end, years)
        start_date = window.start_date
        end_date = window.end_date

        if window.truncated and window.available_start and window.available_end:
            console.print(
                f"[yellow]  ⚠ 当前核心行情仅覆盖 {window.available_start} ~ "
                f"{window.available_end}，不足近 {window.requested_years} 年。[/]\n"
                f"[dim]  本次按可用区间 {window.start_date} ~ {window.end_date} 回测。"
                f" 如需近 {window.requested_years} 年，请先运行 "
                f"'hit-astocker sync --years {window.requested_years}'。[/]\n"
            )

        generator = SignalGenerator(conn, settings)
        engine = BacktestEngine(conn)
        context_caches = DailyContextCaches()

        all_trades: list[TradeResult] = []
        all_skipped: list[SkippedSignal] = []
        total_signals = 0

        trading_dates = get_trading_days_between(start_date, end_date)
        range_coverage = _collect_range_coverage(conn, trading_dates)

        for d in trading_dates:
            try:
                ctx = build_daily_context(conn, settings, d, caches=context_caches)
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
            market_regime = None
            mc = ctx.sentiment.market_context if ctx.sentiment else None
            if mc:
                market_regime = mc.market_regime
            day_result = engine.simulate_day(
                signals, config, d, t1, t2, market_regime=market_regime,
            )
            all_trades.extend(day_result.trades)
            all_skipped.extend(day_result.skipped)

            # Evict stale bar/limit cache entries (keep recent 5 days)
            engine.evict_stale_cache(keep_after=d)

        if total_signals == 0:
            console.print("[yellow]回测区间内无信号生成[/]")
            raise typer.Exit(0)

        stats = compute_backtest_stats(all_trades, all_skipped, total_signals)

        _render_config(config, window.start_label, window.end_label)
        _render_range_coverage(range_coverage)
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

        # LLM backtest narrative (optional)
        if settings.llm_enabled:
            try:
                from hit_astocker.llm.cache import LLMCache
                from hit_astocker.llm.client import NullClient, get_llm_client
                from hit_astocker.llm.narrative_gen import generate_backtest_narrative

                llm_client = get_llm_client(settings)
                if not isinstance(llm_client, NullClient):
                    llm_cache = LLMCache(conn)
                    bt_narrative = generate_backtest_narrative(
                        llm_client, stats, all_trades,
                        cache=llm_cache,
                        use_thinking=True,
                    )
                    if bt_narrative:
                        console.print(Panel(
                            bt_narrative,
                            title="🤖 AI 策略分析",
                            border_style="magenta",
                        ))
            except Exception:
                logger.warning("LLM backtest narrative failed", exc_info=True)


# ── Render functions ─────────────────────────────────────────────


def _resolve_backtest_window(
    conn: sqlite3.Connection,
    start: str | None,
    end: str | None,
    years: int,
) -> ResolvedBacktestWindow:
    if years <= 0:
        console.print("[bold red]--years 必须为正整数[/]")
        raise typer.Exit(1)

    if start and end:
        start_date = from_tushare_date(start)
        end_date = from_tushare_date(end)
        if start_date > end_date:
            console.print("[bold red]起始日期不能晚于结束日期[/]")
            raise typer.Exit(1)
        return ResolvedBacktestWindow(
            start_date=start_date,
            end_date=end_date,
            start_label=start,
            end_label=end,
        )

    if start and not end:
        console.print("[bold red]仅提供 --start 不明确，请同时提供 --end[/]")
        raise typer.Exit(1)

    daily_bar_dates = _load_daily_bar_dates(conn)
    if not daily_bar_dates:
        console.print(
            "[bold red]daily_bar 无数据，无法回测。请先运行 "
            f"'hit-astocker sync --years {years}'。[/]"
        )
        raise typer.Exit(1)

    executable_dates = _resolve_executable_signal_dates(
        sorted(daily_bar_dates), daily_bar_dates,
    )
    if not executable_dates:
        console.print(
            "[bold red]现有 daily_bar 数据不足以形成 T+1/T+2 回测窗口。[/]"
        )
        raise typer.Exit(1)

    available_start = min(daily_bar_dates)
    available_end = max(daily_bar_dates)

    if end:
        end_date = from_tushare_date(end)
    else:
        end_date = executable_dates[-1]

    if start is None:
        target_start = shift_years(end_date, -years)
        start_date = max(target_start, available_start)
        truncated = start_date > target_start
        start_label = start_date.strftime("%Y%m%d")
        end_label = end_date.strftime("%Y%m%d")
        return ResolvedBacktestWindow(
            start_date=start_date,
            end_date=end_date,
            start_label=start_label,
            end_label=end_label,
            requested_years=years,
            truncated=truncated,
            available_start=available_start,
            available_end=available_end,
        )
    raise AssertionError("unreachable")


def _collect_range_coverage(
    conn: sqlite3.Connection,
    trading_dates: list[date],
) -> BacktestRangeCoverage:
    executable_dates = _resolve_executable_signal_dates(
        trading_dates, _load_daily_bar_dates(conn),
    )
    if not executable_dates:
        return BacktestRangeCoverage(len(trading_dates), 0, ())

    exec_set = {to_tushare_date(d) for d in executable_dates}

    buckets = []
    for table_name, label, date_column in _OPTIONAL_COVERAGE_SOURCES:
        # Pre-load all distinct dates (one fast query per table)
        try:
            rows = conn.execute(
                f"SELECT DISTINCT [{date_column}] FROM [{table_name}]",
            ).fetchall()
            db_dates = {r[0] for r in rows}
            covered = sum(1 for d in exec_set if d in db_dates)
        except sqlite3.OperationalError:
            covered = 0
        buckets.append(CoverageBucket(label, covered, len(executable_dates)))

    return BacktestRangeCoverage(
        requested_days=len(trading_dates),
        executable_days=len(executable_dates),
        buckets=tuple(buckets),
    )


def _load_daily_bar_dates(conn: sqlite3.Connection) -> set[date]:
    rows = conn.execute("SELECT DISTINCT trade_date FROM daily_bar").fetchall()
    return {from_tushare_date(row["trade_date"]) for row in rows}


def _resolve_executable_signal_dates(
    trading_dates: list[date],
    daily_bar_dates: set[date],
) -> list[date]:
    executable = []
    for trade_date in trading_dates:
        t1 = get_next_trading_day(trade_date)
        t2 = get_next_trading_day(t1) if t1 else None
        if t1 is None or t2 is None:
            continue
        if t1 not in daily_bar_dates or t2 not in daily_bar_dates:
            continue
        executable.append(trade_date)
    return executable


def _count_covered_dates(
    conn: sqlite3.Connection,
    table_name: str,
    dates: list[date],
    date_column: str,
) -> int:
    if not dates:
        return 0

    placeholders = ", ".join("?" for _ in dates)
    sql = (
        f"SELECT COUNT(DISTINCT [{date_column}]) FROM [{table_name}] "
        f"WHERE [{date_column}] IN ({placeholders})"
    )
    rows = [to_tushare_date(d) for d in dates]
    try:
        result = conn.execute(sql, rows).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(result[0] or 0) if result else 0


def _render_range_coverage(coverage: BacktestRangeCoverage) -> None:
    table = Table(title="数据覆盖", header_style="bold cyan")
    table.add_column("项目", width=12)
    table.add_column("覆盖", justify="right", width=14)
    table.add_column("说明", width=18)

    table.add_row("请求交易日", str(coverage.requested_days), "回测区间内交易日")
    table.add_row(
        "可结算信号日",
        f"{coverage.executable_days}/{coverage.requested_days}",
        "需存在 T+1/T+2 日线",
    )

    for bucket in coverage.buckets:
        if bucket.total_days == 0:
            coverage_str = "0/0"
            note = "无可结算信号日"
        else:
            coverage_str = f"{bucket.covered_days}/{bucket.total_days} ({bucket.ratio:.0%})"
            note = "全覆盖" if bucket.covered_days == bucket.total_days else "缺失日自动剔除"
        table.add_row(bucket.label, coverage_str, note)

    console.print(table)


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
