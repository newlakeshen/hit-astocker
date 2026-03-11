"""Daily market narrative generation via LLM."""

import json
import logging

from hit_astocker.llm.cache import LLMCache
from hit_astocker.llm.client import LLMClient, NullClient
from hit_astocker.llm.models import ThemeCluster
from hit_astocker.llm.prompts import (
    BACKTEST_NARRATIVE_PROMPT,
    SIGNAL_REASON_PROMPT,
    THEME_CLUSTER_PROMPT,
)

logger = logging.getLogger(__name__)


def generate_daily_narrative(
    client: LLMClient,
    ctx,
    *,
    cache: LLMCache | None = None,
    use_thinking: bool = False,
) -> str:
    """Generate a ≤200 char market narrative from DailyAnalysisContext.

    Parameters
    ----------
    client : LLMClient (KimiClient or NullClient)
    ctx : DailyAnalysisContext
    cache : optional LLMCache for deduplication
    use_thinking : use Thinking Mode for deeper analysis

    Returns
    -------
    str — market narrative, or empty string on failure/NullClient
    """
    if isinstance(client, NullClient):
        return ""

    trade_date_str = ctx.trade_date.strftime("%Y%m%d")

    # Build market data summary for prompt
    market_data = _build_market_data(ctx)
    market_json = json.dumps(market_data, ensure_ascii=False, indent=2)

    # Check cache
    cache_key = None
    if cache:
        cache_key = LLMCache.make_key(trade_date_str, "daily_narrative", market_json)
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("LLM daily narrative: cache hit")
            return cached

    from hit_astocker.llm.prompts import DAILY_NARRATIVE_PROMPT
    prompt = DAILY_NARRATIVE_PROMPT.format(market_data=market_json)

    try:
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0 if use_thinking else 0.6,
            use_thinking=use_thinking,
        )
    except Exception:
        logger.warning("LLM daily narrative failed", exc_info=True)
        return ""

    narrative = response.strip()

    if narrative and cache and cache_key:
        cache.put(cache_key, narrative)

    return narrative


def generate_signal_reasons(
    client: LLMClient,
    signals: list,
    event_result=None,
    *,
    cache: LLMCache | None = None,
) -> dict[str, str]:
    """Generate LLM-enhanced signal reasons for a batch of signals.

    Returns
    -------
    dict[str, str] — ts_code → reason string, or empty dict on failure
    """
    if isinstance(client, NullClient) or not signals:
        return {}

    # Build signals data for prompt
    signals_data = []
    ev_map = {}
    if event_result:
        ev_map = {ev.ts_code: ev for ev in event_result.stock_events}

    for sig in signals:
        entry = {
            "ts_code": sig.ts_code,
            "name": sig.name,
            "signal_type": (
                sig.signal_type.value
                if hasattr(sig.signal_type, "value")
                else str(sig.signal_type)
            ),
            "composite_score": sig.composite_score,
            "factors": sig.factors,
        }
        ev = ev_map.get(sig.ts_code)
        if ev:
            entry["event_type"] = ev.event_type
            entry["lu_desc"] = ev.lu_desc
        signals_data.append(entry)

    signals_json = json.dumps(signals_data, ensure_ascii=False, indent=2)

    # Check cache
    trade_date_str = str(signals[0].trade_date) if signals else ""
    cache_key = None
    if cache:
        cache_key = LLMCache.make_key(trade_date_str, "signal_reasons", signals_json)
        cached = cache.get_json(cache_key)
        if cached is not None:
            logger.info("LLM signal reasons: cache hit")
            return {item["ts_code"]: item["reason"] for item in cached
                    if isinstance(item, dict)}

    prompt = SIGNAL_REASON_PROMPT.format(signals_data=signals_json)

    try:
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            use_thinking=False,
        )
    except Exception:
        logger.warning("LLM signal reasons failed", exc_info=True)
        return {}

    # Parse response
    result = _parse_json_response(response)
    if not result:
        return {}

    reason_map = {}
    for item in result:
        if isinstance(item, dict) and "ts_code" in item and "reason" in item:
            reason_map[item["ts_code"]] = item["reason"]

    if reason_map and cache and cache_key:
        cache.put_json(cache_key, result)

    return reason_map


def cluster_themes(
    client: LLMClient,
    themes: list[str],
    *,
    trade_date: str = "",
    cache: LLMCache | None = None,
) -> list[ThemeCluster]:
    """Cluster related themes into main investment themes via LLM.

    Returns
    -------
    list[ThemeCluster] — clustered themes, or empty list on failure
    """
    if isinstance(client, NullClient) or not themes:
        return []

    themes_str = "\n".join(f"- {t}" for t in themes)

    cache_key = None
    if cache:
        cache_key = LLMCache.make_key(trade_date, "theme_cluster", themes_str)
        cached = cache.get_json(cache_key)
        if cached is not None:
            logger.info("LLM theme cluster: cache hit")
            return _parse_theme_clusters(cached)

    prompt = THEME_CLUSTER_PROMPT.format(themes=themes_str)

    try:
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            use_thinking=False,
        )
    except Exception:
        logger.warning("LLM theme cluster failed", exc_info=True)
        return []

    data = _parse_json_response(response)
    if not data:
        return []

    clusters = _parse_theme_clusters(data)

    if clusters and cache and cache_key:
        cache.put_json(cache_key, data)

    return clusters


def generate_backtest_narrative(
    client: LLMClient,
    stats,
    trades: list,
    *,
    cache: LLMCache | None = None,
    use_thinking: bool = True,
) -> str:
    """Generate backtest performance analysis via LLM.

    Uses Thinking Mode by default for deeper strategy insights.

    Returns
    -------
    str — analysis text, or empty string on failure
    """
    if isinstance(client, NullClient):
        return ""

    backtest_data = {
        "total_signals": stats.total_signals,
        "traded_count": stats.traded_count,
        "skipped_count": stats.skipped_count,
        "hit_rate": f"{stats.hit_rate:.1%}",
        "avg_pnl": f"{stats.avg_pnl:+.2f}%",
        "total_pnl": f"{stats.total_pnl:+.2f}%",
        "max_win": f"{stats.max_win:+.2f}%",
        "max_loss": f"{stats.max_loss:+.2f}%",
        "profit_factor": f"{stats.profit_factor:.2f}",
        "consecutive_losses": stats.consecutive_losses,
        "by_type": {k: {"count": v.count, "hit_rate": f"{v.hit_rate:.1%}",
                        "avg_pnl": f"{v.avg_pnl:+.2f}%"}
                    for k, v in stats.by_type.items()},
        "by_exit": {k: {"count": v.count, "avg_pnl": f"{v.avg_pnl:+.2f}%"}
                    for k, v in stats.by_exit.items()},
        "sample_trades": [
            {"date": str(t.trade_date), "code": t.ts_code, "name": t.name,
             "type": t.signal_type, "pnl": f"{t.pnl_pct:+.2f}%",
             "exit": t.exit_reason}
            for t in trades[:20]
        ],
    }
    backtest_json = json.dumps(backtest_data, ensure_ascii=False, indent=2)

    cache_key = None
    if cache:
        cache_key = LLMCache.make_key("", "backtest_narrative", backtest_json)
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("LLM backtest narrative: cache hit")
            return cached

    prompt = BACKTEST_NARRATIVE_PROMPT.format(backtest_data=backtest_json)

    try:
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0 if use_thinking else 0.6,
            use_thinking=use_thinking,
        )
    except Exception:
        logger.warning("LLM backtest narrative failed", exc_info=True)
        return ""

    narrative = response.strip()

    if narrative and cache and cache_key:
        cache.put(cache_key, narrative)

    return narrative


def _build_market_data(ctx) -> dict:
    """Serialize DailyAnalysisContext into a compact dict for the prompt."""
    data: dict = {
        "trade_date": str(ctx.trade_date),
        "sentiment_score": ctx.sentiment.overall_score,
        "sentiment_desc": ctx.sentiment.description,
    }

    # Market context
    mctx = ctx.sentiment.market_context
    if mctx:
        data["market_regime"] = mctx.market_regime
        data["sh_pct_chg"] = f"{mctx.sh_pct_chg:+.2f}%"
        data["gem_pct_chg"] = f"{mctx.gem_pct_chg:+.2f}%"

    # Sentiment cycle
    if ctx.sentiment_cycle:
        data["cycle_phase"] = ctx.sentiment_cycle.phase.value
        data["cycle_delta"] = ctx.sentiment_cycle.score_delta
        data["is_turning_point"] = ctx.sentiment_cycle.is_turning_point

    # Event analysis
    if ctx.event:
        data["dominant_event"] = ctx.event.dominant_event_type
        data["event_distribution"] = ctx.event.event_distribution
        data["theme_concentration"] = ctx.event.theme_concentration
        # Top themes
        data["top_themes"] = [
            {"name": th.theme_name, "count": th.today_count,
             "trend": th.heat_trend, "heat": th.heat_score,
             "lifecycle": th.lifecycle}
            for th in ctx.event.theme_heats[:5]
        ]

    # Lianban
    data["max_height"] = ctx.lianban.max_height
    if ctx.lianban.leader_name:
        data["leader"] = f"{ctx.lianban.leader_name}({ctx.lianban.max_height}连板)"

    # Sector rotation
    data["rotation_detected"] = ctx.sector.rotation_detected

    return data


def _parse_json_response(response: str) -> list | None:
    """Parse LLM response as JSON array, stripping markdown fences."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM JSON parse failed: %s", text[:200])
        return None

    if not isinstance(data, list):
        return None
    return data


def _parse_theme_clusters(data: list) -> list[ThemeCluster]:
    """Parse raw dicts into ThemeCluster objects."""
    clusters = []
    for item in data:
        if not isinstance(item, dict):
            continue
        main_theme = item.get("main_theme", "")
        sub_themes = tuple(item.get("sub_themes", []))
        narrative = item.get("narrative", "")
        if main_theme:
            clusters.append(ThemeCluster(
                main_theme=main_theme,
                sub_themes=sub_themes,
                narrative=narrative,
            ))
    return clusters
