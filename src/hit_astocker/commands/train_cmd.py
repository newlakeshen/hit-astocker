"""Model training command — train ML ranking model from executable trade outcomes.

Pipeline:
  1. For each trading day in [start, end]:
     a. Build DailyAnalysisContext (compute all factors)
     b. Apply the same Stage1/risk gating used by live signal generation
     c. Simulate the default T+1/T+2 trade lifecycle
     d. Use realized net PnL > 0 as the training label
  2. Aggregate (features, labels) across all days
  3. Train model (logistic or GBDT)
  4. Save model + quality metadata
"""

import logging
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.utils.date_utils import from_tushare_date, get_trading_days_between

logger = logging.getLogger(__name__)

train_app = typer.Typer(name="train", help="Train ML ranking model")
console = Console(theme=APP_THEME)

# ── Feature label mapping (module-level constant) ──
_FEATURE_LABELS: dict[str, str] = {
    "sentiment": "市场情绪",
    "sector": "板块热度",
    "capital_flow": "资金流向",
    "dragon_tiger": "游资席位",
    "event_catalyst": "事件催化",
    "stock_sentiment": "个股情绪",
    "northbound": "北向资金",
    "technical_form": "技术形态",
    "seal_quality": "封板质量",
    "survival": "晋级率",
    "height_momentum": "高度动能",
    "theme_heat": "题材热度",
    "leader_position": "龙头地位",
    "cycle_phase": "情绪周期",
    "sig_first_board": "首板信号",
    "sig_follow_board": "连板信号",
    "sig_sector_leader": "龙头信号",
    "has_northbound_data": "有北向数据",
    "has_technical_data": "有技术数据",
}


@train_app.callback(invoke_without_command=True)
def train(
    start: str = typer.Option(..., "--start", "-s", help="Training start date (YYYYMMDD)"),
    end: str = typer.Option(..., "--end", "-e", help="Training end date (YYYYMMDD)"),
    model_type: str = typer.Option(
        "logistic", "--model", "-m",
        help="Model type: logistic (可解释) / gbdt (非线性)",
    ),
    min_samples: int = typer.Option(200, "--min-samples", help="Minimum training samples"),
):
    """Train ML ranking model from historical backtest data."""
    settings = get_settings()
    start_date = from_tushare_date(start)
    end_date = from_tushare_date(end)

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        console.print(f"\n  训练区间: {start_date} → {end_date}")
        console.print(f"  模型类型: {model_type}")
        console.print()

        # ── 1. Collect training data ──
        features, labels, meta = _collect_training_data(
            conn, settings, start_date, end_date,
        )

        if len(features) < min_samples:
            console.print(
                f"[red]  样本不足: {len(features)} < {min_samples}[/]\n"
                "  请扩大训练区间或先运行 sync 补充数据。"
            )
            raise typer.Exit(1)

        # ── 2. Train model ──
        from hit_astocker.signals.ranking_model import RankingModel

        model = RankingModel(model_type=model_type)
        pos = sum(labels)
        console.print(f"  训练样本: {len(features)} (正样本 {pos}, 负样本 {len(labels) - pos})")
        console.print("  训练中...")

        metrics = model.train(features, labels)

        # ── 3. Save model ──
        model_path = Path(settings.db_path).parent / "ranking_model.pkl"
        model.save(model_path, metrics)

        # ── 4. Display results ──
        _display_metrics(metrics)
        _display_feature_importance(model)
        _display_training_summary(meta)

        console.print(f"\n  [green]模型已保存: {model_path}[/]")
        if metrics["auc_mean"] >= 0.55:
            console.print("  下次运行 signal 命令将自动使用 ML 模型排序。\n")
        else:
            console.print("  当前模型未达到自动启用阈值，signal 命令将继续使用规则排序。\n")


def _collect_training_data(
    conn, settings, start_date: date, end_date: date,
) -> tuple[list[list[float]], list[int], dict]:
    """Collect (features, labels) from historical data.

    For each trading day:
      1. Compute factors for all candidates
      2. Apply the same Stage1/risk gating used in live signal generation
      3. Simulate the default executable trade and use realized PnL as label

    Performance: pre-loads limit_list_d/limit_step/kpl_list data for the full
    date range in 3 bulk SQL queries, then all per-day lookups use in-memory
    data. This eliminates ~80% of individual SQL queries.
    """
    import time

    from hit_astocker.analyzers.backtest_engine import BacktestEngine
    from hit_astocker.models.backtest import BacktestConfig
    from hit_astocker.models.daily_context import (
        DataCoverage,
        DailyContextCaches,
        build_daily_context,
        table_has_data,
    )
    from hit_astocker.models.signal import RiskLevel, SignalType, TradingSignal
    from hit_astocker.repositories.kpl_repo import KplRepository
    from hit_astocker.repositories.limit_repo import LimitListRepository
    from hit_astocker.repositories.limit_step_repo import LimitStepRepository
    from hit_astocker.signals.composite_scorer import CompositeScorer
    from hit_astocker.signals.feature_builder import build_feature_vector
    from hit_astocker.signals.risk_assessor import RiskAssessor
    from hit_astocker.signals.stage1_filter import Stage1Filter
    from hit_astocker.utils.date_utils import get_next_trading_day

    engine = BacktestEngine(conn)
    scorer = CompositeScorer(settings)
    stage1_filter = Stage1Filter()
    risk_assessor = RiskAssessor()
    config = BacktestConfig()

    trading_days = get_trading_days_between(start_date, end_date)

    # ── Pre-warm: bulk preload repos for entire training range ──
    from datetime import timedelta

    preload_start = start_date - timedelta(days=20)  # lookback buffer
    preload_end = end_date + timedelta(days=5)  # T+2 exit buffer
    console.print("  预加载数据...")

    limit_repo = LimitListRepository(conn)
    limit_repo.preload_range(preload_start, preload_end)

    step_repo = LimitStepRepository(conn)
    step_repo.preload_range(preload_start, preload_end)

    kpl_repo = KplRepository(conn)
    kpl_repo.preload_range(preload_start, preload_end)

    # Global coverage: tables either have data or don't (check once)
    global_coverage = DataCoverage(
        has_ths_hot=table_has_data(conn, "ths_hot"),
        has_hsgt=table_has_data(conn, "hsgt_top10"),
        has_stk_factor=table_has_data(conn, "stk_factor_pro"),
        has_hm=table_has_data(conn, "hm_detail"),
        has_auction=table_has_data(conn, "stk_auction"),
    )

    from hit_astocker.repositories.hm_repo import HmRepository
    hm_repo = HmRepository(conn)

    context_caches = DailyContextCaches(
        limit_repo=limit_repo,
        step_repo=step_repo,
        kpl_repo=kpl_repo,
        hm_repo=hm_repo,
        global_coverage=global_coverage,
    )

    features: list[list[float]] = []
    labels: list[int] = []
    meta = {
        "days_processed": 0,
        "days_skipped": 0,
        "signals_executed": 0,
        "signals_skipped": 0,
        "total_days": len(trading_days),
    }
    loop_start = time.monotonic()

    with console.status("  收集训练数据...") as status:
        for i, td in enumerate(trading_days):
            # ETA display
            elapsed = time.monotonic() - loop_start
            if i > 0 and elapsed > 0:
                rate = i / elapsed
                eta = (len(trading_days) - i) / rate
                eta_str = f" ETA {eta:.0f}s"
            else:
                eta_str = ""
            status.update(
                f"  收集训练数据... [{i + 1}/{len(trading_days)}] {td}{eta_str}"
            )
            try:
                next_td = get_next_trading_day(td)
                exit_td = get_next_trading_day(next_td) if next_td else None
                if not next_td or not exit_td:
                    meta["days_skipped"] += 1
                    continue

                ctx = build_daily_context(conn, settings, td, caches=context_caches)

                # Get scored candidates (factors extracted)
                scored = scorer.score(
                    ctx.sentiment,
                    list(ctx.firstboard),
                    ctx.lianban,
                    ctx.sector,
                    ctx.dragon,
                    list(ctx.moneyflow),
                    event_result=ctx.event,
                    stock_sentiments=list(ctx.stock_sentiments),
                    survival_model=ctx.survival_model,
                    hsgt_net_map=ctx.hsgt_net_map,
                    coverage=ctx.coverage,
                    cycle=ctx.sentiment_cycle,
                )

                if not scored:
                    meta["days_skipped"] += 1
                    continue

                survivors = stage1_filter.filter(scored, ctx)
                if not survivors:
                    meta["days_skipped"] += 1
                    continue

                signal_features: list[tuple[TradingSignal, list[float]]] = []
                for candidate in survivors:
                    risk = risk_assessor.assess(
                        candidate, ctx.sentiment, cycle=ctx.sentiment_cycle,
                    )
                    if risk == RiskLevel.NO_GO:
                        continue
                    signal = TradingSignal(
                        trade_date=ctx.trade_date,
                        ts_code=candidate.ts_code,
                        name=candidate.name,
                        signal_type=SignalType(candidate.signal_type),
                        composite_score=candidate.score,
                        risk_level=risk,
                        position_hint=RiskAssessor.position_hint(risk),
                        factors=candidate.factors,
                        reason="",
                        score_source="rules",
                    )
                    signal_features.append((
                        signal,
                        build_feature_vector(
                            candidate.factors,
                            candidate.signal_type,
                            ctx.sentiment_cycle,
                            ctx.coverage,
                        ),
                    ))

                if not signal_features:
                    meta["days_skipped"] += 1
                    continue

                day_result = engine.simulate_day(
                    [signal for signal, _ in signal_features],
                    config,
                    td,
                    next_td,
                    exit_td,
                )
                trade_map = {trade.ts_code: trade for trade in day_result.trades}
                for signal, vec in signal_features:
                    trade = trade_map.get(signal.ts_code)
                    if trade is None:
                        continue
                    features.append(vec)
                    labels.append(1 if trade.pnl_pct > 0 else 0)

                meta["signals_executed"] += len(day_result.trades)
                meta["signals_skipped"] += len(day_result.skipped)

                meta["days_processed"] += 1

            except Exception:
                logger.warning("Training: failed to process %s", td, exc_info=True)
                meta["days_skipped"] += 1
                continue

    return features, labels, meta


def _display_metrics(metrics: dict) -> None:
    """Display training evaluation metrics."""
    table = Table(title="模型评估指标", show_header=True)
    table.add_column("指标", style="cyan")
    table.add_column("值", style="bold")

    table.add_row("模型类型", str(metrics["model_type"]))
    table.add_row("训练样本", str(metrics["n_samples"]))
    table.add_row("正样本率", f"{metrics['positive_rate']:.1%}")
    table.add_row(
        "AUC (交叉验证)",
        f"{metrics['auc_mean']:.4f} ± {metrics['auc_std']:.4f}",
    )
    table.add_row("准确率", f"{metrics['accuracy_mean']:.4f}")
    table.add_row("交叉验证折数", str(metrics["cv_folds"]))

    auc = metrics["auc_mean"]
    if auc >= 0.65:
        quality = "[green]模型有效 (AUC > 0.65)[/]"
    elif auc >= 0.55:
        quality = "[yellow]模型较弱 (AUC 0.55-0.65), 建议增加训练数据[/]"
    else:
        quality = "[red]模型无效 (AUC < 0.55), 不建议使用[/]"
    table.add_row("质量评估", quality)

    console.print()
    console.print(table)


def _display_feature_importance(model) -> None:
    """Display top feature importances."""
    top = model.top_features(n=10)
    if not top:
        return

    table = Table(title="特征重要性 (Top 10)", show_header=True)
    table.add_column("特征", style="cyan")
    table.add_column("重要性", style="bold", justify="right")
    table.add_column("方向", justify="center")

    for feat, imp in top:
        label = _FEATURE_LABELS.get(feat, feat)
        direction = "[green]正向[/]" if imp > 0 else "[red]负向[/]"
        table.add_row(label, f"{imp:.4f}", direction)

    console.print()
    console.print(table)


def _display_training_summary(meta: dict) -> None:
    """Display training data collection summary."""
    console.print(
        Panel(
            f"处理交易日: {meta['days_processed']}/{meta['total_days']}\n"
            f"跳过交易日: {meta['days_skipped']}\n"
            f"可执行样本: {meta['signals_executed']}\n"
            f"被跳过信号: {meta['signals_skipped']}",
            title="数据收集",
        )
    )
