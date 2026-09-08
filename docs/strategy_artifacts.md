# R5 等权575 策略 · 程序产物说明文档

> 版本 v1.0 ｜ 2026-09-08 ｜ 服务对象：R5 等权575（Amihud×中期动量 行业内百分位）
> 本文档登记**跑本策略程序产生的全部产物**：文件、生成脚本、触发时机、格式含义、再生成命令。
> 产物分三类：**生产运营**（模拟盘四账户）、**年度场景**（回放）、**回测/研究**（各轮实验）。

---

## 1. 产物总览（一张表）

| 类别 | 产物 | 生成脚本 | 触发 | git |
|---|---|---|---|---|
| 运营 | `output/ledger_aum{XX}w.json` | `paper_live.py` init/step | 建仓/月调仓 | ✅ 入库 |
| 运营 | `output/daily_nav_aum{XX}w.csv` | `paper_live.py mark` / `daily_update.py` | 每日 | ❌ gitignore |
| 运营 | `output/monthly_funds_aum{XX}w.csv` | `paper_live.py step` | 每月 | ❌ gitignore |
| 运营 | `output/paper_init_aum{XX}w.csv` | `paper_trade.py init` | 建仓演示 | ❌ |
| 运营 | `output/strategy_holdings_*.csv` | 持仓快照 | 建仓时 | ❌ |
| 运营 | `output/account_comparison.csv` | 对比表 | 定稿 | ❌ |
| 场景 | `output/daily_nav_{YYYY0101}_aum{XX}w.csv` | `scenario_ytd.py --start` | 年度复盘 | ❌ |
| 场景 | `output/monthly_funds_{YYYY0101}_aum{XX}w.csv` | `scenario_ytd.py --start` | 年度复盘 | ❌ |
| 场景 | `output/daily_gains_{YYYY0101}.png` | `plot_daily_gains.py --prefix` | 年度复盘 | ❌ |
| 回测 | `output/factor_round{3..9}_summary.csv` + `.png` | 各轮实验脚本 | 实验时 | ❌ |
| 回测 | `output/factor_screen_round{1,2}_summary.csv` | 因子筛选 | 实验时 | ❌ |
| 回测 | `output/factor_corr_*.csv` | 因子相关性 | 实验时 | ❌ |
| 辅助 | `data/round2/adjust_factor_live.parquet` | `paper_live.py step` | 每月增量补因子 | ❌ |

---

## 2. 生产运营产物（四账户模拟盘）

### 2.1 账本 `output/ledger_aum{60w,100w,300w,600w}.json`

**唯一入库的生产状态文件**（git 跟踪，可回溯）。

```json
{
  "aum": 3000000,              // 账户本金
  "last_signal": "2026-08-31", // 最近信号日(月末T)
  "last_exec": "2026-09-01",   // 最近调仓执行日(T+1)
  "bench_base": 2.6285746352529453, // 基准起点(同池等权, 建仓日=1基准)
  "shares": { "sh.603937": 400, ... },  // 当前持仓: 代码→股数
  "cash": 458689.61,           // 当前现金
  "nav_history": [ {"date": "...", "nav": 2997219.61, "bench": 1.0} ], // 调仓日净值
  "trades": [ {"code":"sh.603937","side":"buy","qty":400,"price":12.01,
               "amount":4804.0,"佣金":5.0,"印花税":0.0,"过户费":0.05,"滑点":0.0} ], // 全部成交
  "div_credited": 0.0,         // 累计税后分红
  "total_fees": 2780.54        // 累计总费用
}
```

**字段含义**：`shares` 是唯一权威持仓；`nav_history` 每次调仓追加一条（含基准）；
`trades` 记录每笔成交与四项费用拆分（佣金/印花/过户/滑点）。

### 2.2 每日净值 `output/daily_nav_aum{XX}w.csv`（3 列）

```
date,nav,涨幅%
2026-09-02,2976548.61,-0.6897
2026-09-03,2967658.89,-0.2987
2026-09-04,2969110.68,0.0489
```
- `nav` = 当日收盘账户总值（现金+持仓盯市，含分红入账）；`涨幅%` = 今/昨收盘 NAV − 1；
- 由 `mark` 每次**全量重写**；`daily_update.py` 一键更新四账户；
- ⚠️ **当前状态**：被 09-07 事故的坏 mark 覆盖（5 行错误值），待数据恢复后重跑修复。

### 2.3 月度资金变动 `output/monthly_funds_aum{XX}w.csv`（12 列）

```
date,pre_nav,post_nav,月涨幅%,买入额,卖出额,换手率%,费用,分红入账,期末现金,期末持仓,较本金盈亏
2026-09-01,3000000.0,2997219.61,,2538530.0,0,84.618,2780.54,0.0,458689.61,2538530.0,-2780.39
```
| 列 | 含义 |
|---|---|
| date | 调仓执行日 |
| pre_nav / post_nav | 下单前/后账户总值（同一天收盘价） |
| 月涨幅% | 本次/上次调仓后净值 − 1 |
| 买入额 / 卖出额 | 本次调仓成交金额 |
| 换手率% | 单边换手 = (买+卖)/2 ÷ 期初净值 |
| 费用 | 佣金+印花税+过户费（本次） |
| 分红入账 | 税后分红（期间） |
| 期末现金 / 期末持仓 | 调仓后状态 |
| **较本金盈亏** | 期末净值 − 账户本金（赚/亏多少钱） |

首行是**建仓种子行**（月涨幅为空）；之后每月 step 追加一行。

### 2.4 其他运营产物

| 产物 | 内容 |
|---|---|
| `paper_init_aum{XX}w.csv` | `paper_trade.py init` 的建仓成交明细（按金额排序，头部5笔打印到控制台）；`paper_init_aum10w.csv` 是 10万 不可行性演示 |
| `strategy_holdings_2026-09-01.csv` | 持仓快照（13 列）：`code,name,industry,amihud,mom,pa,pm,score,price,qty300,qty600,weight` —— 含因子分与两档股数 |
| `account_comparison.csv` | 四账户建仓+回测对比表（定稿时生成） |

---

## 3. 年度场景产物（scenario_ytd.py 回放）

### 3.1 年度每日净值 `daily_nav_{YYYY0101}_aum{XX}w.csv`（4 列）

```
date,nav,涨幅%,较本金盈亏
2026-09-02,598379.76,-0.3265,-1620.24
```
比生产版多一列 **较本金盈亏**（NAV − 本金）。

### 3.2 年度月度资金 `monthly_funds_{YYYY0101}_aum{XX}w.csv`（12 列）
同 §2.3 结构，但按"年初建仓"场景重放，含每年第一个执行日的建仓行。

### 3.3 年度图 `daily_gains_{YYYY0101}.png`
- **上子图**：四账户累计净值（建仓日=1.0 归一）；
- **下子图**：每日涨幅%（细线）+ 20日滚动均线（粗线）；
- 生成：`plot_daily_gains.py --prefix 20260101 --title "2026年至今"`。

再生成（数据恢复后）：
```bash
python research/scenario_ytd.py --start 2026-01-01   # 刷新 daily_nav/monthly_funds
python research/plot_daily_gains.py --prefix 20260101 --title "2026年至今(至09-07)"
```

---

## 4. 回测/研究产物（各轮实验）

| 产物 | 内容 | 来源轮次 |
|---|---|---|
| `factor_screen_round{1,2}_summary.csv` + `.png` | 因子批量筛选汇总/图 | Round 1/2 |
| `factor_round3..9_summary.csv` + `.png` | 组合/风控/中性化/扩池/实盘化各轮汇总 | Round 3-9 |
| `factor_round8_holdings_2026-09-03.csv` | Round 8 实盘化起点持仓（575 只） | Round 8 |
| `factor_corr_ic*.csv` / `factor_corr_crosssec*.csv` | 因子 IC/横截面相关性 | Round 2 |
| `reversal_factor_*.csv` + `.png` | 短期反转因子实验 | 早期 |
| `backtest_*.png/.trades.csv` | 双均线示例回测 | 学习示例 |
| `weekday_effect_*.png` / `dividend_factor.png` / `ew_base.png` / `etf_*.png` / `convertible_double_low.png` | 其他研究图 | 早期 |

**结论性数字以 `docs/factor_round*_plan.md` 的 §0 归档为准**，CSV 是过程产物。

---

## 5. 辅助数据产物

- `data/round2/adjust_factor_live.parquet`：`paper_live.py step` 每月对**新增持仓股**增量查询的实时复权因子（baostock 限流 60s 退避）；与静态因子 `adjust_factor.parquet` 合并成完整面板。若缺失，step 会用静态因子继续并提示尽快重抓。

---

## 6. 入库规则（重要）

| 类型 | git 状态 | 原因 |
|---|---|---|
| `ledger_aum*.json` | ✅ **入库** | 生产状态，需版本回溯 |
| `output/*.csv`、`output/*.png` | ❌ gitignore | **派生数据/图，全部可再生成** |
| `data/round2/adjust_factor_live.parquet` | ❌ gitignore | 派生 |
| `docs/*.md` | ✅ 入库 | 预注册/归档/手册 |

**任何 CSV/PNG 丢了都不用慌**：跑对应脚本即可再生；**ledger 是唯一不可再生的生产状态**（已入库+备份）。

---

## 7. 当前状态（2026-09-08）

| 产物 | 状态 |
|---|---|
| 四账本 ledger | ✅ 完好（git 入库） |
| `daily_nav_aum*.csv`（生产） | ⚠️ 被坏 mark 覆盖，**待数据恢复后重跑修复** |
| `monthly_funds_aum*.csv`（生产） | ✅ 完好（仅建仓种子行） |
| 年度场景 CSV/PNG | ✅ 完好（到 09-04 版本；恢复后可刷新到 09-07） |
| 回测/研究产物 | ✅ 完好（历史实验，与数据恢复无关） |
| `adjust_factor_live.parquet` | ⚠️ 依赖 full_daily 恢复后下次 step 才会再补 |

---

## 8. 产物 ↔ 脚本 ↔ 环节 对照（速查）

| 想干什么 | 命令 | 产物 |
|---|---|---|
| 每日看四账户涨幅+盈亏 | `python research/daily_update.py` | 控制台总表 + daily_nav CSV |
| 只看表不重算 | `python research/daily_update.py --table` | 控制台总表 |
| 月调仓 | `python research/paper_live.py step` | ledger + monthly_funds |
| 月报告 | `python research/paper_live.py report` | 控制台 + monthly_funds tail |
| 年度回放 | `python research/scenario_ytd.py --start YYYY-01-01` | daily_nav/monthly_funds_{prefix} |
| 年度图 | `python research/plot_daily_gains.py --prefix YYYY0101` | daily_gains_{prefix}.png |
| 历史全口径回测 | `python research/paper_trade.py replay --aum 3000000` | 控制台指标 |
| 建仓明细 | `python research/paper_trade.py init --aum 3000000` | paper_init CSV |

---

*本文档与 `docs/data_sources_integrity.md`（数据源）、`docs/strategy_operations_handbook.md`（运营）、`AGENTS.md`（纪律）配套；产物结构变更须同步更新本文档。*
