"""Reusable Rich table builders."""

from __future__ import annotations

from rich.table import Table

from hit_astocker.renderers.theme import format_amount, pct_color, risk_color, score_color


def sentiment_table(sentiment) -> Table:
    """Build sentiment overview table (9-factor enhanced)."""
    table = Table(title="市场情绪概览 (9因子)", show_header=True, header_style="bold cyan")
    table.add_column("指标", style="bold", width=16)
    table.add_column("数值", justify="right", width=12)
    table.add_column("指标", style="bold", width=16)
    table.add_column("数值", justify="right", width=12)

    s = sentiment
    # Row 1: 涨停 / 跌停
    table.add_row(
        "涨停家数", f"[bold red]{s.limit_up_count}[/]",
        "跌停家数", f"[bold green]{s.limit_down_count}[/]",
    )
    # Row 2: 炸板 / 回封
    table.add_row(
        "炸板家数", f"[yellow]{s.broken_count}[/]",
        "回封数", f"[bold]{s.recovery_count}[/]",
    )
    # Row 3: 涨跌停比 / 炸板修复率
    table.add_row(
        "涨跌停比", f"{s.up_down_ratio:.2f}",
        "炸板修复率", f"{s.broken_recovery_rate:.1%}",
    )
    # Row 4: 一字板 / 炸板率
    table.add_row(
        "一字板", f"{s.yizi_count} ({s.yizi_ratio:.0%})",
        "炸板率", f"{s.broken_rate:.1%}",
    )
    # Row 5: 10cm / 20cm 涨停
    table.add_row(
        "10cm涨停/炸", f"[bold red]{s.limit_up_10cm}[/]/[yellow]{s.broken_10cm}[/]",
        "20cm涨停/炸", f"[bold red]{s.limit_up_20cm}[/]/[yellow]{s.broken_20cm}[/]",
    )
    # Row 6: 连板高度 / 晋级率
    table.add_row(
        "最高连板", f"[bold]{s.max_consecutive_height}[/] 板",
        "总晋级率", f"{s.promotion_rate:.1%}",
    )
    # Row 7: 2→3 / 3→4 晋级率
    table.add_row(
        "2→3板晋级", f"{s.promo_rate_2to3:.0%}",
        "3→4板晋级", f"{s.promo_rate_3to4:.0%}",
    )
    # Row 8: 次日溢价 / 竞价强弱
    premium_color = pct_color(s.prev_limit_up_premium)
    table.add_row(
        "昨涨停次日溢价", f"[{premium_color}]{s.prev_limit_up_premium:+.2f}%[/]",
        "竞价均涨", f"[{pct_color(s.auction_avg_pct)}]{s.auction_avg_pct:+.2f}%[/]",
    )
    # Row 9: 竞价高开比 / 赚钱效应
    table.add_row(
        "竞价高开比", f"{s.auction_up_ratio:.0%}",
        "赚钱效应",
        f"[{score_color(s.money_effect_score)}]{s.money_effect_score:.1f}[/]",
    )
    # Row 10: 综合评分 / 风险等级
    table.add_row(
        "综合评分",
        f"[{score_color(s.overall_score)}]{s.overall_score:.1f}[/]",
        "风险等级",
        f"[{risk_color(s.risk_level)}]{s.risk_level}[/]",
    )
    # Row 11: 描述
    table.add_row("市场描述", s.description, "", "")
    return table


def firstboard_table(results) -> Table:
    """Build first-board analysis table."""
    table = Table(title="首板分析排行", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("题材", width=8)
    table.add_column("封板时间", width=9)
    table.add_column("开板次数", justify="right", width=5)
    table.add_column("封单/流通", justify="right", width=8)
    table.add_column("换手率", justify="right", width=7)
    table.add_column("综合评分", justify="right", width=8)

    for i, r in enumerate(results[:20], 1):
        seal_ratio = r.limit_amount / r.float_mv * 100 if r.float_mv > 0 else 0
        table.add_row(
            str(i),
            r.ts_code,
            r.name,
            (r.sector_name or r.industry)[:4],
            r.first_time[:5] if r.first_time else "-",
            str(r.open_times),
            f"{seal_ratio:.1f}%",
            f"{r.turnover_ratio:.1f}%",
            f"[{score_color(r.composite_score)}]{r.composite_score:.1f}[/]",
        )
    return table


def lianban_table(lianban) -> Table:
    """Build consecutive board ladder table."""
    table = Table(title="连板天梯", show_header=True, header_style="bold cyan")
    table.add_column("高度", justify="center", width=5)
    table.add_column("数量", justify="right", width=5)
    table.add_column("昨日", justify="right", width=5)
    table.add_column("晋级率", justify="right", width=7)
    table.add_column("个股", width=40)

    for tier in lianban.tiers:
        names = ", ".join(tier.stock_names[:5])
        if len(tier.stock_names) > 5:
            names += f" (+{len(tier.stock_names) - 5})"
        promo_str = f"{tier.promotion_rate:.0%}" if tier.yesterday_count > 0 else "-"
        table.add_row(
            f"{tier.height}板",
            str(tier.count),
            str(tier.yesterday_count),
            promo_str,
            names,
        )
    return table


def sector_table(sector_result) -> Table:
    """Build sector rotation table."""
    table = Table(title="涨停板块排行", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("板块名称", width=12)
    table.add_column("涨停数", justify="right", width=6)
    table.add_column("连板数", justify="right", width=6)
    table.add_column("上榜天数", justify="right", width=6)
    table.add_column("涨幅", justify="right", width=7)
    table.add_column("状态", width=6)

    continuing = set(sector_result.continuing_sectors)
    new = set(sector_result.new_sectors)

    for i, s in enumerate(sector_result.top_sectors[:10], 1):
        if s.name in continuing:
            status = "[bold red]持续[/]"
        elif s.name in new:
            status = "[yellow]新进[/]"
        else:
            status = ""
        table.add_row(
            str(i),
            s.name,
            str(s.up_nums),
            str(s.cons_nums),
            str(s.days),
            f"[{pct_color(s.pct_chg)}]{s.pct_chg:.2f}%[/]",
            status,
        )
    return table


_SIGNAL_TYPE_LABELS = {
    "FIRST_BOARD": "[bold red]首板[/]",
    "FOLLOW_BOARD": "[bold yellow]连板[/]",
    "SECTOR_LEADER": "[bold cyan]龙头[/]",
}


def signal_table(signals) -> Table:
    """Build trading signal table — shows type-specific key factor."""
    table = Table(title="打板信号 (三模型)", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("类型", width=4)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("评分", justify="right", width=6)
    table.add_column("风险", width=6)
    table.add_column("仓位", width=5)
    table.add_column("核心", justify="right", width=5)
    table.add_column("题材", width=8)
    table.add_column("理由", width=28)

    for i, sig in enumerate(signals[:15], 1):
        f = sig.factors
        # Type-specific key factor display
        sig_type = sig.signal_type.value
        if sig_type == "FIRST_BOARD":
            key_val = f.get("seal_quality", 0)
            key_label = f"封{key_val:.0f}"
        elif sig_type == "FOLLOW_BOARD":
            key_val = f.get("survival", 0)
            key_label = f"存{key_val:.0f}"
        else:
            key_val = f.get("theme_heat", 0)
            key_label = f"热{key_val:.0f}"

        theme_display = sig.theme[:8] if hasattr(sig, "theme") and sig.theme else "-"
        type_label = _SIGNAL_TYPE_LABELS.get(sig_type, sig_type)
        table.add_row(
            str(i),
            type_label,
            sig.ts_code,
            sig.name,
            f"[{score_color(sig.composite_score)}]{sig.composite_score:.1f}[/]",
            f"[{risk_color(sig.risk_level.value)}]{sig.risk_level.value}[/]",
            sig.position_hint,
            f"[{score_color(key_val)}]{key_label}[/]",
            theme_display,
            sig.reason[:28],
        )
    return table


def dragon_tiger_table(dragon) -> Table:
    """Build dragon-tiger board table with quantified seat profiles."""
    table = Table(title="龙虎榜分析", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("涨幅", justify="right", width=7)
    table.add_column("净买入", justify="right", width=10)
    table.add_column("机构净买", justify="right", width=10)
    table.add_column("游资", width=8)
    table.add_column("胜率", justify="right", width=5)
    table.add_column("原因", width=16)

    sorted_records = sorted(dragon.records, key=lambda r: r.net_amount, reverse=True)
    for i, r in enumerate(sorted_records[:15], 1):
        inst_net = dragon.institutional_net_buy.get(r.ts_code, 0)
        seat = dragon.seat_scores.get(r.ts_code)

        if seat:
            count = seat.known_trader_count
            coop = "+" if seat.is_coordinated else ""
            seat_label = f"[bold red]{count}席{coop}[/]"
            wr = f"{seat.max_win_rate:.0%}"
        else:
            seat_label = "-"
            wr = "-"

        table.add_row(
            str(i),
            r.ts_code,
            r.name,
            f"[{pct_color(r.pct_change)}]{r.pct_change:.2f}%[/]",
            format_amount(r.net_amount),
            format_amount(inst_net) if inst_net else "-",
            seat_label,
            wr,
            r.reason[:16],
        )
    return table


# ── Profit effect ──


_REGIME_STYLES = {
    "STRONG": "[bold red]STRONG[/]",
    "NORMAL": "[bold yellow]NORMAL[/]",
    "WEAK": "[bold green]WEAK[/]",
    "FROZEN": "[bold blue]FROZEN[/]",
}

_REGIME_HINTS = {
    "STRONG": "多层溢价正/胜率高 → 积极参与",
    "NORMAL": "部分层有赚钱效应 → 正常参与",
    "WEAK": "赚钱效应偏弱 → 精选高确定性",
    "FROZEN": "全面亏钱效应 → 空仓观望",
}


def profit_effect_table(
    snapshot,
    *,
    title_suffix: str = "",
) -> Table:
    """Build profit effect stratification table.

    Shows per-tier metrics: premium, return, win_rate, broken_rate, participation.
    """
    from hit_astocker.models.profit_effect import ProfitEffectSnapshot

    pe: ProfitEffectSnapshot = snapshot
    regime_label = _REGIME_STYLES.get(pe.regime.value, pe.regime.value)
    table = Table(
        title=f"赚钱效应分层{title_suffix} ({regime_label} {pe.regime_score:.0f})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("层级", width=6)
    table.add_column("昨数", justify="right", width=4)
    table.add_column("次日溢价", justify="right", width=8)
    table.add_column("次日收益", justify="right", width=8)
    table.add_column("胜率", justify="right", width=5)
    table.add_column("今数", justify="right", width=4)
    table.add_column("炸板率", justify="right", width=6)
    table.add_column("可参与", justify="right", width=6)

    for t in pe.by_height:
        table.add_row(
            f"[bold]{t.tier}[/]",
            str(t.prev_count),
            f"[{pct_color(t.avg_premium)}]{t.avg_premium:+.2f}%[/]",
            f"[{pct_color(t.avg_return)}]{t.avg_return:+.2f}%[/]",
            f"{t.win_rate:.0%}",
            str(t.today_count),
            f"[{_broken_color(t.broken_rate)}]{t.broken_rate:.0%}[/]",
            f"{t.non_yizi_rate:.0%}",
        )

    # 总体行
    table.add_row(
        "[dim]总体[/]",
        str(pe.overall_count),
        f"[{pct_color(pe.overall_premium)}]{pe.overall_premium:+.2f}%[/]",
        "",
        f"{pe.overall_win_rate:.0%}",
        "",
        "",
        "",
    )

    return table


def profit_effect_split_table(snapshot) -> Table | None:
    """Build 10cm/20cm split table (compact).

    Returns None if neither split has data.
    """
    from hit_astocker.models.profit_effect import ProfitEffectSnapshot

    pe: ProfitEffectSnapshot = snapshot
    if not pe.by_height_10cm and not pe.by_height_20cm:
        return None

    table = Table(
        title="赚钱效应: 10cm vs 20cm",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("类型", width=6)
    table.add_column("层级", width=6)
    table.add_column("昨数", justify="right", width=4)
    table.add_column("溢价", justify="right", width=7)
    table.add_column("胜率", justify="right", width=5)
    table.add_column("炸板", justify="right", width=5)

    for label, tiers in [("10cm", pe.by_height_10cm), ("20cm", pe.by_height_20cm)]:
        for i, t in enumerate(tiers):
            type_col = f"[bold]{label}[/]" if i == 0 else ""
            table.add_row(
                type_col,
                t.tier,
                str(t.prev_count),
                f"[{pct_color(t.avg_premium)}]{t.avg_premium:+.2f}%[/]",
                f"{t.win_rate:.0%}",
                f"[{_broken_color(t.broken_rate)}]{t.broken_rate:.0%}[/]",
            )

    return table


def _broken_color(rate: float) -> str:
    """Color for broken rate (high = bad)."""
    if rate >= 0.40:
        return "bold red"
    if rate >= 0.25:
        return "yellow"
    return "green"
