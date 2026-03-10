"""Trading signal command."""

from datetime import date

import typer
from rich.console import Console

from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.models.daily_context import build_daily_context
from hit_astocker.models.sentiment_cycle import CYCLE_PHASE_HINTS, CYCLE_PHASE_LABELS
from hit_astocker.renderers.tables import signal_table
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.signals.signal_generator import SignalGenerator
from hit_astocker.utils.date_utils import from_tushare_date

signal_app = typer.Typer(name="signal", help="Trading signal generation")
console = Console(theme=APP_THEME)


@signal_app.callback(invoke_without_command=True)
def signal(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
    max_risk: str = typer.Option("HIGH", "--risk", "-r", help="Max risk level: LOW/MEDIUM/HIGH"),
):
    """Generate and display trading signals."""
    settings = get_settings()
    trade_date = from_tushare_date(date_str) if date_str else date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        ctx = build_daily_context(conn, settings, trade_date)

        # Sentiment cycle display
        if ctx.sentiment_cycle:
            cyc = ctx.sentiment_cycle
            phase_label = CYCLE_PHASE_LABELS.get(cyc.phase.value, cyc.phase.value)
            phase_hint = CYCLE_PHASE_HINTS.get(cyc.phase.value, "")
            delta_arrow = "↑" if cyc.score_delta > 0 else ("↓" if cyc.score_delta < 0 else "→")
            console.print(
                f"  情绪周期: [bold cyan]{phase_label}[/] {delta_arrow}"
                f" (MA3={cyc.score_ma3:.0f} Δ={cyc.score_delta:+.1f})\n"
                f"  [dim]{phase_hint}[/]\n"
            )

        # Data coverage warning
        if ctx.coverage.missing_sources:
            missing = ", ".join(ctx.coverage.missing_sources)
            console.print(
                f"[yellow]  ⚠ 数据缺失: {missing}[/]\n"
                "[dim]  对应因子已从评分权重中剔除。运行 sync 补齐数据后自动启用。[/]\n"
            )

        generator = SignalGenerator(conn, settings)
        signals = generator.generate_from_context(ctx)

        # Filter by risk
        risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "EXTREME": 3, "NO_GO": 4}
        max_risk_val = risk_order.get(max_risk.upper(), 2)
        filtered = [
            s for s in signals
            if risk_order.get(s.risk_level.value, 4) <= max_risk_val
        ]

        if filtered:
            console.print(signal_table(filtered))
            console.print(f"\n  共 {len(filtered)} 个信号 (最大风险: {max_risk})")
        else:
            console.print("[dim]  无满足条件的信号[/]")

        # Summary
        if signals:
            avg_score = sum(s.composite_score for s in signals) / len(signals)
            score_source = signals[0].score_source if signals else "rules"
            source_label = "ML模型" if score_source == "model" else "规则打分"
            console.print(f"  平均评分: {avg_score:.1f}  (评分来源: {source_label})")
