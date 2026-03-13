# Phase 3: 数据补齐 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 6 年历史数据（2020-2026），使 Phase 2 回测结果覆盖完整时间段，消除因子缺失导致的信号盲区。

**Architecture:** 现有 `SyncOrchestrator.sync_date_range_bulk()` 已支持月级分块 + 4 worker 并行获取 + 顺序写入。所有 12 个 batchable API 均有 `fetch_range()` 支持。无需新建代码，仅需运行 sync 命令。

**Tech Stack:** 现有 CLI (`hit-astocker sync`)，Tushare Pro API

**关键发现:** sync 基础设施已完整 — 支持 date-range bulk fetch、INSERT OR REPLACE 幂等写入、trade_cal 自动过滤节假日、sync_log 日志追踪。

---

## Task 1: 运行 6 年全量数据同步

**目标:** 补齐 limit_step、top_list、top_inst、ths_hot、anns_d 等所有已有 fetcher 的 6 年历史数据。

**前提:** Tushare Pro API token 已配置在 `.env` 中。

- [ ] **Step 1: 检查当前数据覆盖**

```bash
cd /Users/lakeshen/MyProject/hit-astocker
python -c "
import sqlite3
conn = sqlite3.connect('data/hit_astocker.db')
for table in ['limit_step', 'top_list', 'top_inst', 'ths_hot', 'anns_d', 'limit_list_d', 'daily_bar']:
    r = conn.execute(f'SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM {table}').fetchone()
    print(f'{table}: {r[0]} ~ {r[1]} ({r[2]} rows)')
conn.close()
"
```

- [ ] **Step 2: 运行 P0 数据补齐 (limit_step)**

limit_step 是 P0 优先级 — 直接影响连板生存率因子。

```bash
hit-astocker sync --start 20200101 --end 20260313 --api limit_step
```

预估: ~1,500 API 调用，~8 分钟

- [ ] **Step 3: 运行 P1/P2 数据补齐 (全量)**

一次性补齐所有 batchable API（包括 limit_list_d、daily_bar、moneyflow 等已有 6 年数据的会自动跳过重复）:

```bash
hit-astocker sync --start 20200101 --end 20260313
```

这会触发 `sync_date_range_bulk()`:
- Phase 1 (batch): 12 API 月级分块并行获取
- Phase 2 (per-day): ths_hot + anns_d 逐日获取
- Phase 3 (on-demand): stk_factor_pro + concept_detail 按需获取

预估总时间: 30-60 分钟（取决于 Tushare API 响应速度）

- [ ] **Step 4: 验证数据覆盖**

重新运行 Step 1 的检查脚本，确认所有表都有 2020-2026 的数据。

---

## Task 2: 重新运行 6 年回测验证

- [ ] **Step 1: 运行 backtest-diag**

```bash
hit-astocker backtest-diag -s 20200101 -e 20260301
```

对比 Phase 2 基线:
- Phase 2 (部分数据): 29 笔, 62.1% 胜率, +71.9% 累计
- 预期: 数据补齐后交易笔数增加（更多日期有完整因子），关注胜率和累计收益是否仍为正

- [ ] **Step 2: 分析结果**

如果累计收益转负，分析哪些新覆盖的年份/时段拖累了表现，为 Phase 4 因子优化提供数据支撑。

- [ ] **Step 3: 推送到 GitHub**

```bash
git push origin main
```

（注: 数据补齐不涉及代码修改，仅 .db 文件变化。.db 文件不入 git。）

---

## Key Decisions

1. **不新建 fetcher/repo/schema**: moneyflow_ind、margin_detail、ths_daily、cyq_perf 等新数据源延后到 Phase 4
2. **全量同步而非增量**: INSERT OR REPLACE 幂等写入，已有数据会被覆盖（保持数据一致性）
3. **一次性跑完**: 避免分批打断，让 SyncOrchestrator 自动处理月级分块和并行
