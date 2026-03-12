# A股打板策略全面优化设计

> 日期: 2026-03-12
> 目标: 6年回测（2020-2026）从 -241% 扭正
> 聚焦: 情绪面 + 事件面 + 量化分析策略

## 背景

### 当前系统状态
- 两阶段信号管线: Stage1 硬过滤 → Stage2 ML/规则排名 → 风控 → 组合约束
- 6相情绪周期 + 3层事件分类 + 11因子复合评分（含 auction_quality） + 赚钱效应分层
- ML 特征向量: 21维（14因子 + 7上下文，含 auction_quality 和 has_auction_data）
- 6年回测: -241%（从 -368% 改善 34%，仍大幅亏损）

### 诊断出的四个核心问题

1. **信号太多，不够精** — top_k=5，日均 2-3 信号，6年累计 3000-4500 笔交易，打板应"少做精做"
2. **情绪择时门槛太宽** — CLIMAX 末期几乎无限制，DIVERGE 只挡首板
3. **核心因子回测中大面积缺失** — limit_step 2周、stk_factor_pro 2天、anns_d 空表，回测模型与实盘模型是两个不同的东西
4. **出场逻辑对市况不敏感** — 固定止损止盈，牛熊通用

### 数据覆盖诊断

| 数据层级 | 数据源 | 覆盖 |
|---------|--------|------|
| 核心（6年） | limit_list_d, kpl_list, daily_bar, index_daily, moneyflow_ths/detail, hsgt_top10 | 完整 |
| 短期（2周） | limit_step, top_list, top_inst | 严重不足 |
| 极短（2天） | ths_hot, stk_factor_pro, hm_detail, stk_auction | 几乎无 |
| 空表 | anns_d, ths_member | 无数据 |
| 未接入 | margin_detail, cyq_perf, moneyflow_ind, ths_daily | 未使用 |

---

## 优化方案: 四阶段混合路径

```
Phase 1: 回测解剖 → 找到亏损出血点
Phase 2: 策略减法 + 情绪面增强 → 用现有+新数据提高信号质量
Phase 3: 数据补齐 → 消除回测与实盘的因子差异
Phase 4: 因子优化 → 基于 Phase 1 发现的问题针对性增强
```

---

## Phase 1: 回测解剖

### 目标
搞清楚 -241% 的亏损来源分布，为 Phase 2 减法策略提供数据依据。

### 新增模块: `analyzers/backtest_diagnosis.py`

对 `BacktestEngine` 输出的 `list[TradeResult]` 做多维分解，不改动现有回测逻辑。

### 6个分解维度

| 维度 | 切片方式 | 目的 |
|------|----------|------|
| 按年份 | 2020/2021/.../2026 | 均匀亏损 vs 某几年集中大亏 |
| 按情绪周期 | ICE/REPAIR/FERMENT/CLIMAX/DIVERGE/RETREAT | 哪个阶段亏最多 |
| 按信号类型 | FIRST_BOARD/FOLLOW_BOARD/SECTOR_LEADER | 哪种信号贡献最大亏损 |
| 按出场原因 | STOP_LOSS/TAKE_PROFIT/CLOSE/YIZI_HELD | 止损多还是收盘卖亏 |
| 按评分区间 | <50/50-60/60-70/70-80/80+ | 高分信号是否真的更好 |
| 按赚钱效应 | STRONG/NORMAL/WEAK/FROZEN | 不同 regime 下的表现差异 |

### 每个切片输出指标
- 交易笔数、胜率、平均盈亏、最大单笔亏损
- 盈亏比（avg_win / avg_loss）
- 累计收益贡献（该切片占总亏损的百分比）

### 数据需求
`TradeResult` 新增 2 个可选字段: `cycle_phase: CyclePhase | None` 和 `profit_regime: ProfitRegime | None`，在 `BacktestEngine.simulate_day()` 中填充，避免诊断时重复计算。

### 新增 CLI
```bash
hit-astocker backtest-diag -s 20200311 -e 20260310
```
输出 Rich 表格，每个维度一张表，标红亏损贡献 >20% 的切片。

---

## Phase 2: 策略减法 + 情绪面增强

### 2.1 情绪择时严格化

修改 `signals/risk_assessor.py` 的 `_cycle_gate()`:

| 周期阶段 | 当前规则 | 优化后规则 |
|----------|---------|-----------|
| CLIMAX 末期 | 无特殊限制 | `score_accel < -3` → 所有类型 min_score +10 |
| DIVERGE | 仅挡 FIRST_BOARD | FIRST_BOARD → NO_GO; FOLLOW_BOARD → min_score 75; SECTOR_LEADER → min_score 80 |
| CLIMAX→DIVERGE 转折日 | 无概念 | `is_turning_point=True` 且从 CLIMAX 转入 → 当日 NO_GO |
| ICE→REPAIR 初期 | REPAIR 仅提高门槛 | REPAIR 前 2 天: 仅允许 SECTOR_LEADER 80+ |

### 2.2 信号数量硬控制

修改 `signals/signal_generator.py`:

| 参数 | 当前值 | 优化值 |
|------|--------|--------|
| `signal_top_k` | 5 | **2** |
| `signal_min_score` | 55 | **65** |
| `signal_max_per_theme` | 2 | **1** |

新增动态限额机制:

| 条件 | top_k |
|------|-------|
| 赚钱效应 STRONG + 周期 FERMENT/CLIMAX初(score_delta≥0) | 2（满额） |
| 赚钱效应 NORMAL + 周期 FERMENT | 2 |
| 赚钱效应 NORMAL + 其他周期 | 1 |
| 赚钱效应 WEAK | 1 且 min_score +5 |
| 赚钱效应 FROZEN | 0（Stage1 已拦截） |

### 2.3 出场策略市场自适应

修改 `analyzers/backtest_engine.py` 的 `BacktestConfig.effective_stops()`:

| 市场状态 | 止损调整 | 止盈调整 |
|---------|---------|---------|
| STRONG_BULL | 收紧 1% | 放宽 2% |
| BULL | 标准 | 标准 |
| BEAR | 收紧 1.5% | 收紧 1% |
| STRONG_BEAR | 收紧 2% | 收紧 2% |

`effective_stops(signal_type, market_regime)` 增加 `market_regime` 参数。

**传入路径**: `BacktestEngine.simulate_day()` 新增可选参数 `market_regime: str | None = None`，由 `DailyAnalysisContext.market_context` 获取。`BacktestConfig` 保持 frozen，新增 `effective_stops_with_regime(signal_type, market_regime)` 方法保持向后兼容，原 `effective_stops()` 默认 regime=BULL。

### 2.4 Stage1 过滤加严

修改 `signals/stage1_filter.py`:

| 过滤条件 | 当前阈值 | 优化阈值 | 原因 |
|---------|---------|---------|------|
| 首板封板质量 | < 35 | **< 45** | 差封板次日大面概率高 |
| 连板生存率基础门槛 | < 20 | **< 30** | 低生存率 = 接最后一棒 |
| 连板生存率递增门槛 | 3板≥25/4板≥35/5板≥45 | **3板≥35/4板≥45/5板≥55** | 与基础门槛联动上调 |
| 题材生命周期 FADING | 无过滤 | **过滤** | 退潮题材补涨 = 接盘 |
| 换手率异常 | 无检查 | **> 25% 过滤** | 超高换手多为出货 |
| 炸板后回封 | 无特殊 | **open_times ≥ 3 且非龙头过滤** | 反复开板分歧大 |

### 2.5 赚钱效应分层级门控

修改 `signals/stage1_filter.py` + `signals/risk_assessor.py`:

```
首板信号: 首板tier avg_premium < -2% 且 win_rate < 35% → 过滤
连板信号: 对应高度 win_rate < 25% → 过滤
龙头信号: 空间板 broken_rate > 60% → 过滤
```

### 2.6 新增 Tushare 数据源情绪增强

#### 2.6.1 融资融券情绪 (`margin_detail`)

**市场级 — SentimentAnalyzer 第 10 因子 `margin_momentum`**:
- 融资余额 5 日变化率（MA5 slope）
- 评分曲线（非线性，防止过热误判）:
  - 温和增长（slope 0-2%）→ 75-90分（健康加杠杆）
  - 加速增长（slope 2-5%）→ 60-75分（情绪偏热，谨慎乐观）
  - 急速增长/创20日新高（slope >5%）→ 40-60分（过热减分，见顶风险）
  - 持平（slope ±0.5%）→ 50分
  - 温和下降（slope -2%-0）→ 30-45分（杠杆退潮）
  - 急速下降（slope < -2%）→ 15-30分（恐慌去杠杆）
- 权重: 8%（从其余 9 因子按比例压缩）

**个股级 — StockSentimentAnalyzer 新因子 `margin_heat`**:
- 个股融资买入额 / 成交额
- > 15% → 高杠杆追涨（偏危险，减分）
- 5-15% → 适度
- < 5% → 不活跃
- 作为风险修正因子（杠杆过高反而减分）

#### 2.6.2 筹码分布风险 (`cyq_perf`)

**Stage1 过滤 — `chip_pressure`**:
- `profit_ratio > 95%` → 几乎全获利 → 抛压巨大 → 过滤（除龙头连板）

**CompositeScorer 新因子**:
- 获利比例 < 50% → 高分（筹码锁定好）
- 50-80% → 中性
- 80-95% → 低分
- > 95% → 极低分或直接过滤

#### 2.6.3 行业资金共振 (`moneyflow_ind`)

增强 CompositeScorer 的 `sector` 因子:
- 板块 top 3 + 行业资金净流入 → 100（强共振）
- 板块 top 3 + 行业资金净流出 → 70（存疑）
- 非 top 3 + 行业资金净流入 → 60
- 非 top 3 + 行业资金净流出 → 30

Stage1 过滤: 独立涨停（非 top 板块 + 行业资金流出 + 非龙头） → 过滤

### 2.7 板块/行业情绪增强

#### 2.7.1 板块梯队纵深分析 (limit_cpt_list 全字段利用)

| 指标 | 计算方式 | 情绪含义 |
|------|----------|---------|
| 板块赚钱面广度 | 涨停数>0 的板块数 | ≥8=好, <3=无主线 |
| 板块集中度 | top3 涨停数/总涨停数 | >60%=主线清晰, <30%=散乱 |
| 最强板块持续天数 | limit_cpt_list.days | ≥3=主线确认, 1=一日游 |
| 板块轮动速度 | today top3 vs yesterday top3 重合度 | ≥2=延续, 0=快速轮动 |
| 板块纵深结构 | 板块内首板数/2板数/3板+ | 有3板+=纵深好 |

SentimentAnalyzer 新增第 11、12 因子: `sector_breadth` + `sector_continuity`。

**12 因子完整权重分配**:
```
prev_premium:       16% (原18%, 压缩)
up_down_ratio:      10% (原12%)
broken_recovery:    10% (原12%)
board_structure:    10% (原12%)
promotion_rate:      9% (原10%)
auction_strength:    9% (原10%)
yizi_ratio:          8% (原10%)
height_promotion:    7% (原8%)
max_height:          5% (原8%)
margin_momentum:     8% (新增)     ← 2.6.1
sector_breadth:      4% (新增)     ← 2.7.1
sector_continuity:   4% (新增)     ← 2.7.1
                   -----
                   100%
```

Stage1: 板块集中度 < 20% 且无板块持续 ≥2 天 → "无主线日"，top_k 降至 1。

#### 2.7.2 行业指数趋势 (新增 ths_daily)

新增数据: `ths_index`（指数列表，一次性）+ `ths_daily`（指数日线，每日同步）

指标:
- 行业涨幅排名: ths_daily pct_change 排名
- 行业趋势强度: close / MA5 ratio
- 行业相对强弱: 行业 pct_change - 上证 pct_change
- 行业量能变化: vol / MA5(vol)
- 强势行业数量: 涨幅 > 1% 的行业数

#### 2.7.3 板块级情绪周期

**扩展现有 ThemeHeat lifecycle**（不新建独立模块，避免两套周期逻辑矛盾）:

当前 EventClassifier 已有 ThemeHeat lifecycle (NEW/HEATING/PEAK/FADING)，基于 3 天涨停数轨迹。扩展为:
- 数据源增加 limit_cpt_list 的 `days` + `cons_nums` 字段作为辅助判定
- HEATING 确认: 涨停数连续增加 + `days ≥ 2` + `cons_nums` 上升
- PEAK 确认: 涨停数稳定 + 有空间板 (`cons_nums ≥ 3`)
- FADING 确认: 涨停数下降 + 炸板增加 或 `days` 停止增长

Stage1: 个股所在板块 FADING → 过滤; HEATING 持续 ≥2 天 → 加分。

### 2.8 已有数据深度挖掘 + 热榜扩展

#### 2.8.1 limit_cpt_list 全字段利用

当前只用 `up_nums`，浪费了 `days`/`up_stat`/`cons_nums`/`pct_chg`/`rank`。

板块综合评分:
```
涨停家数分(25%): up_nums 排名 → 0-100
持续天数分(25%): days=1→30, days=2→60, days≥3→85, days≥5→100
连板纵深分(25%): cons_nums≥3→100, =2→70, =1→40, =0→20
板块涨幅分(15%): pct_chg 排名 → 0-100
官方热度分(10%): rank 排名 → 0-100
```

主线板块识别: `days ≥ 3` + `cons_nums ≥ 2` + `up_nums ≥ 3` → 确认主线。

一日游标记: `days = 1` + `cons_nums = 0` → 非高分不通过。

#### 2.8.2 ths_hot 行业板块 + 概念板块热榜

新增同步 market: `行业板块` + `概念板块`（现有只同步热股和概念）。

三层融入:
- **市场级情绪**: top 10 热度值 MA3 趋势 → 市场关注度升温/降温
- **板块级评分**: hot 值排名 + 热度趋势 → 增强 sector 因子
- **个股级**: 概念板块 hot 值与自研 ThemeHeat 交叉验证 → 两者都高=强确认，不一致=降权

#### 2.8.3 rank_reason 文本情绪解析

关键词分类（规则匹配，不需要 NLP）:
- 资金类 ("资金流入"/"主力加仓") → 资金驱动（持续性好）
- 政策类 ("政策"/"利好") → 事件驱动（关注衰减）
- 技术类 ("突破"/"创新高") → 技术驱动（需确认）
- 情绪类 ("涨停潮"/"热度飙升") → 情绪驱动（小心过热）

融入 EventClassifier 作为 L1/L2/L3 都无法分类时的 fallback。

### 2.9 优化后情绪体系全景

```
市场级情绪 (SentimentAnalyzer, 12因子)
├── 原有9因子: 涨跌停比/炸板修复/晋级率/高位晋级/连板高度/昨日溢价/一字板/首板结构/竞价
├── 新增: 融资杠杆动量 (margin_detail)
├── 新增: 板块赚钱面广度 (limit_cpt_list)
└── 新增: 板块持续性/轮动速度 (limit_cpt_list)

板块级情绪 (新模块)
├── 板块mini周期: HEATING/PEAK/FADING
├── 行业指数趋势: ths_daily MA5/相对强弱
├── 行业资金流向: moneyflow_ind 净流入排名
└── 板块纵深: limit_cpt_list 全字段

个股级情绪 (StockSentimentAnalyzer, 9+1因子)
├── 核心6: volume_ratio/seal_order/bid_activity/theme_heat/event_catalyst/margin_heat
└── 可选3: popularity/northbound/technical_form

信号评分 sector 因子 (CompositeScorer, 重构)
├── limit_cpt_list 综合分(30%)
├── ths_hot 板块热度分(30%)
├── 行业资金流向分(20%)
└── 板块轮动稳定分(20%)
```

---

## Phase 3: 数据补齐

### 优先级与预估

| 优先级 | 数据源 | 当前覆盖 | 预估调用量 | 预估耗时 |
|--------|--------|---------|-----------|---------|
| P0 | limit_step | 2周 | ~1,500 | ~8分钟 |
| P1 | ths_hot ×4 market | 2天(部分未接) | ~6,000 | ~30分钟 |
| P1 | anns_d | 空表 | ~1,500 | ~8分钟 |
| P1 | moneyflow_ind (新) | 未接入 | ~1,500 | ~8分钟 |
| P2 | margin_detail (新) | 未接入 | ~1,500 | ~8分钟 |
| P2 | top_list + top_inst | 2周 | ~3,000 | ~15分钟 |
| P2 | stk_factor_pro | 2天 | 回测按需 | 渐进 |
| P3 | stk_auction | 2天 | ~1,500 | ~8分钟 |
| P3 | hm_detail | 2天 | ~1,500 | ~8分钟 |
| P3 | cyq_perf (新) | 未接入 | 回测按需 | 渐进 |
| P3 | ths_daily (新) | 未接入 | ~1,500 | ~8分钟 |
| 一次性 | ths_index (新) | 未接入 | 1 | 即时 |

### 执行分批

```
Phase 3a（立即，~40分钟）:
  1. limit_step 6年补齐
  2. ths_hot ×4 market 6年补齐

Phase 3b（次日，~60分钟）:
  3. anns_d 6年补齐
  4. moneyflow_ind 6年补齐 (新建 fetcher/repo/schema)
  5. margin_detail 6年补齐 (新建 fetcher/repo/schema)
  6. top_list + top_inst 6年补齐
  7. ths_index 一次性 + ths_daily 补齐

Phase 3c（回测驱动，渐进）:
  8. stk_factor_pro 回测按需拉取+缓存
  9. cyq_perf 回测按需拉取+缓存

Phase 3d（低优先）:
  10. stk_auction / hm_detail 6年补齐
```

### 新增模块

| 模块 | 类型 |
|------|------|
| `MoneyFlowIndFetcher` + `MoneyFlowIndRepository` | 行业资金流向 |
| `MarginFetcher` + `MarginRepository` | 融资融券明细 |
| `ThsDailyFetcher` + `ThsDailyRepository` | 行业指数日线 |
| `CyqPerfFetcher` + `CyqPerfRepository` | 筹码分布 |
| 对应 5 张新表 schema | moneyflow_ind/margin_detail/ths_daily/ths_index/cyq_perf |

### sync 命令扩展

```bash
hit-astocker sync --backfill -s 20200311 -e 20260310 --api limit_step
hit-astocker sync --backfill -s 20200311 -e 20260310 --api all-p0
hit-astocker sync --backfill -s 20200311 -e 20260310 --api all-p1
```

断点续传: `sync_progress` 表记录进度，中断后从断点继续。

```sql
CREATE TABLE IF NOT EXISTS sync_progress (
    api_name    TEXT PRIMARY KEY,
    last_synced_date TEXT NOT NULL,
    last_error  TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**on-demand API 缓存策略**（stk_factor_pro / cyq_perf）:
- 首次请求某只股票时，拉取该股票完整历史数据并批量入库
- 后续回测直接走本地 SQLite 查询，无需重复调用 API
- 判断缓存命中: `SELECT COUNT(*) FROM stk_factor_pro WHERE ts_code=? AND trade_date BETWEEN ? AND ?`
- 6年回测中涨停股去重约 3000-5000 只，每只 1 次 API 调用即可覆盖全部历史

---

## Phase 4: 因子优化

> Phase 4 具体执行依赖 Phase 1 回测解剖的发现。此处设计"弹药库"，Phase 1 找到出血点后按需选取。

### 4.1 事件面因子优化

#### 4.1.1 多事件叠加效应

当前只取单一最高权重事件。优化为叠加模型:
```
event_weight = primary_weight + Σ(secondary_weight × 0.3)
cap = 1.5 × primary_weight
```

#### 4.1.2 政策主线生命周期管理

新增 `PolicyThemeTracker`:
- 主线识别: 同概念连续 ≥5 天有涨停 + ths_hot 热度 top 10
- 状态: EMERGING → CONFIRMED → MATURE → FADING
- 主线内事件不做常规衰减，按状态调整权重系数

#### 4.1.3 题材传导链

利用 ths_member 概念成分股重叠检测产业链传导:
- 板块A 3+涨停 + 板块B 成分股重叠 ≥20% + 板块B 涨停数<A → 标记传导
- T+1 板块B 首板信号 → event_catalyst +10

### 4.2 情绪面因子优化

#### 4.2.1 情绪动量

新增 `sentiment_momentum` 因子:
```
40% × score_delta 归一化 + 30% × score_accel 归一化 + 30% × broken_rate_trend 反转
```
CompositeScorer sentiment 改为: 60% × overall_score + 40% × sentiment_momentum。

#### 4.2.2 主板/创业板情绪分化

SentimentAnalyzer 拆分计算 10cm/20cm 子情绪:
- 首板信号根据个股板类使用对应市场情绪
- 20cm 情绪冰点时创业板信号额外降权

#### 4.2.3 竞价情绪预判

竞价情绪指数:
```
30% × 竞价高开率 + 25% × 竞价量能比 + 25% × 涨停股竞价强度 + 20% × 竞价涨停预期数
```
联动 Phase 2.2 动态限额: 竞价弱势 → 收紧当日信号。

### 4.3 信号质量因子优化

#### 4.3.1 封板时间连续化

替代 4 档阶梯为连续函数:
```
≤09:35 → 100; ≤10:00 → 线性衰减; ≤11:30 → 缓慢衰减; 午后平台 → 尾盘衰减
```

#### 4.3.2 涨停类型精细化

FIRST_BOARD 子分类: LOW_BASE / MID_BASE / HIGH_BASE / BROKEN_RESEAL
- HIGH_BASE → min_score +10, 止损收紧 1%
- LOW_BASE → seal_quality 权重 ×1.1

FOLLOW_BOARD 子分类: STANDARD / GAP_UP / WEAK_TO_STRONG

#### 4.3.3 量价配合度

新增 `volume_pattern` 因子:
```
缩量涨停 (vol_ratio < 0.8) → 80分（惜售）
适度放量 (0.8-1.5) → 70分
明显放量 (1.5-3.0) → 50分（分歧）
天量涨停 (> 3.0) → 30分（风险高）
```

### 4.4 ML 模型优化

#### 4.4.1 特征扩展 (21维 → 30维)

当前实际为 21 维（14因子 + 7上下文，含 auction_quality + has_auction_data）。

新增因子特征 (+6): margin_momentum, chip_pressure, sector_resonance, sector_continuity, volume_pattern, sentiment_momentum

新增上下文特征 (+3): is_main_theme, board_type_10cm, market_regime

总计: 21 + 6 + 3 = 30维

**过拟合防护**（30维 + ~4000样本，样本/有效参数比偏低）:
- 最小训练样本数 ≥ 1000，不足则降级为 logistic
- GBDT: max_depth 从 4 降为 3，或 n_estimators 从 200 降为 100
- 新增 L2 正则化参数调优（logistic C=0.1-10 grid search）
- 特征删除实验: 逐一删除 importance < 1% 的底部特征，AUC 不降则永久删除

#### 4.4.2 时间序列交叉验证

替代 KFold(shuffle=True) 为 TimeSeriesSplit(n_splits=5):
```
Fold 1: train=[2020], test=[2021]
Fold 2: train=[2020-2021], test=[2022]
...
Fold 5: train=[2020-2024], test=[2025]
```

#### 4.4.3 特征重要性分析

train 命令完成后输出:
- GBDT: feature_importances_ top 10 / bottom 10
- Logistic: coef_ 正负和大小（可解释性报告）
- 重要性 < 1% 的特征标记为候选删除

---

## 修改文件清单

### 修改现有文件

| 文件 | Phase | 改动 |
|------|-------|------|
| `signals/risk_assessor.py` | 2.1 | _cycle_gate() 严格化 |
| `signals/signal_generator.py` | 2.2 | top_k/min_score 调整 + 动态限额 |
| `signals/stage1_filter.py` | 2.4/2.5/2.6.2/2.7.1/2.8.1 | 过滤条件加严 + 新因子门控 |
| `signals/composite_scorer.py` | 2.6.3/2.7/2.8/4.2.1/4.3 | sector 因子重构 + 新因子 |
| `signals/feature_builder.py` | 4.4.1 | 21维→30维 |
| `signals/ranking_model.py` | 4.4.2/4.4.3 | TimeSeriesSplit + 特征重要性 |
| `analyzers/backtest_engine.py` | 1/2.3 | TradeResult 扩展 + 市场自适应出场 |
| `analyzers/sentiment.py` | 2.6.1/2.7.1 | 9→12 因子 |
| `analyzers/stock_sentiment.py` | 2.6.1 | margin_heat 新因子 |
| `analyzers/event_classifier.py` | 4.1.1/4.1.3/2.8.3 | 多事件叠加 + 传导链 + rank_reason |
| `analyzers/sector_rotation.py` | 2.8.1 | limit_cpt_list 全字段利用 |
| `analyzers/firstboard.py` | 4.3.1/4.3.2 | 封板时间连续化 + 类型精细化 |
| `models/backtest.py` | 1 | TradeResult +cycle_phase/profit_regime |
| `models/daily_context.py` | 2.6/2.7/2.8 | DataCoverage 新增字段 |
| `config/settings.py` | 2.2/2.6/2.7/2.8 | 新因子权重配置 |
| `fetchers/sync_orchestrator.py` | 2.8.2/3 | API_REGISTRY 新增 + backfill |
| `fetchers/ths_hot_fetcher.py` | 2.8.2 | 支持行业板块/概念板块 market |
| `commands/backtest_cmd.py` | 1 | backtest-diag 子命令 |
| `commands/sync_cmd.py` | 3.7 | --backfill 模式 + 断点续传 |
| `models/sentiment.py` | 2.6.1/2.7.1 | SentimentScore 新增 margin_momentum/sector_breadth/sector_continuity 字段 |
| `renderers/backtest_diag_renderer.py` | 1 | 回测诊断 Rich 表格渲染（如果单独文件）或修改现有 renderer |
| `database/schema.py` | 3 | 新增 5 张表 DDL + sync_progress 表 |

### 新建文件

| 文件 | Phase | 说明 |
|------|-------|------|
| `analyzers/backtest_diagnosis.py` | 1 | 回测多维诊断分析 |
| `analyzers/policy_theme_tracker.py` | 4.1.2 | 政策主线生命周期 |
| `fetchers/moneyflow_ind_fetcher.py` | 3 | 行业资金流向 |
| `fetchers/margin_fetcher.py` | 3 | 融资融券明细 |
| `fetchers/ths_daily_fetcher.py` | 3 | 行业指数日线 |
| `fetchers/cyq_perf_fetcher.py` | 3 | 筹码分布 |
| `repositories/moneyflow_ind_repo.py` | 3 | 行业资金流向查询 |
| `repositories/margin_repo.py` | 3 | 融资融券查询 |
| `repositories/ths_daily_repo.py` | 3 | 行业指数查询 |
| `repositories/cyq_perf_repo.py` | 3 | 筹码分布查询 |
| `models/margin_data.py` | 3 | 融资融券数据模型 |
| `models/moneyflow_ind_data.py` | 3 | 行业资金数据模型 |
| `models/ths_daily_data.py` | 3 | 行业指数数据模型 |
| `models/cyq_perf_data.py` | 3 | 筹码分布数据模型 |
| `commands/backtest_diag_cmd.py` | 1 | 回测诊断命令 |

---

## Phase 2 叠加效应验证计划

Phase 2 同时收紧多个维度（择时/信号数量/过滤/赚钱效应），叠加后可能导致某些市场状态下零信号。实施策略:

1. **逐项验证**: 每个 2.x 改动独立实施并跑回测，记录信号数量变化和收益变化
2. **信号产出监控**: 回测诊断新增"每日信号产出数分布"维度，标记连续零信号日
3. **叠加顺序**: 先 2.1（择时）→ 验证 → 再 2.2（数量）→ 验证 → 再 2.4（过滤）→ 验证
4. **安全阈值**: 如果叠加后日均信号数 < 0.3（年均 < 75 笔交易），则回退最后一项收紧
5. **信号荒预警**: 连续 10 个交易日零信号时记录日志，分析是策略过严还是市场确实不适合

---

## CLI 命令设计说明

`backtest-diag` 作为 `backtest` 命令的 Typer sub-app 实现:
```bash
hit-astocker backtest diag -s 20200311 -e 20260310
```
而非独立顶层命令，符合 Typer app/sub-app 模式。

---

## 风险与约束

1. **Tushare API 限流**: 会员 500次/分钟，数据补齐总量 ~2万次调用，需分批执行
2. **SQLite 单写瓶颈**: 大量历史数据写入时单线程瓶颈，建议按月分块+事务批量插入
3. **因子过多导致过拟合**: 30维特征 + 6年数据，需严格 TimeSeriesSplit + 特征删除实验防止过拟合
4. **Phase 4 选择性执行**: 不是所有 4.x 项都要做，根据 Phase 1 诊断结果取舍
5. **Phase 2 叠加过滤风险**: 多维度同时收紧可能导致信号荒，需逐项验证（见上方验证计划）

## 成功标准

1. **Phase 1 完成标准**: 生成完整的 6 维诊断报告，明确 top 3 出血点
2. **Phase 2 完成标准**: 6年回测亏损从 -241% 改善至 -100% 以内（仅用现有6年完整数据）
3. **Phase 3 完成标准**: P0+P1 数据全部补齐至 6 年，回测在完整因子模式下运行
4. **Phase 4 完成标准**: 6年回测扭正（累计收益 > 0%）
