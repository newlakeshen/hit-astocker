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
                       Signal Generator (Two-Stage Pipeline)
                       │
                       ├── Stage 1: Hard Filter (stage1_filter.py)
                       │   └── ST/BJ排除, 大盘暴跌, 周期门控, 质量硬伤
                       │
                       ├── Stage 2: Cross-Sectional Ranking
                       │   ├── ML Model (ranking_model.py) — logistic/GBDT
                       │   └── Rule-based fallback (composite_scorer.py)
                       │
                       ├── CompositeScorer (10-factor weighted scoring)
                       ├── RiskAssessor (cycle-aware gating + market regime)
                       ├── FeatureBuilder (19-dim feature vectors)
                       ├── SentimentCycleDetector (6-phase emotion cycle)
                       ├── EventClassifier (3-layer + 政策级别 + 金额级别)
                       ├── StockSentimentAnalyzer (8因子个股情绪)
                       ├── BoardSurvivalAnalyzer (连板生存率统计)
                       ├── TechnicalFormAnalyzer (技术形态分析)
                       └── HsgtTop10Repository (北向资金)
                            |
                    Rich Terminal Output

Concurrency model:
- SQLite in WAL mode + check_same_thread=False for concurrent reads
- SignalGenerator: Stage1 filter → Stage2 rank (ML or rules) → risk assess
- SyncOrchestrator: parallel HTTP fetches (4 workers) → sequential DB writes
- daily_cmd: 6 analyzers parallel, then SignalGenerator sequential (avoid nested pools)
```

## Key Modules

- `analyzers/` - Strategy engines:
  - `sentiment.py` - Market sentiment with index adjustment (大盘联动)
  - `sentiment_cycle.py` - 6-phase emotion cycle detector (ICE→REPAIR→FERMENT→CLIMAX→DIVERGE→RETREAT)
  - `firstboard.py` - First-board scoring (封板时间/强度/纯度/换手/板块)
  - `lianban.py` - Consecutive board ladder (连板天梯)
  - `sector_rotation.py` - Sector rotation tracking
  - `dragon_tiger.py` - Dragon-tiger board analysis
  - `moneyflow.py` / `flow_factors.py` - Money flow (7 sub-factors)
  - `event_classifier.py` - Event-driven classification (3-layer + 政策级别 + 金额级别 + 交易日衰减)
  - `stock_sentiment.py` - Per-stock sentiment scoring (8因子: 量比/封单/竞价/题材/催化/人气/北向/技术)
  - `market_context.py` - Market index regime analysis (MA5/MA20 + regime scoring)
  - `signal_validator.py` - T+1 signal validation (legacy, simple close-vs-OHLC)
  - `backtest_engine.py` - Realistic board-hitting backtest (3 execution modes + dynamic stop/target)
  - `predictor.py` - Buy/sell prediction engine
  - `board_survival.py` - 连板生存率统计 (10-year historical P(N+1|N))
  - `technical_form.py` - 技术形态评分 (MACD/KDJ/RSI/BOLL)
- `signals/` - Two-stage signal generation pipeline:
  - `stage1_filter.py` - Hard filter (ST排除/大盘暴跌/周期门控/质量硬伤)
  - `feature_builder.py` - 19-dim feature vector extraction (13 factor + 6 context)
  - `ranking_model.py` - ML ranking model (logistic/GBDT, sklearn)
  - `composite_scorer.py` - 10-factor weighted scoring (rule-based fallback)
  - `risk_assessor.py` - Cycle-aware risk gating + market regime thresholds
  - `signal_generator.py` - Two-stage pipeline orchestrator
- `fetchers/` - Tushare data sync (sync_orchestrator + 14 fetchers)
  - Includes: `ths_hot_fetcher.py` (同花顺热股), `hsgt_fetcher.py` (北向资金), `stk_factor_fetcher.py` (技术因子)
- `repositories/` - SQLite data access layer (13 repositories)
  - Includes: `ths_hot_repo.py`, `hsgt_repo.py`, `stk_factor_repo.py`
- `models/` - Frozen dataclass models
  - Includes: `ths_hot_data.py`, `hsgt_data.py`, `stk_factor_data.py`, `backtest.py` (TradeResult/BacktestStats + dynamic stops), `daily_context.py` (DataCoverage), `sentiment_cycle.py` (CyclePhase/SentimentCycle), `event_data.py` (PolicyLevel/OrderAmountLevel)
- `commands/` - CLI command handlers (14 commands including `train`)
- `renderers/` - Rich terminal output (tables, dashboard, theme)

## CLI Commands

```
hit-astocker sync -d YYYYMMDD       # Sync all data (including ths_hot + hsgt_top10)
hit-astocker daily -d YYYYMMDD      # Full dashboard with market context + event analysis
hit-astocker sentiment -d YYYYMMDD  # Sentiment with 大盘联动 display
hit-astocker event -d YYYYMMDD      # Event classification + theme heat + stock sentiment
hit-astocker signal -d YYYYMMDD     # Trading signals (two-stage: filter + ML/rule rank)
hit-astocker train -s START -e END [-m logistic|gbdt] [--min-samples 200]
  # Train ML ranking model from historical data
  # Collects (factor vectors, T+1 return labels) → train → save model
  # Next signal/backtest run auto-loads trained model
hit-astocker backtest -s START -e END [-m MODE] [--stop-loss -7] [--take-profit 5] [--no-dynamic-stops] [--detail]
  # MODE: AUCTION (竞价买) / WEAK_TO_STRONG (弱转强) / RE_SEAL (回封买)
  # T信号 → T+1买入 → T+2卖出, 动态止损止盈(首板紧/龙头宽)
hit-astocker firstboard / lianban / sector / dragon / flow / predict
```

## Two-Stage Signal Pipeline

### Stage 1: Hard Filter (`stage1_filter.py`)
Removes candidates that should never be traded:
- ST / BJ / 风险警示 (制度性排除)
- 大盘暴跌 (上证 ≤ -3% 或 创业板 ≤ -4%)
- 情绪极度低迷 (overall_score < 25)
- 退潮期: 除绝对龙头(score≥85)外全部回避
- 冰点期: score < 75 回避
- 首板封板质量极差 (seal_quality < 25)
- 连板生存率极低 (survival < 15)

### Stage 2: Cross-Sectional Ranking
**ML Model** (优先, 需先运行 `train` 命令):
- 19维特征向量: 13个因子分 + 6个上下文特征 (周期/类型/数据可用性)
- logistic regression (可解释, 默认) 或 GBDT (捕获非线性交互)
- 训练数据: 历史因子向量 + T+1收益标签 (盈利=1/亏损=0)
- 5折交叉验证 + AUC评估
- predict_proba → 概率 × 100 = 综合评分 (0-100)

**Rule-based fallback** (无模型时):
- 10-factor weighted scoring (current composite_scorer.py)
- Cycle-aware weight adjustment
- Dynamic weight redistribution for missing data

### Feature Vector (19 dimensions):
```
Factor features (13): sentiment, sector, capital_flow, dragon_tiger,
  event_catalyst, stock_sentiment, northbound, technical_form,
  seal_quality, survival, height_momentum, theme_heat, leader_position
Context features (6): cycle_phase (ordinal 0-5),
  sig_first_board, sig_follow_board, sig_sector_leader (one-hot),
  has_northbound_data, has_technical_data
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

### Sentiment Cycle (6-phase):
- ICE (冰点) → REPAIR (修复) → FERMENT (发酵) → CLIMAX (高潮) → DIVERGE (分歧) → RETREAT (退潮)
- Computed from 5-day score trajectory: MA3/MA5, delta (一阶导), acceleration (二阶导)
- Gating in RiskAssessor: RETREAT→NO_GO, ICE→only SECTOR_LEADER 80+, DIVERGE→no FIRST_BOARD
- Weight adjustment in CompositeScorer: ICE/RETREAT reduce technical_form/capital_flow, boost seal_quality/survival

### Risk Assessment (Cycle + Regime):
- Thresholds auto-adjust by market regime (STRONG_BULL → STRONG_BEAR)
- **Cycle gating**: emotion phase overrides risk for signal types (e.g., DIVERGE blocks FIRST_BOARD)
- Index-based kill conditions (大盘暴跌 → NO_GO)
- 5 levels: LOW → FULL, MEDIUM → HALF, HIGH → QUARTER, EXTREME/NO_GO → ZERO

### Event Classification (3-layer + 强度建模):
- L1 公告触发 (anns_d): 交易日衰减 + 政策级别 + 订单金额级别
- L2 题材主线 (concept_detail): 概念归属 + 政策级别检测
- L3 关键词+扩散 (lu_desc/theme): keyword + 金额解析
- **政策级别**: 国家级(S) / 部委级(A) / 行业级(B) / 地方级(C) → 半衰期×2/1.5/1/0.7
- **金额级别**: ≥10亿(S) / ≥1亿(A) / ≥5000万(B) / <5000万(C) → 覆盖关键词级别
- **交易日衰减**: `count_trading_days_between()` 替代 calendar days

### Event Lifecycle + Crowding:
- Theme lifecycle: NEW → HEATING → PEAK → FADING (from 3-day count trajectory)
- Crowding ratio: limit_up_count / concept_members_total
- Crowding penalty: >60% → -25pts, >50% → -18pts, >40% → -10pts (from heat_score)

### Dynamic Stops (per signal type):
- FIRST_BOARD: 紧止损(-5%), 标准止盈 (弱转强失败快速回落)
- FOLLOW_BOARD: 标准止损, 宽止盈(+8%) (连板有惯性)
- SECTOR_LEADER: 标准止损, 最宽止盈(+10%) (龙头溢价最高)
- Disabled via --no-dynamic-stops

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
- scikit-learn as optional dependency (`pip install 'hit-astocker[ml]'`)
- 所有交流使用中文
- 写完代码后主动提交并推送到 GitHub
