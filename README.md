# Hit-Astocker

A-Stock limit-up board hitting quantitative trading analysis system (A股打板量化分析系统)

## Features

- **Market Sentiment Scoring** - 涨停/跌停比、炸板率、连板高度、赚钱效应综合评分
- **First-Board Analysis** - 首板评分: 封板时间、封板强度、封板纯度、换手率、板块归属
- **Consecutive Board Ladder** - 连板天梯: 各层级晋级率、空间板龙头识别
- **Sector Rotation Tracking** - 板块轮动: 热点持续性、新进/掉出板块、板块龙头
- **Dragon-Tiger Board Analysis** - 龙虎榜: 机构净买入、游资席位追踪、合力检测
- **Money Flow Analysis** - 资金流向: 主力净流入、大单/中单/小单分析
- **Signal Generation** - 综合打板信号: 多因子评分、风险分级、仓位建议

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Set Tushare token
cp .env.example .env
# Edit .env with your token

# Sync data
hit-astocker sync -d 20260306

# Full daily dashboard
hit-astocker daily -d 20260306

# Individual analyses
hit-astocker sentiment -d 20260306
hit-astocker lianban -d 20260306
hit-astocker sector -d 20260306
hit-astocker firstboard -d 20260306
hit-astocker dragon -d 20260306
hit-astocker signal -d 20260306

# Backtest
hit-astocker backtest
hit-astocker backtest --years 6
hit-astocker backtest -s 20260301 -e 20260306

# Batch sync
hit-astocker sync --start 20260301 --end 20260306
hit-astocker sync --years 6
```

## Architecture

```
CLI (Typer) -> Commands -> Analyzers -> Repositories -> SQLite
                            |
                       Signal Generator
                            |
                    Rich Terminal Output
```

## Data Sources (Tushare Pro)

| API | Description |
|-----|-------------|
| `limit_list_d` | 涨跌停/炸板数据 |
| `limit_step` | 连板天梯 |
| `limit_cpt_list` | 涨停最强板块 |
| `kpl_list` | 开盘啦涨停榜 |
| `top_list` | 龙虎榜每日交易 |
| `top_inst` | 龙虎榜机构明细 |
| `moneyflow_ths` | 同花顺资金流向 |

## Scoring Methodology

### Sentiment Score (0-100)
- 30% 涨跌停比 (up/down ratio)
- 25% 封板成功率 (1 - broken rate)
- 20% 连板晋级率 (promotion rate)
- 15% 最高连板高度 (max height)
- 10% 涨停数量趋势 (first-board trend)

### Risk Levels
- **LOW**: Score > 65, all conditions met
- **MEDIUM**: Score 50-65
- **HIGH**: Score 40-50 or weak seal quality
- **NO_GO**: Score < 40 or broken rate > 50%
