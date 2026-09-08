# R5 等权575 策略 · 数据源与完整性档案

> 版本 v1.0 ｜ 2026-09-08 ｜ 服务对象：R5 等权575（Amihud×中期动量 行业内百分位）
> 本文档登记策略**每个数据环节用到的所有数据源**、来源、范围、校验方法与当前完整性状态。
> 数据源变更/恢复后，本文档必须同步更新（与 AGENTS.md、运营手册同级的运维文档）。

---

## 1. 数据源总览（一张表）

| # | 数据源 | 文件 | 用途（策略环节） | 来源 | 获取脚本 | 当前状态 |
|---|---|---|---|---|---|---|
| 1 | **全市场日线** | `data/fundamental/full_daily/` 年分区 | 选股池/因子/调仓执行的**主数据** | baostock 前复权日线 | `fetch_full_market.py`（全量）`fetch_daily_incremental.py`（每日增量） | ✅ **已恢复并升级**（含退市股，见 §3.1） |
| 2 | **复权因子** | `data/round2/adjust_factor.parquet` | 真实价格账 + 分红/送转事件补回 | baostock 复权因子 | `fetch_corporate_actions.py` | ✅ 完好（git 跟踪） |
| 3 | **行业分类** | `data/round2/industry_full.parquet` | 行业内百分位打分（MIN_IND=5） | 东财行业 | `fetch_full_industry.py` | ✅ 完好（git 跟踪） |
| 4 | 旧800只池日线(含额) | `data/round2/daily_ext.parquet` | Round1-6 早期研究（现策略不用） | baostock | `fetch_round2_data.py` | ✅ 完好（缺 tradestatus/isST，不可直接替代 #1） |
| 5 | 旧800只池日线(无额) | `data/fundamental/daily.parquet` + shards | 早期研究（无 amount，Amihud 不可用） | baostock | 旧管线 | ✅ 完好 |
| 6 | 分红明细 | `data/round2/dividends.parquet` | 备查；现策略走复权因子事件驱动 | baostock | `fetch_round2_data.py --dividends` | ✅ 完好（含预告登记日） |
| 7 | 历史研究因子 | `round2/hsgt/margin/roe/industry.parquet` | Round1-2 因子筛选（现策略不用） | baostock/东财 | `fetch_round2_data.py` | ✅ 完好（hsgt 止于 2024-08 系源停更） |
| 8 | 四账户账本 | `output/ledger_aum{60w,100w,300w,600w}.json` | 生产账本（持仓/现金/净值） | 本地生成 | `paper_live.py` | ✅ 完好 |

---

## 2. 策略数据流（谁用谁）

```
                    ┌─────────────────────────────────────────────┐
                    │  #1 全市场日线 full_daily.parquet            │
                    │  close / amount / tradestatus / isST        │
                    └──────┬──────────┬───────────┬───────────────┘
                           │          │           │
   build_pool(选股池)      │          │           │  等权575执行价
   375日/非ST/主板/未涨停   ▼          ▼           ▼
                  ┌─────────────┐  ┌──────────────────────┐
                  │ Amihud因子  │  │ 中期动量             │
                  │ |ret|/amount│  │ close[21]/close[250] │
                  │ ×1e6, roll21│  │                      │
                  └──────┬──────┘  └──────────┬───────────┘
                         │   #3 行业 industry_full.parquet
                         ▼   （行业内百分位 rank(pct=True)）
                  ┌──────────────────────────────┐
                  │ 综合分 sc=(pa+pm)/2 → 前20%  │
                  └──────────────┬───────────────┘
                                 ▼
                  #2 复权因子（除权日补回分红/送转, 真实价格账）
                  #8 账本 ledger（持仓/现金/净值, 月调仓/日mark）
```

**依赖关系**：策略运行 **强依赖 #1（日线）**；#2/#3 是打分与记账的必需项；#4-#7 仅历史研究，现策略不读。

---

## 3. 各数据源详细档案

### 3.1 全市场日线 `full_daily/` 年分区（核心）

| 项 | 内容 |
|---|---|
| 结构 | `date, code, close(前复权), pbMRQ, turn, amount, peTTM, tradestatus, isST`；数值列 float64、snappy、index=False、原子写 |
| 存储 | **`data/fundamental/full_daily/` 按年分区**（`2012.parquet`…`2026.parquet`）；统一读取层 `research/data_io.py`（全库唯一入口，旧单文件已废弃为 `.singlefile.bak` 回滚点） |
| 范围 | 2012-06-01 → 最新交易日；**3409 只**（主板 sh.60*/sz.00*，**含 215 只有数据的主板退市股**，Round 17 去幸存者偏差） |
| 规模 | 9,269,410 行 |
| 用途 | 选股池过滤（tradestatus/isST/涨停）、Amihud（close+amount）、动量（close）、调仓执行价（close） |
| 来源 | baostock `query_history_k_data_plus`（adjustflag=2 前复权） |
| 更新 | 每日收盘后 `fetch_daily_incremental.py <日期>`（分区写，单只探测+原子写）；全量用 `fetch_full_market.py`（宇宙=stock_basic 含退市，退市股按 ipo→outDate 区间抓取） |
| 校验 | 最新日行数 ≥ 前5交易日最大×90% 且 ≥ 总code×50%（daily_update 守卫）；close 非空率≈100% |
| **状态** | ✅ **2026-09-08 已恢复并升级**（事故后全量重下：3194 在市 + 215 退市 + 75 窗口外跳过 + 2 全程停牌无行） |
| 边界 | 停牌日无行（tradestatus=="1" 才入库）；2012 前退市/全程停牌股无行属设计；退市股缺复权因子时 qfq 回退（F=1.0，仅影响 share 级回放精度） |

### 3.2 复权因子 `round2/adjust_factor.parquet` ✅

| 项 | 内容 |
|---|---|
| 结构 | `code, date, foreAdjustFactor` |
| 范围 | 2012-01-05 → 2026-09-03；3,123 只；32,332 行 |
| 用途 | `raw = close/F` 得到真实价格账；F 变化日事件驱动补回除权缺口（现金分红按 10% 红利税入账、送转价值等效） |
| 来源 | baostock 复权因子 |
| 校验 | code 数 ≥ 3000；日期连续；git 跟踪（可回滚） |
| 状态 | ✅ 完好 |

### 3.3 行业分类 `round2/industry_full.parquet` ✅

| 项 | 内容 |
|---|---|
| 结构 | `code, industry` |
| 范围 | 3,193 只 |
| 用途 | 行业内百分位（R5 核心：行业中性化 + MIN_IND=5 过滤） |
| 来源 | 东财行业分类 |
| 校验 | 与 #1 的 code 交集 ≥ 95%；git 跟踪 |
| 状态 | ✅ 完好 |

### 3.4 旧800只池（#4 daily_ext / #5 daily.parquet+shards）✅

- `round2/daily_ext.parquet`：800 只，close/turn/amount/peTTM，2010→2026-09-03，含额但**缺 tradestatus/isST** → 不可直接替代 #1；
- `fundamental/daily.parquet` + `daily_shard_*.parquet`：800 只，close/pbMRQ/tradestatus/isST，**无 amount** → Amihud 不可用；
- 均为 Round1-6 早期研究产物，现策略不读。✅ 完好。

### 3.5 分红明细 `round2/dividends.parquet` ✅
`code, date, cashBeforeTax, stocksPs`，2,120 只；含 36 行"未来日期"（预告登记日至 2026-10-23，属正常公告）。现策略公司行为走复权因子事件驱动，本文件仅备查。

### 3.6 账本 `output/ledger_aum*.json` ✅
四账户现金/持仓/净值与建仓（2026-09-01）一致；`nav_history` 正确。**注意**：`daily_nav_aum*.csv` 在事故中被无价格 mark 覆盖（5 行错误值），待 #1 恢复后重跑 `daily_update.py` 自动修复。

---

## 4. 当前完整性状态（红绿灯）

| 数据 | 状态 | 影响 |
|---|---|---|
| #1 全市场日线 | 🟢 **已恢复**（3409 只 / 9,269,410 行，含退市股，年分区） | 可运行 |
| #2 复权因子 | 🟢 完好（在市股 3123 只；退市股缺因子用 qfq 回退，见 §3.1 边界） | 精度受限（share 回放） |
| #3 行业 | 🟢 完好 | 无 |
| #4-#7 历史数据 | 🟢 完好 | 无 |
| #8 账本 | 🟢 完好 | 无 |
| daily_nav CSV | 🟢 已修复（2026-09-08 重建 init×4+mark×4，09-01→09-07 连续） |

**当前无阻塞**；唯一待办 = baostock 恢复后日常增量（每日收盘后 `fetch_daily_incremental.py <日期>` + `daily_update.py`）。

---

## 5. 更新流程

### 5.1 全量重下（已完成，历史记录）

2026-09-08 事故后已全量重下并升级为年分区 + 含退市股宇宙（3194 在市 + 215 退市）。
如需重跑（数据再丢失/重建环境）：
```bash
python research/fetch_full_market.py     # 全量重下(宇宙=stock_basic 含退市) → full_daily/ 年分区
python research/daily_update.py          # 守卫放行 → 四账户重 mark → 修复 daily_nav CSV → 出表
# 验证：close 非空率≈100%、最新日行数≈3187、在市缺失=0
```

### 5.2 日常更新（每日收盘后）

```bash
python research/fetch_daily_incremental.py <日期>   # 单只探测：未发布秒退；发布则补全（原子写）
python research/daily_update.py                     # 守卫(≥前5日90%) → 四账户 mark → 总表
```

### 5.3 月度（每月末数据到手）

```bash
python research/fetch_daily_incremental.py <月末日>   # 若有新交易日
python research/paper_live.py step                    # 四账户月调仓
python research/paper_live.py report
```

---

## 6. 完整性校验清单（可执行）

```bash
# ① 最新交易日行数守卫（daily_update 内置）
python research/daily_update.py --table   # 正常时应显示四账户总表

# ② 手动核查关键文件
python -c "
import pandas as pd
d = pd.read_parquet('data/fundamental/full_daily.parquet', columns=['date','code','close'])
print('最新:', d['date'].max(), '| 该日行数:', (d['date']==d['date'].max()).sum(), '| close非空率:',
      d[d['date']==d['date'].max()]['close'].notna().mean())
"
# ③ 复权因子/行业（git 跟踪，git status 无改动即完好）
git status --short data/round2/
```

---

## 7. 事故记录与教训（2026-09-07）

- **事故**：验证"数据完整度守卫"时，测试脚本用只含 `date,code` 的副本 `shutil.move` 覆盖了真实 `full_daily.parquet`（`finally` 块为空未还原）→ 全部历史价格值丢失；
- **根因**：测试代码直接操作真实数据文件，无备份、无还原；
- **教训（已写入 AGENTS.md 禁忌清单）**：测试/验证代码**绝不直接读写真实数据文件**；先 /tmp 副本或备份上测；baostock 不稳定时**停止猛打、等待恢复**；
- **防护**：daily_update 已加严谨数据守卫（前5日基线×90% + 总code 50% 双保险），半成品数据拒绝 mark。

---

*本文档与 `AGENTS.md` §2/§6、`docs/strategy_operations_handbook.md` §8 配合使用；任何数据源变更须同步更新本文档。*
