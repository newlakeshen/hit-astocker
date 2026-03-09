"""Reusable Rich table builders."""

from rich.table import Table

from hit_astocker.renderers.theme import format_amount, pct_color, risk_color, score_color


def sentiment_table(sentiment) -> Table:
    """Build sentiment overview table."""
    table = Table(title="市场情绪概览", show_header=True, header_style="bold cyan")
    table.add_column("指标", style="bold")
    table.add_column("数值", justify="right")

    s = sentiment
    table.add_row("涨停家数", f"[bold red]{s.limit_up_count}[/]")
    table.add_row("跌停家数", f"[bold green]{s.limit_down_count}[/]")
    table.add_row("炸板家数", f"[yellow]{s.broken_count}[/]")
    table.add_row("涨跌停比", f"{s.up_down_ratio:.2f}")
    table.add_row("炸板率", f"{s.broken_rate:.1%}")
    table.add_row("最高连板", f"[bold]{s.max_consecutive_height}[/] 板")
    table.add_row("晋级率", f"{s.promotion_rate:.1%}")
    table.add_row(
        "赚钱效应",
        f"[{score_color(s.money_effect_score)}]{s.money_effect_score:.1f}[/]",
    )
    table.add_row(
        "综合评分",
        f"[{score_color(s.overall_score)}]{s.overall_score:.1f}[/]",
    )
    table.add_row(
        "风险等级",
        f"[{risk_color(s.risk_level)}]{s.risk_level}[/]",
    )
    table.add_row("市场描述", s.description)
    return table


def firstboard_table(results) -> Table:
    """Build first-board analysis table."""
    table = Table(title="首板分析排行", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("行业", width=8)
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
            r.industry[:4],
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


def signal_table(signals) -> Table:
    """Build trading signal table (enhanced with new factors)."""
    table = Table(title="打板信号 (10因子)", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("评分", justify="right", width=6)
    table.add_column("风险", width=6)
    table.add_column("仓位", width=5)
    table.add_column("北向", justify="right", width=4)
    table.add_column("人气", justify="right", width=4)
    table.add_column("技术", justify="right", width=4)
    table.add_column("理由", width=28)

    for i, sig in enumerate(signals[:15], 1):
        nb = sig.factors.get("northbound", 0)
        pop = sig.factors.get("stock_sentiment", 0)
        tech = sig.factors.get("technical_form", 0)
        table.add_row(
            str(i),
            sig.ts_code,
            sig.name,
            f"[{score_color(sig.composite_score)}]{sig.composite_score:.1f}[/]",
            f"[{risk_color(sig.risk_level.value)}]{sig.risk_level.value}[/]",
            sig.position_hint,
            f"[{score_color(nb)}]{nb:.0f}[/]",
            f"[{score_color(pop)}]{pop:.0f}[/]",
            f"[{score_color(tech)}]{tech:.0f}[/]",
            sig.reason[:28],
        )
    return table


def dragon_tiger_table(dragon) -> Table:
    """Build dragon-tiger board table."""
    table = Table(title="龙虎榜分析", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=3)
    table.add_column("代码", width=10)
    table.add_column("名称", width=8)
    table.add_column("涨幅", justify="right", width=7)
    table.add_column("净买入", justify="right", width=10)
    table.add_column("机构净买", justify="right", width=10)
    table.add_column("游资", width=6)
    table.add_column("原因", width=20)

    sorted_records = sorted(dragon.records, key=lambda r: r.net_amount, reverse=True)
    for i, r in enumerate(sorted_records[:15], 1):
        inst_net = dragon.institutional_net_buy.get(r.ts_code, 0)
        has_hot = "Y" if r.ts_code in dragon.hot_money_seats else ""
        is_coop = "*" if r.ts_code in dragon.cooperation_flags else ""

        table.add_row(
            str(i),
            r.ts_code,
            r.name,
            f"[{pct_color(r.pct_change)}]{r.pct_change:.2f}%[/]",
            format_amount(r.net_amount),
            format_amount(inst_net) if inst_net else "-",
            f"[bold red]{has_hot}{is_coop}[/]",
            r.reason[:20],
        )
    return table
