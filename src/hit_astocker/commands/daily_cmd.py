"""Daily dashboard command."""

import logging
from datetime import date

import typer
from rich.console import Console

from hit_astocker.config.settings import get_settings
from hit_astocker.database.connection import get_connection
from hit_astocker.database.migrations import ensure_schema
from hit_astocker.models.daily_context import build_daily_context
from hit_astocker.models.sentiment_cycle import CYCLE_PHASE_HINTS, CYCLE_PHASE_LABELS
from hit_astocker.renderers.dashboard import render_dashboard
from hit_astocker.renderers.theme import APP_THEME
from hit_astocker.signals.signal_generator import SignalGenerator
from hit_astocker.utils.date_utils import from_tushare_date

logger = logging.getLogger(__name__)
daily_app = typer.Typer(name="daily", help="Full daily analysis dashboard")
console = Console(theme=APP_THEME)


def _init_llm(settings, conn):
    """Initialize LLM client and cache if enabled. Returns (client, cache)."""
    if not settings.llm_enabled:
        return None, None

    try:
        from hit_astocker.llm.cache import LLMCache
        from hit_astocker.llm.client import get_llm_client

        client = get_llm_client(settings)
        # NullClient check
        from hit_astocker.llm.client import NullClient
        if isinstance(client, NullClient):
            return None, None

        cache = LLMCache(conn)
        return client, cache
    except Exception:
        logger.warning("LLM initialization failed", exc_info=True)
        return None, None


@daily_app.callback(invoke_without_command=True)
def daily(
    date_str: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD)"),
):
    """Show full daily analysis dashboard."""
    settings = get_settings()

    if date_str:
        trade_date = from_tushare_date(date_str)
    else:
        trade_date = date.today()

    with get_connection(settings.db_path) as conn:
        ensure_schema(conn)

        # Check if data exists
        from hit_astocker.repositories.limit_repo import LimitListRepository
        repo = LimitListRepository(conn)
        counts = repo.count_by_type(trade_date)
        if sum(counts.values()) == 0:
            date_hint = date_str or trade_date.strftime("%Y%m%d")
            console.print(
                f"[yellow]No data for {trade_date}."
                f" Run 'hit-astocker sync -d {date_hint}' first.[/]"
            )
            raise typer.Exit(1)

        # Initialize LLM (optional)
        llm_client, llm_cache = _init_llm(settings, conn)

        # Build context ONCE — all analyzers run here
        ctx = build_daily_context(
            conn, settings, trade_date,
            llm_client=llm_client, llm_cache=llm_cache,
        )

        # Generate signals from pre-computed context (no re-computation)
        signals = SignalGenerator(
            conn, settings, llm_client=llm_client, llm_cache=llm_cache,
        ).generate_from_context(ctx)

        # Sentiment cycle display
        if ctx.sentiment_cycle:
            cyc = ctx.sentiment_cycle
            phase_label = CYCLE_PHASE_LABELS.get(cyc.phase.value, cyc.phase.value)
            phase_hint = CYCLE_PHASE_HINTS.get(cyc.phase.value, "")
            delta_arrow = "↑" if cyc.score_delta > 0 else ("↓" if cyc.score_delta < 0 else "→")
            turning = " [bold yellow]⚡ 拐点[/]" if cyc.is_turning_point else ""
            console.print(
                f"  情绪周期: [bold cyan]{phase_label}[/] {delta_arrow}"
                f" (MA3={cyc.score_ma3:.0f} Δ={cyc.score_delta:+.1f}){turning}\n"
                f"  [dim]{phase_hint}[/]\n"
            )

        # Data coverage warning
        if ctx.coverage.missing_sources:
            missing = ", ".join(ctx.coverage.missing_sources)
            console.print(
                f"[yellow]  ⚠ 数据缺失: {missing}[/]\n"
                "[dim]  对应因子已从评分权重中剔除，不影响其他因子准确性。"
                "运行 sync 补齐数据后自动启用。[/]\n"
            )

        # LLM daily narrative (after all analysis, before rendering)
        narrative = ""
        if llm_client is not None:
            try:
                from hit_astocker.llm.narrative_gen import generate_daily_narrative
                narrative = generate_daily_narrative(
                    llm_client, ctx,
                    cache=llm_cache,
                    use_thinking=settings.kimi_use_thinking,
                )
            except Exception:
                logger.warning("LLM narrative generation failed", exc_info=True)

        render_dashboard(
            console,
            ctx.sentiment,
            list(ctx.firstboard),
            ctx.lianban,
            ctx.sector,
            ctx.dragon,
            signals,
            event_result=ctx.event,
            narrative=narrative,
            profit_effect=ctx.profit_effect,
        )
