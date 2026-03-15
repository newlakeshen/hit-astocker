# Hit-Astocker

A股打板量化分析系统 (A-Share Limit-Up Board Hitting Quantitative Analysis System)

## Data Source

- **Tushare Pro** is the sole data provider. All market data must come from Tushare APIs.
- Available APIs include but are not limited to: `limit_list_d`, `limit_step`, `limit_cpt_list`, `kpl_list`, `top_list`, `top_inst`, `moneyflow_ths`, `moneyflow_detail`, `daily_bar`, `index_daily`, `hsgt_top10`, `margin_detail`, `stk_factor_pro`, `cyq_perf`, `moneyflow_ind`, `concept_detail`, `ths_member`, `stk_mins`, `ths_hot`, `stk_surv`, `anns_d`
- **Active data APIs** (synced by orchestrator): `limit_list_d`, `limit_step`, `limit_cpt_list`, `kpl_list`, `top_list`, `top_inst`, `moneyflow_ths`, `moneyflow_detail`, `daily_bar`, `index_daily`, `ths_hot`, `hsgt_top10`
- `stk_factor_pro` is fetched on-demand per stock (not in bulk sync)
- `anns_d` supports date range queries (`start_date/end_date`) for batch sync
- Tushare token is stored in `.env` file
- Rate limit: 200 calls/minute (configurable)
- Supports 6-year historical data range for statistical models

## Architecture

```
CLI (Typer) -> Commands -> Analyzers -> Repositories -> SQLite (WAL mode)
                            |               |
                       Signal Generator (Two-Stage Pipeline)
                       │
                       ├── Stage 1: Hard Filter (stage1_filter.py)
                       │   └── ST/BJ排除, 大盘暴跌, 周期门控, 质量硬伤, 赚钱效应分层门控
                       │
                       ├── Stage 2: Cross-Sectional Ranking
                       │   ├── ML Model (ranking_model.py) — logistic/GBDT
                       │   └── Rule-based fallback (composite_scorer.py)
                       │
                       ├── CompositeScorer (10-factor weighted scoring)
                       ├── ProfitEffectAnalyzer (赚钱效应分层: 首板/2板/3板/空间板 × 10cm/20cm)
                       ├── RiskAssessor (cycle-aware gating + market regime + profit regime)
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
- SQLite in WAL mode; single connection per command (no check_same_thread)
- SignalGenerator: Stage1 filter → Stage2 rank (ML or rules) → risk assess
- SyncOrchestrator: parallel HTTP fetches (4 workers) → sequential DB writes → failed chunks auto-retry (max 2 rounds)
- daily_cmd / signal_cmd: sequential analyzers (single SQLite connection, not thread-safe)
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
  - `backtest_engine.py` - Realistic board-hitting backtest (3 execution modes + dynamic stop/target + T+3 持仓 + 历史收益率指标)
  - `backtest_diagnosis.py` - 6-dimensional backtest diagnosis (切片分析亏损来源)
  - `predictor.py` - Buy/sell prediction engine
  - `board_survival.py` - 连板生存率统计 (6-year historical P(N+1|N))
  - `technical_form.py` - 技术形态评分 (MACD/KDJ/RSI/BOLL)
  - `profit_effect.py` - 赚钱效应分层 (首板/2板/3板/空间板 × 10cm/20cm → STRONG/NORMAL/WEAK/FROZEN)
- `signals/` - Two-stage signal generation pipeline:
  - `stage1_filter.py` - Hard filter (ST排除/大盘暴跌/周期门控/质量硬伤/赚钱效应门控/10cm-20cm分层)
  - `filters.py` - Candidate pre-filter (ST/BJ/市值排除)
  - `feature_builder.py` - 19-dim feature vector extraction (13 factor + 6 context)
  - `ranking_model.py` - ML ranking model (logistic/GBDT, sklearn)
  - `composite_scorer.py` - 10-factor weighted scoring (rule-based, default path)
  - `risk_assessor.py` - Cycle-aware risk gating + market regime thresholds + DIVERGE白名单
  - `signal_generator.py` - Two-stage pipeline orchestrator + 核心因子直通 + TopK分差放行
- `fetchers/` - Tushare data sync (sync_orchestrator + 21 fetchers)
  - Includes: `ths_hot_fetcher.py`, `hsgt_fetcher.py`, `stk_factor_fetcher.py`, `trade_cal_fetcher.py`, `hm_fetcher.py`, `ann_fetcher.py`, `concept_fetcher.py`, `ths_member_fetcher.py`
- `repositories/` - SQLite data access layer (17 repositories + base)
  - Includes: `ths_hot_repo.py`, `hsgt_repo.py`, `stk_factor_repo.py`, `hm_repo.py`, `ann_repo.py`, `concept_repo.py`, `auction_repo.py`
- `models/` - Frozen dataclass models (27 model files)
  - Includes: `backtest.py` (TradeResult/BacktestStats/EquityPoint), `daily_context.py` (DataCoverage/DailyContextCaches), `sentiment_cycle.py` (CyclePhase/SentimentCycle), `event_data.py` (PolicyLevel/OrderAmountLevel), `profit_effect.py` (ProfitRegime/ProfitEffectSnapshot)
- `commands/` - CLI command handlers (15 commands including `train`, `backtest-diag`)
- `database/` - SQLite connection management, schema migrations
- `utils/` - Shared utilities:
  - `trade_calendar.py` - TradeCalendar singleton (bisect O(log n) 交易日查找)
  - `date_utils.py` - Date helper functions (委托给 TradeCalendar)
  - `stock_filter.py` - ST/BJ/退市风险警示 stock exclusion
- `llm/` - LLM integration (optional, `pip install 'hit-astocker[llm]'`):
  - `client.py` / `cache.py` - OpenAI API client with response caching
  - `event_enhancer.py` / `narrative_gen.py` - AI-powered event narrative generation
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
  # T信号 → T+1买入 → T+2卖出, 动态止损止盈(首板紧/龙头宽), 历史收益率指标(Sharpe/回撤/CAGR)
hit-astocker backtest-diag -s START -e END  # 6维切片诊断亏损来源 (周期/类型/评分/风险/出场/板块)
hit-astocker firstboard / lianban / sector / dragon / flow / predict
```

## Development Setup

```bash
pip install -e '.[dev,ml]'           # Install with dev + ML dependencies
pip install -e '.[dev,ml,llm]'       # Include LLM integration (OpenAI)
ruff check src/                      # Lint
ruff format src/                     # Format
pytest                               # Run tests with coverage (no --timeout flag, pytest-timeout not installed)
```

## Two-Stage Signal Pipeline

### Stage 1: Hard Filter (`stage1_filter.py`)
Removes candidates that should never be traded:
- ST / BJ / 退市风险警示 (制度性排除, 含"退"字检测)
- 大盘暴跌 (上证 ≤ -3% 或 创业板 ≤ -4%)
- 情绪极度低迷 (overall_score < 25)
- 退潮期: 龙头/连板 score<70 回避, 首板 score<75 回避
- 冰点期: score < 50 回避
- 首板封板质量极差 (seal_quality < 25)
- 连板生存率极低 (高度→门槛查表: 2板≥30/3板≥25/4板≥30/5板+≥35)
- 赚钱效应门控: 按 10cm/20cm 分层查询, 样本不足时 fallback 到总体层

### Stage 2: Cross-Sectional Ranking
**ML Model** (优先, 需先运行 `train` 命令):
- 19维特征向量: 13个因子分 + 6个上下文特征 (周期/类型/数据可用性)
- logistic regression (可解释, 默认) 或 GBDT (捕获非线性交互)
- 训练数据: 历史因子向量 + T+1收益标签 (盈利=1/亏损=0)
- TimeSeriesSplit 时序交叉验证 + AUC评估 (Pipeline包裹StandardScaler防止数据泄漏)
- predict_proba → 概率 × 100 = 综合评分 (0-100)
- 加载时校验 feature_columns 与当前代码一致, 不匹配则拒绝加载
- 缺失因子用 50.0 (中性值) 而非 0.0, 避免与"极差"混淆

**Rule-based (default path, ML disabled by default via `Settings.use_ml_model`)**:
- 10-factor weighted scoring (composite_scorer.py)
- Cycle-aware weight adjustment
- Dynamic weight redistribution for missing data
- 核心因子直通通道: 综合分略低但核心因子极强的票放行 (min_score-10 保底)

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
- **SECTOR_LEADER 优先级**: FOLLOW_BOARD 跳过 sl_codes (龙一), 确保龙一被评为 SECTOR_LEADER 而非 FOLLOW_BOARD
- **SECTOR_LEADER 独立因子**: theme_heat 和 event_catalyst 各有独立权重, 不再用 max 覆盖 (避免双重计分)
- **Dynamic weight redistribution**: factors backed by empty tables (not synced) are excluded; their weight is redistributed proportionally to factors with real data
- `DataCoverage` tracks: has_ths_hot, has_hsgt, has_stk_factor, has_hm
- Commands display "⚠ 数据缺失" warning when factors are excluded

### Stock Sentiment (up to 8 sub-factors, dynamic weights):
- Core 5 (always available): volume_ratio(15%), seal_order(14%), bid_activity(8%), theme_heat(12%), event_catalyst(11%)
- Optional 3 (require synced tables): popularity/ths_hot(15%), northbound/hsgt(13%), technical_form/stk_factor(12%)
- When optional tables are empty, core weights are renormalized to sum=1

### Sentiment Cycle (6-phase):
- ICE (冰点) → REPAIR (修复) → FERMENT (发酵) → CLIMAX (高潮) → DIVERGE (分歧) → RETREAT (退潮)
- Computed from 5-day light_score trajectory (3因子一致量纲): MA3/MA5, delta (一阶导), acceleration (二阶导)
- Gating in RiskAssessor: RETREAT→NO_GO, ICE→only SECTOR_LEADER 80+, DIVERGE→no FIRST_BOARD
- Weight adjustment in CompositeScorer: ICE/RETREAT reduce technical_form/capital_flow, boost seal_quality/survival

### Risk Assessment (Cycle + Regime):
- Thresholds auto-adjust by market regime (STRONG_BULL → STRONG_BEAR)
- **Cycle gating**: emotion phase overrides risk (DIVERGE: FIRST_BOARD白名单式放行(sq≥60或ec≥60), RETREAT: 龙头/连板65+/首板70+→HIGH, ICE: 60+→HIGH, REPAIR初期: 65+→MEDIUM)
- **CLIMAX末期**: 要求 delta<-1 OR (delta<0 AND accel<-3), 避免上升减速误判
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
- FIRST_BOARD: 紧止损(-5%), 止盈+7% (弱转强失败快速回落)
- FOLLOW_BOARD: 标准止损, 宽止盈+10% (连板有惯性)
- SECTOR_LEADER: 标准止损, 最宽止盈+12% (龙头溢价最高)
- 默认止盈 8%, 溢价上限 9%
- 同 K 线止损+止盈均触发时取止损 (保守假设, 日内无法确定先后顺序)
- 市场 regime 调整: STRONG_BULL(-0.5%止损/+2%止盈), BEAR(+1.5%/-1%), STRONG_BEAR(+2%/-2%)
- **YIZI_HELD 成本修正**: 一字跌停无法卖出时不扣出场滑点/卖出佣金/印花税 (仅保留买入成本)
- Disabled via --no-dynamic-stops

### Per-Type Holding Days:
- FIRST_BOARD: T+1买 T+2卖 (默认1天)
- FOLLOW_BOARD: 同上
- SECTOR_LEADER: FERMENT/CLIMAX 周期可延长到 T+3 (hold_days=2)
- T+2 触发止损→立即出 (protection first); T+2 CLOSE→继续持有到 T+3

### Historical Return Metrics (历史收益率):
- **权益曲线**: 按 exit_date 复利计算, 月末快照降采样
- **年化收益率 (CAGR)**: (final_equity/100)^(252/N_days) - 1
- **Sharpe/Sortino** (rf=0, 均用N-1样本方差): 日收益率序列 (含无交易日=0) 年化
- **最大回撤**: peak-to-trough 幅度 + 起止日期
- **Calmar 比率**: CAGR / |max_drawdown| (保留正负号)
- **月度/年度收益表**: 按 exit_date 分月/年的 BucketStats
- EquityPoint: (trade_date, equity, daily_return, drawdown)

### Board Survival Model:
- Uses up to 6 years of historical limit_step data
- Computes P(height N+1 | height N) for each board height
- Replaces crude fixed lianban_position scoring with statistical probabilities

### Profit Effect Stratification (赚钱效应分层):
- **维度**: 首板/2板/3板/空间板 × 10cm(主板)/20cm(创科)
- **指标**: 次日溢价、次日收益、次日胜率、炸板率、非一字率(可参与度)
- **Regime**: STRONG(≥65) / NORMAL(≥45) / WEAK(≥25) / FROZEN(<25)
- **集成**: Stage1 FROZEN→kill / WEAK→过滤; RiskAssessor regime overlay; Dashboard 分层表

## Performance Constraints

- **No N+1 queries**: Always use batch methods (`find_recent_bars_batch`, `find_recent_batch`, `find_by_codes`, `get_themes_by_dates`) when loading data for multiple stocks
- **Composite indexes**: `(ts_code, trade_date DESC)` on `daily_bar`, `stk_factor_pro`, `hsgt_top10`; `(trade_date, tag)` on `kpl_list`; `(ts_code, trade_date)` on `limit_step`, `moneyflow_ths`
- **Thread safety**: All analyzer queries must be read-only (no DDL, no temp tables). Use CTE/window functions instead. `BoardSurvivalAnalyzer` uses CTE + LEAD() window function for consecutive date pairing
- **Sequential analyzers**: daily_cmd / signal_cmd run analyzers sequentially (single SQLite connection, not thread-safe). Only SyncOrchestrator uses ThreadPoolExecutor (for HTTP fetches, 4 workers); DB writes are sequential (SQLite single-writer)
- **ROW_NUMBER batch queries**: Always enumerate columns explicitly in the outer SELECT to exclude the `rn` column
- **Repo bulk preloading** (training/backtest): `LimitListRepository`, `LimitStepRepository`, `KplRepository` support `preload_range(start, end)` — one bulk SQL loads all records into memory, subsequent per-date queries use dict lookups instead of SQL. All derived methods (count_by_type, find_first_board_stocks, etc.) check `_records_cache` before hitting DB
- **Shared repo instances**: `DailyContextCaches` holds shared pre-loaded repos (`limit_repo`, `step_repo`, `kpl_repo`, `hm_repo`). Analyzers accept optional repo params (e.g., `limit_repo=None`) — when provided, skip creating new repo instances. This ensures preloaded data is shared across all analyzers in the same `build_daily_context` call
- **HmRepository profiles cache**: `compute_trader_profiles()` SQL limits daily_bar scan to `relevant_codes` CTE (not full table). Profiles are cached and reused within 30-day windows (98% data overlap between adjacent days)
- **SentimentCycleDetector light_metrics cache**: `light_metrics_cache: dict[date, _DayMetrics]` in `DailyContextCaches` eliminates 75% redundant lookback queries across consecutive days
- **EventClassifier concept_members cache**: `concept_members_cache: dict[str, list[str]]` in `DailyContextCaches` eliminates N+1 concept membership queries (structural data, rarely changes)
- **DataCoverage per-day**: `DailyContextCaches.coverage_cache` uses `table_has_data_for_date_batch()` to batch-query per-day coverage (5 SQL queries for entire range, uses `WHERE IN` for precise date filtering). Replaces old table-level `global_coverage` which incorrectly marked tables as available when only 2/1498 days had data
- **NaN handling**: `_safe_float_nullable()` preserves NULL for `fd_amount`, `turnover_ratio`, `float_mv`, `total_mv` in limit_list_d (DB stores NULL, repo layer `or 0.0` fallback). Other fields use `_safe_float()` (NaN→0.0)
- **Sync retry**: `sync_date_range_bulk()` auto-retries failed batch chunks up to 2 rounds with exponential backoff. `stk_factor_pro` per-stock failures are logged (not silent)

## Conventions

- Python 3.11+ (pyproject.toml: `>=3.11`)
- Use `pydantic-settings` for configuration
- All scoring on 0-100 scale
- Use `__slots__` for performance-critical data classes
- Immutable tuples for collections in model outputs
- Date format: `date` objects internally, `YYYYMMDD` strings for Tushare API
- Frozen dataclasses for all model outputs
- `out_date` fields: always store as NULL (not empty string) to represent "未退出"
- `_safe_float` / `_safe_float_nullable` / `_safe_int` in `limit_fetcher.py` are shared across all 14+ fetchers — add new variants, never change existing signatures
- Optional dependencies: `[ml]` (scikit-learn), `[llm]` (openai), `[dev]` (pytest, ruff)
- Linter/formatter: `ruff` (line-length=100, target py311)
- **所有对话和交流必须使用中文**（包括解释、分析、建议、提问等，commit message 可中英混合）
- 写完代码后主动提交并推送到 GitHub
- **每次提交前必须更新 CLAUDE.md**: 结合当前 session 的改动，准确更新 CLAUDE.md 中的架构、模块、性能约束等相关章节，确保文档与代码保持同步
- **每次提交前必须进行代码审查**: 使用 `requesting-code-review` skill 审查本次提交的代码变更（忽略测试类、文档等文件，仅审查业务代码），发现问题立即修复后再提交
