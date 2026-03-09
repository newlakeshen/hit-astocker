# Hit-Astocker

A股打板量化分析系统 (A-Share Limit-Up Board Hitting Quantitative Analysis System)

## Data Source

- **Tushare Pro** is the sole data provider. All market data must come from Tushare APIs.
- Available APIs include but are not limited to: `limit_list_d`, `limit_step`, `limit_cpt_list`, `kpl_list`, `top_list`, `top_inst`, `moneyflow_ths`, `moneyflow_detail`, `daily_bar`, `index_daily`, `hsgt_top10`, `margin_detail`, `stk_factor_pro`, `cyq_perf`, `moneyflow_ind`, `concept_detail`, `ths_member`, `stk_mins`, `ths_hot`, `stk_surv`, `anns_d`
- **Active data APIs** (synced by orchestrator): `limit_list_d`, `limit_step`, `limit_cpt_list`, `kpl_list`, `top_list`, `top_inst`, `moneyflow_ths`, `moneyflow_detail`, `daily_bar`, `index_daily`, `ths_hot`, `hsgt_top10`
- `stk_factor_pro` is fetched on-demand per stock (not in bulk sync)
- Tushare token is stored in `.env` file
- Rate limit: 200 calls/minute (configurable)
- Supports 10-year historical data range for statistical models

## Architecture

```
CLI (Typer) -> Commands -> Analyzers -> Repositories -> SQLite
                            |
                       Signal Generator
                       ├── CompositeScorer (10-factor weighted scoring)
                       ├── RiskAssessor (dynamic thresholds via market context)
                       ├── EventClassifier (事件驱动分类)
                       ├── StockSentimentAnalyzer (8因子个股情绪)
                       ├── BoardSurvivalAnalyzer (连板生存率统计)
                       ├── TechnicalFormAnalyzer (技术形态分析)
                       └── HsgtTop10Repository (北向资金)
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
  - `stock_sentiment.py` - Per-stock sentiment scoring (8因子: 量比/封单/竞价/题材/催化/人气/北向/技术)
  - `market_context.py` - Market index regime analysis (MA5/MA20 + regime scoring)
  - `signal_validator.py` - T+1 signal validation and hit rate tracking
  - `predictor.py` - Buy/sell prediction engine
  - `board_survival.py` - 连板生存率统计 (10-year historical P(N+1|N))
  - `technical_form.py` - 技术形态评分 (MACD/KDJ/RSI/BOLL)
- `signals/` - Signal generation pipeline:
  - `composite_scorer.py` - 10-factor weighted scoring
  - `risk_assessor.py` - Dynamic risk thresholds based on market regime
  - `signal_generator.py` - Full signal generation with all factor integration
- `fetchers/` - Tushare data sync (sync_orchestrator + 14 fetchers)
  - Includes: `ths_hot_fetcher.py` (同花顺热股), `hsgt_fetcher.py` (北向资金), `stk_factor_fetcher.py` (技术因子)
- `repositories/` - SQLite data access layer (13 repositories)
  - Includes: `ths_hot_repo.py`, `hsgt_repo.py`, `stk_factor_repo.py`
- `models/` - Frozen dataclass models
  - Includes: `ths_hot_data.py`, `hsgt_data.py`, `stk_factor_data.py`
- `commands/` - CLI command handlers (13 commands including `event` and `backtest --detail`)
- `renderers/` - Rich terminal output (tables, dashboard, theme)

## CLI Commands

```
hit-astocker sync -d YYYYMMDD       # Sync all data (including ths_hot + hsgt_top10)
hit-astocker daily -d YYYYMMDD      # Full dashboard with market context + event analysis
hit-astocker sentiment -d YYYYMMDD  # Sentiment with 大盘联动 display
hit-astocker event -d YYYYMMDD      # Event classification + theme heat + stock sentiment
hit-astocker signal -d YYYYMMDD     # Trading signals (10-factor scoring)
hit-astocker backtest -s START -e END [--detail]  # Backtest with T+1 validation
hit-astocker firstboard / lianban / sector / dragon / flow / predict
```

## Scoring System

### Composite Score (10 factors, 0-100):
- 17% 市场情绪 (sentiment, index-adjusted)
- 16% 封板质量 (seal quality)
- 12% 板块归属 (sector)
- 10% 事件催化 (event catalyst)
- 10% 个股情绪 (stock sentiment, 8-factor enhanced)
- 8% 连板生存率 (lianban survival rate, 10-year stats)
- 7% 资金流向 (capital flow)
- 7% 龙虎榜 (dragon tiger)
- 7% 北向资金 (northbound capital)
- 6% 技术形态 (technical form: MACD/KDJ/RSI/BOLL)

### Stock Sentiment (8 sub-factors, 0-100):
- 15% 量比 (volume ratio)
- 15% 同花顺人气 (THS hot ranking)
- 14% 封单强度 (seal order)
- 13% 北向资金 (northbound signal)
- 12% 题材热度 (theme heat)
- 12% 技术形态 (technical form)
- 11% 事件催化 (event catalyst)
- 8% 竞价活跃度 (bid activity)

### Risk Assessment (Dynamic):
- Thresholds auto-adjust by market regime (STRONG_BULL → STRONG_BEAR)
- Index-based kill conditions (大盘暴跌 → NO_GO)
- 5 levels: LOW → FULL, MEDIUM → HALF, HIGH → QUARTER, EXTREME/NO_GO → ZERO

### Board Survival Model:
- Uses up to 10 years of historical limit_step data
- Computes P(height N+1 | height N) for each board height
- Replaces crude fixed lianban_position scoring with statistical probabilities

## Conventions

- Python 3.12+
- Use `pydantic-settings` for configuration
- All scoring on 0-100 scale
- Use `__slots__` for performance-critical data classes
- Immutable tuples for collections in model outputs
- Date format: `date` objects internally, `YYYYMMDD` strings for Tushare API
- Frozen dataclasses for all model outputs
