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
CLI (Typer) -> Commands -> Analyzers -> Repositories -> SQLite (WAL mode)
                            |               |
                       Signal Generator     Batch queries (no N+1)
                       ├── CompositeScorer (10-factor weighted scoring)
                       ├── RiskAssessor (dynamic thresholds via market context)
                       ├── EventClassifier (事件驱动分类)
                       ├── StockSentimentAnalyzer (8因子个股情绪)
                       ├── BoardSurvivalAnalyzer (连板生存率统计)
                       ├── TechnicalFormAnalyzer (技术形态分析)
                       └── HsgtTop10Repository (北向资金)
                            |
                    Rich Terminal Output

Concurrency model:
- SQLite in WAL mode + check_same_thread=False for concurrent reads
- SignalGenerator: Phase1 parallel (8 independent analyzers) → Phase2 parallel (2 dependent)
- SyncOrchestrator: parallel HTTP fetches (4 workers) → sequential DB writes
- daily_cmd: 6 analyzers parallel, then SignalGenerator sequential (avoid nested pools)
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
  - `signal_validator.py` - T+1 signal validation (legacy, simple close-vs-OHLC)
  - `backtest_engine.py` - Realistic board-hitting backtest (3 execution modes + stop/target)
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
  - Includes: `ths_hot_data.py`, `hsgt_data.py`, `stk_factor_data.py`, `backtest.py` (TradeResult/BacktestStats), `daily_context.py` (DataCoverage)
- `commands/` - CLI command handlers (13 commands including `event` and `backtest --detail`)
- `renderers/` - Rich terminal output (tables, dashboard, theme)

## CLI Commands

```
hit-astocker sync -d YYYYMMDD       # Sync all data (including ths_hot + hsgt_top10)
hit-astocker daily -d YYYYMMDD      # Full dashboard with market context + event analysis
hit-astocker sentiment -d YYYYMMDD  # Sentiment with 大盘联动 display
hit-astocker event -d YYYYMMDD      # Event classification + theme heat + stock sentiment
hit-astocker signal -d YYYYMMDD     # Trading signals (10-factor scoring)
hit-astocker backtest -s START -e END [-m MODE] [--stop-loss -7] [--take-profit 5] [--detail]
  # MODE: AUCTION (竞价买) / WEAK_TO_STRONG (弱转强) / RE_SEAL (回封买)
  # T信号 → T+1买入 → T+2卖出, 处理一字板/炸板止损/冲高兑现
hit-astocker firstboard / lianban / sector / dragon / flow / predict
```

## Scoring System

### Composite Score (10 factors, dynamic weights):
- Base weights: sentiment(12-17%), seal_quality(16-22%), sector(8-12%), event_catalyst(5-12%), stock_sentiment(7-12%), survival(6-22%), capital_flow(5-8%), dragon_tiger(5-10%), northbound(5-7%), technical_form(3-12%)
- Three models: FIRST_BOARD / FOLLOW_BOARD / SECTOR_LEADER, each with distinct weight profiles
- **Dynamic weight redistribution**: factors backed by empty tables (not synced) are excluded; their weight is redistributed proportionally to factors with real data
- `DataCoverage` tracks: has_ths_hot, has_hsgt, has_stk_factor, has_hm
- Commands display "⚠ 数据缺失" warning when factors are excluded

### Stock Sentiment (up to 8 sub-factors, dynamic weights):
- Core 5 (always available): volume_ratio(15%), seal_order(14%), bid_activity(8%), theme_heat(12%), event_catalyst(11%)
- Optional 3 (require synced tables): popularity/ths_hot(15%), northbound/hsgt(13%), technical_form/stk_factor(12%)
- When optional tables are empty, core weights are renormalized to sum=1

### Risk Assessment (Dynamic):
- Thresholds auto-adjust by market regime (STRONG_BULL → STRONG_BEAR)
- Index-based kill conditions (大盘暴跌 → NO_GO)
- 5 levels: LOW → FULL, MEDIUM → HALF, HIGH → QUARTER, EXTREME/NO_GO → ZERO

### Board Survival Model:
- Uses up to 10 years of historical limit_step data
- Computes P(height N+1 | height N) for each board height
- Replaces crude fixed lianban_position scoring with statistical probabilities

## Performance Constraints

- **No N+1 queries**: Always use batch methods (`find_recent_bars_batch`, `find_recent_batch`, `find_by_codes`, `get_themes_by_dates`) when loading data for multiple stocks
- **Composite indexes**: `(ts_code, trade_date DESC)` on `daily_bar`, `stk_factor_pro`, `hsgt_top10`; `(trade_date, tag)` on `kpl_list`; `(ts_code, trade_date)` on `limit_step`, `moneyflow_ths`
- **Thread safety**: All analyzer queries must be read-only (no DDL, no temp tables). Use CTE/window functions instead. `BoardSurvivalAnalyzer` uses CTE + LEAD() window function for consecutive date pairing
- **Parallel analyzers**: Independent analyzers run in ThreadPoolExecutor. Never nest ThreadPoolExecutor inside another pool on the same SQLite connection
- **Sync parallelism**: API HTTP fetches are parallelized (4 workers); DB writes are sequential (SQLite single-writer)
- **ROW_NUMBER batch queries**: Always enumerate columns explicitly in the outer SELECT to exclude the `rn` column

## Conventions

- Python 3.12+
- Use `pydantic-settings` for configuration
- All scoring on 0-100 scale
- Use `__slots__` for performance-critical data classes
- Immutable tuples for collections in model outputs
- Date format: `date` objects internally, `YYYYMMDD` strings for Tushare API
- Frozen dataclasses for all model outputs
- 所有交流使用中文
- 写完代码后主动提交并推送到 GitHub
