# Hit-Astocker

A股打板量化分析系统 (A-Share Limit-Up Board Hitting Quantitative Analysis System)

## Data Source

- **Tushare Pro** is the sole data provider. All market data must come from Tushare APIs.
- Available APIs include but are not limited to: `limit_list_d`, `limit_step`, `limit_cpt_list`, `kpl_list`, `top_list`, `top_inst`, `moneyflow_ths`, `moneyflow_detail`, `daily_bar`, `index_daily`, `hsgt_top10`, `margin_detail`, `stk_factor`, `cyq_perf`, `moneyflow_ind`, `concept_detail`, `ths_member`, `stk_mins`, `ths_hot`, `stk_surv`, `anns_d`
- Tushare token is stored in `.env` file
- Rate limit: 200 calls/minute (configurable)

## Architecture

```
CLI (Typer) -> Commands -> Analyzers -> Repositories -> SQLite
                            |
                       Signal Generator
                       ├── CompositeScorer (8-factor weighted scoring)
                       ├── RiskAssessor (dynamic thresholds via market context)
                       ├── EventClassifier (事件驱动分类)
                       └── StockSentimentAnalyzer (个股情绪)
                            |
                    Rich Terminal Output
```

## Key Modules

- `analyzers/` - Strategy engines:
  - `sentiment.py` - Market sentiment with index adjustment (大盘联动)
  - `firstboard.py` - First-board scoring (封板时间/强度/纯度/换手/板块)
  - `lianban.py` - Consecutive board ladder (连板天梯)
  - `sector_rotation.py` - Sector rotation tracking
  - `dragon_tiger.py` - Dragon-tiger board analysis
  - `moneyflow.py` / `flow_factors.py` - Money flow (7 sub-factors)
  - `event_classifier.py` - Event-driven classification (涨停原因分类 + 题材热度)
  - `stock_sentiment.py` - Per-stock sentiment scoring (量比/封单/竞价/题材/催化)
  - `market_context.py` - Market index regime analysis (MA5/MA20 + regime scoring)
  - `signal_validator.py` - T+1 signal validation and hit rate tracking
  - `predictor.py` - Buy/sell prediction engine
- `signals/` - Signal generation pipeline:
  - `composite_scorer.py` - 8-factor weighted scoring (情绪/封板/板块/连板/资金/龙虎/事件/个股情绪)
  - `risk_assessor.py` - Dynamic risk thresholds based on market regime
  - `signal_generator.py` - Full signal generation with event + sentiment integration
- `fetchers/` - Tushare data sync (sync_orchestrator + 12 fetchers including index_daily)
- `repositories/` - SQLite data access layer (10 repositories)
- `models/` - Frozen dataclass models
- `commands/` - CLI command handlers (13 commands including `event` and `backtest --detail`)
- `renderers/` - Rich terminal output (tables, dashboard, theme)

## CLI Commands

```
hit-astocker sync -d YYYYMMDD       # Sync all data (including index)
hit-astocker daily -d YYYYMMDD      # Full dashboard with market context + event analysis
hit-astocker sentiment -d YYYYMMDD  # Sentiment with 大盘联动 display
hit-astocker event -d YYYYMMDD      # Event classification + theme heat + stock sentiment
hit-astocker signal -d YYYYMMDD     # Trading signals (8-factor scoring)
hit-astocker backtest -s START -e END [--detail]  # Backtest with T+1 validation
hit-astocker firstboard / lianban / sector / dragon / flow / predict
```

## Scoring System

### Composite Score (8 factors, 0-100):
- 20% 市场情绪 (sentiment, index-adjusted)
- 18% 封板质量 (seal quality)
- 15% 板块归属 (sector)
- 11% 事件催化 (event catalyst) ← NEW
- 10% 连板位置 (lianban position)
- 10% 个股情绪 (stock sentiment) ← NEW
- 8% 资金流向 (capital flow)
- 8% 龙虎榜 (dragon tiger)

### Risk Assessment (Dynamic):
- Thresholds auto-adjust by market regime (STRONG_BULL → STRONG_BEAR)
- Index-based kill conditions (大盘暴跌 → NO_GO)
- 5 levels: LOW → FULL, MEDIUM → HALF, HIGH → QUARTER, EXTREME/NO_GO → ZERO

## Conventions

- Python 3.12+
- Use `pydantic-settings` for configuration
- All scoring on 0-100 scale
- Use `__slots__` for performance-critical data classes
- Immutable tuples for collections in model outputs
- Date format: `date` objects internally, `YYYYMMDD` strings for Tushare API
- Frozen dataclasses for all model outputs
