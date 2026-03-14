# src/hit_astocker/commands/backtest_diag_cmd.py
"""backtest diag — 6-dimensional backtest diagnosis."""

from __future__ import annotations

import dataclasses
import logging
from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from hit_astocker.analyzers.backtest_diagnosis import BacktestDiagnosis, SliceStats
from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.theme import APP_THEME

logger = logging.getLogger(__name__)
diag_app = typer.Typer(name="backtest-diag", help="回测诊断: 6维切片分析亏损来源")
console = Console(theme=APP_THEME)


def _render_slice_table(title: str, slices: dict[str, SliceStats]) -> None:
    """Render one dimension's slice stats as a Rich table."""
    table = Table(title=title, header_style="bold cyan")
    table.add_column("切片", style="bold", width=16)
    table.add_column("笔数", justify="right", width=8)
    table.add_column("胜率", justify="right", width=8)
    table.add_column("平均盈亏%", justify="right", width=10)
    table.add_column("累计盈亏%", justify="right", width=10)
    table.add_column("盈亏比", justify="right", width=8)
    table.add_column("最大赢%", justify="right", width=8)
    table.add_column("最大亏%", justify="right", width=8)

    for key, stats in slices.items():
        pnl_style = "green" if stats.total_pnl > 0 else "red" if stats.total_pnl < 0 else ""
        inf = float("inf")
        pl_str = f"{stats.profit_loss_ratio:.2f}" if stats.profit_loss_ratio != inf else "∞"

        table.add_row(
            key,
            str(stats.count),
            f"{stats.hit_rate:.1f}%",
            f"[{pnl_style}]{stats.avg_pnl:+.2f}[/]",
            f"[{pnl_style}]{stats.total_pnl:+.1f}[/]",
            pl_str,
            f"{stats.max_win:+.2f}",
            f"[red]{stats.max_loss:+.2f}[/]",
        )

    console.print(table)
    console.print()


def _render_bleeding_points(bleeds: list[dict]) -> None:
    """Render bleeding point summary."""
    if not bleeds:
        console.print("[green]没有发现明显的出血点 (所有切片亏损贡献 < 20%)[/]\n")
        return

    table = Table(title="出血点摘要 (亏损贡献 > 20%)", header_style="bold red")
    table.add_column("维度", width=12)
    table.add_column("切片", width=16)
    table.add_column("累计亏损%", justify="right", width=10)
    table.add_column("亏损占比", justify="right", width=10)
    table.add_column("笔数", justify="right", width=8)
    table.add_column("胜率", justify="right", width=8)

    dim_labels = {
        "year": "年份",
        "cycle": "情绪周期",
        "signal_type": "信号类型",
        "exit_reason": "出场原因",
        "score": "评分区间",
        "profit_regime": "赚钱效应",
    }

    for b in bleeds:
        table.add_row(
            dim_labels.get(b["dimension"], b["dimension"]),
            b["slice_key"],
            f"[red]{b['total_pnl']:+.1f}[/]",
            f"[red]{b['contribution_pct']:.1f}%[/]",
            str(b["count"]),
            f"{b['hit_rate']:.1f}%",
        )

    console.print(table)
    console.print()


@diag_app.callback(invoke_without_command=True)
def diag(
    start: str = typer.Option(
        ..., "--start", "-s", help="起始日期 YYYYMMDD"
    ),
    end: str = typer.Option(
        ..., "--end", "-e", help="结束日期 YYYYMMDD"
    ),
    mode: str = typer.Option(
        "AUCTION", "--mode", "-m", help="执行模式: AUCTION/WEAK_TO_STRONG/RE_SEAL"
    ),
    stop_loss: float = typer.Option(-7.0, "--stop-loss", help="止损线 (负数%)"),
    take_profit: float = typer.Option(8.0, "--take-profit", help="止盈线 (正数%)"),
    no_dynamic_stops: bool = typer.Option(False, "--no-dynamic-stops", help="禁用动态止损止盈"),
) -> None:
    """6维回测诊断: 按年份/周期/信号类型/出场/评分/赚钱效应切片分析。"""
    from datetime import timedelta

    from hit_astocker.analyzers.backtest_engine import BacktestEngine
    from hit_astocker.models.backtest import BacktestConfig, ExecutionMode, TradeResult
    from hit_astocker.models.daily_context import (
        DailyContextCaches,
        DataCoverage,
        build_daily_context,
        table_has_data_for_date_batch,
    )
    from hit_astocker.repositories.hm_repo import HmRepository
    from hit_astocker.repositories.kpl_repo import KplRepository
    from hit_astocker.repositories.limit_repo import LimitListRepository
    from hit_astocker.repositories.limit_step_repo import LimitStepRepository
    from hit_astocker.signals.signal_generator import SignalGenerator
    from hit_astocker.utils.date_utils import get_next_trading_day, get_trading_days_between

    settings = get_settings()

    try:
        exec_mode = ExecutionMode(mode.upper())
    except ValueError:
        console.print(f"[bold red]无效执行方式: {mode}[/]")
        raise typer.Exit(1)

    config = BacktestConfig(
        execution_mode=exec_mode,
        stop_loss_pct=stop_loss,
        take_profit_pct=take_profit,
        dynamic_stops=not no_dynamic_stops,
    )

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        # Parse dates
        start_date = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
        end_date = date(int(end[:4]), int(end[4:6]), int(end[6:8]))

        engine = BacktestEngine(conn)
        generator = SignalGenerator(conn, settings)

        trading_days = get_trading_days_between(start_date, end_date)

        # ── Pre-warm: bulk preload for performance ──
        preload_start = start_date - timedelta(days=20)
        preload_end = end_date + timedelta(days=5)

        limit_repo = LimitListRepository(conn)
        limit_repo.preload_range(preload_start, preload_end)
        step_repo = LimitStepRepository(conn)
        step_repo.preload_range(preload_start, preload_end)
        kpl_repo = KplRepository(conn)
        kpl_repo.preload_range(preload_start, preload_end)
        hm_repo = HmRepository(conn)

        # Per-day coverage batch preload
        ths_hot_dates = table_has_data_for_date_batch(conn, "ths_hot", trading_days)
        hsgt_dates = table_has_data_for_date_batch(conn, "hsgt_top10", trading_days)
        stk_factor_dates = table_has_data_for_date_batch(
            conn, "stk_factor_pro", trading_days,
        )
        hm_dates = table_has_data_for_date_batch(conn, "hm_detail", trading_days)
        auction_dates = table_has_data_for_date_batch(conn, "stk_auction", trading_days)
        coverage_cache: dict[date, DataCoverage] = {}
        for d_cov in trading_days:
            coverage_cache[d_cov] = DataCoverage(
                has_ths_hot=d_cov in ths_hot_dates,
                has_hsgt=d_cov in hsgt_dates,
                has_stk_factor=d_cov in stk_factor_dates,
                has_hm=d_cov in hm_dates,
                has_auction=d_cov in auction_dates,
            )

        context_caches = DailyContextCaches(
            limit_repo=limit_repo,
            step_repo=step_repo,
            kpl_repo=kpl_repo,
            hm_repo=hm_repo,
            coverage_cache=coverage_cache,
        )

        console.print(f"\n[bold]回测诊断[/] {start} -> {end}  mode={mode}\n")

        all_trades: list[TradeResult] = []

        with console.status("[bold green]Running backtest diagnosis..."):
            for d in trading_days:
                t1 = get_next_trading_day(d)
                t2 = get_next_trading_day(t1) if t1 else None
                if not t1 or not t2:
                    continue

                # build_daily_context already computes sentiment_cycle + profit_effect
                try:
                    ctx = build_daily_context(conn, settings, d, caches=context_caches)
                    signals = generator.generate_from_context(ctx)
                except Exception as exc:
                    logger.warning("信号生成失败 [%s]: %s", d, exc)
                    continue

                if not signals:
                    continue

                # Run simulation with market-regime adaptive stops + T+3
                market_regime = None
                mc = ctx.sentiment.market_context if ctx.sentiment else None
                if mc:
                    market_regime = mc.market_regime
                t3 = get_next_trading_day(t2)
                cycle_phase = (
                    ctx.sentiment_cycle.phase.value if ctx.sentiment_cycle else None
                )
                day_result = engine.simulate_day(
                    signals, config, d, t1, t2,
                    exit_date_t3=t3,
                    market_regime=market_regime,
                    cycle_phase=cycle_phase,
                )

                # Post-hoc enrichment: fill cycle_phase/profit_regime via dataclasses.replace
                cycle_phase: str | None = None
                profit_regime: str | None = None
                if ctx.sentiment_cycle is not None:
                    cycle_phase = ctx.sentiment_cycle.phase.value
                if ctx.profit_effect is not None:
                    profit_regime = ctx.profit_effect.regime.value

                enriched = [
                    dataclasses.replace(
                        trade,
                        cycle_phase=cycle_phase,
                        profit_regime=profit_regime,
                    )
                    for trade in day_result.trades
                ]
                all_trades.extend(enriched)

                # Evict stale bar/limit cache entries
                engine.evict_stale_cache(keep_after=d)

        if not all_trades:
            console.print("[yellow]回测区间内无交易[/]")
            return

        # Run diagnosis
        diagnosis = BacktestDiagnosis(all_trades)

        # Overall summary
        total_pnl = sum(t.pnl_pct for t in all_trades)
        win_count = sum(1 for t in all_trades if t.pnl_pct > 0)
        hit_rate = win_count / len(all_trades) * 100

        pnl_color = "green" if total_pnl > 0 else "red"
        console.print(
            f"总交易: [bold]{len(all_trades)}[/] 笔  "
            f"胜率: [bold]{hit_rate:.1f}%[/]  "
            f"累计收益: [bold {pnl_color}]{total_pnl:+.1f}%[/]\n"
        )

        # Render 6 dimensions via all_slices()
        dim_titles = {
            "year": "按年份",
            "cycle": "按情绪周期",
            "signal_type": "按信号类型",
            "exit_reason": "按出场原因",
            "score": "按评分区间",
            "profit_regime": "按赚钱效应",
        }

        for dim_key, slices in diagnosis.all_slices().items():
            _render_slice_table(dim_titles[dim_key], slices)

        # Bleeding points
        _render_bleeding_points(diagnosis.find_bleeding_points())
