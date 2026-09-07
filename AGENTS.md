# AGENTS.md — 给 AI 代理与本仓库维护者的操作指南

本文件给在本仓库工作的 AI 代理（及任何人）提供**关键上下文、纪律与禁忌**。改动任何
策略/账本前先读本文件；README 顶部 ⭐ 标注是策略总览入口，本文是"怎么干活"细则。

---

## 1. 这是什么项目

个人 **A 股量化**：免费数据（baostock 首选 / akshare 兜底）+ 本地事件式回测引擎（含
A 股规则：T+1、1手=100股、涨跌停、佣金/印花/过户/红利税全口径）+ 多轮因子研究 +
**模拟盘长期运营（四账户）**。

- 当前最终策略 = **R5 等权575**（Amihud 流动性 × 中期动量，行业内百分位打分，前 20% 等权，月频调仓）。
- 完整运营文档：`docs/strategy_operations_handbook.md`（**只维护 R5 一版内容**）。
- 多版本探索谱系见 README 顶部 ⭐ 标注（R5 只是其中运营中的一版）。

---

## 2. 环境与运行

```bash
# 依赖用 uv 管理（pyproject.toml + uv.lock 可复现）
uv sync                     # 建 .venv
.venv/bin/python <script>   # 本项目通常直接 .venv/bin/python 跑
```

- 工作目录 = 仓库根目录；**脚本都在 `research/` 下**。
- 数据：`data/fundamental/full_daily.parquet`（全市场 879万+ 行，date/code/close/amount/tradestatus/isST…）、
  `data/round2/adjust_factor.parquet`（复权因子）、`data/round2/industry_full.parquet`（行业）。
- 输出：`output/`（账本 JSON、每日/月度 CSV、图）。**`output/*.csv` 与 `output/*.png` 被 gitignore**，
  不入库；`output/ledger_aum*.json` 已跟踪。

---

## 3. 核心脚本一览

| 脚本 | 用途 | 典型耗时 |
|---|---|---|
| `research/paper_trade.py` | PaperPortfolio 引擎 + 历史全口径回放（`replay`/`replay_w`/`init`）+ `r5_rebalances` 信号 | 单个 share 级回放 ~8-15 分钟 |
| `research/paper_live.py` | **模拟盘四账户**：`init` 建仓 / `step` 月调仓 / `mark` 每日涨幅 / `report` 报告 | mark 数百只 ~1-2 分钟/账户 |
| `research/scenario_ytd.py` | 年度场景回放（`--start`/`--end`），输出 daily_nav/monthly_funds | 同回放 |
| `research/plot_daily_gains.py` | 年度每日涨幅图（累计净值 + 每日涨幅 + 20日MA），`--prefix`/`--title` | 秒级 |
| `research/fetch_full_market.py` | 全市场数据更新（按 code 增量，新 code 才抓） | 分钟~小时 |
| `research/fetch_daily_incremental.py` | **日常收盘后只补当日 K 线**（`<日期>` 参数，按已有 code 补指定日） | 全市场 ~20-30 分钟 |
| `research/factor_round1*.py` | Round 12-16 专项实验（集中版/满仓补买/行业中性/20万/拥挤度择时） | 每个 10-20 分钟 |

---

## 4. 冻结参数（**改前必须预注册 + 用户批准**）

```
佣金 万1.5(单笔最低5元, COMM_MIN=5.0) · 印花税 万5(仅卖出) · 过户费 万0.1(双边)
红利税 10%(DIV_TAX, 保守) · 现金无息
MIN_N=50(池<50跳过月) · MIN_IND=5(行业<5剔除) · LIMIT_THR=0.098(涨停阈值)
START=2013-06-01 · 信号=月末T → 执行=T+1收盘 · 等权575 前20% · 1手=100股
```

- **R5 等权575 是用户明确要求"策略不变"的版本**——不经预注册讨论，不要改任何选股/打分/参数。
- 例外：`paper_live`/`paper_trade` 的成本常量是**硬编码**的（§4 同值），改脚本逻辑时保持一致。

---

## 5. 研究纪律（不可省略）

1. **先预注册、后回测**：任何新变体/参数先写 `docs/factor_roundNN_xxx_plan.md`
   （规则定死、判定标准、诚实风险），**用户点头后再实施**；
2. **结果归档**：跑完把结果写进同一 plan 文档的 `§0 实施结果归档`，如实报告（含失败），
   再提交 commit；
3. **报告要带判定**：对照预注册标准明确"通过/未达标/否决"，诚实写代价与局限；
4. **用数据说话**：不编造数字；关键结论引用回测输出或账本数据；
5. **预注册判定边界**：同一条件未达标持续 ≥3 轮才算 blocked（见工具纪律）。

---

## 6. 模拟盘运营（四账户）

- 账户：`60万/100万/300万/600万`，账本 `output/ledger_aum{60w,100w,300w,600w}.json`。
- **建仓 2026-09-01（信号 2026-08-31）**。注意：**生产账户跑的是"原版 575 等权"**，
  小账户因 1手 约束天然退化（60万 只持有 267 只、37% 现金）——**这是现状，不是 bug**。
- 每日：`fetch_daily_incremental.py <日期>` → 四账户各跑一次 `paper_live.py mark --aum NNNN`。
- 每月：`paper_live.py step`（自动推进四账户调仓）+ `report`。
- **对账不变量**（每次 step 后抽查）：① 期末净值=现金+持仓；② 期末≈期初−费用(<1%)；
  ③ 月涨幅连乘=累计。
- **"今日涨幅"以数据源最新 K 线为准**，不是系统日历——先 `date` 确认今天，再查
  `full_daily.parquet` 最大日期，数据没出就等数据出了再 mark。

---

## 7. 资金规模结论（已实测，别推翻）

| 资金 | 可行口径 | 超额 | 结论 |
|---|---|---|---|
| <20万 | — | — | 不可行 |
| 20万 | 前150+补买 | +1.86pp | 不建议（费用吃光） |
| **60万** | **前100+满仓补买** | +3.4~3.6pp | 绝对可行下限 |
| **300万** | 原版 575 等权 | +4.43pp | 最优起点 |
| 600万 | 原版满配 | +4.72pp | 效率饱和 |

**风控五轮总收束（R4b/4c/4d/6/16）**：熔断/均线/双熔断/拥挤度择时都压不住回撤且牺牲超额——
`−50% 级回撤是 Amihud+满仓小盘的市场定价，扛住+深坑不割肉是唯一验证可行的应对`。

---

## 8. 禁忌清单

- ❌ 不跑多次重回测去"试"：share 级回放 10-20 分钟，**先预注册、后台跑、不重复**；
- ❌ 不改冻结参数 / 不改 R5 选股逻辑；
- ❌ 不提交 `output/*.csv`、`output/*.png`（gitignored，可再生成）；
- ❌ 不把其他策略版本写进 `docs/strategy_operations_handbook.md`（它只维护 R5）；
- ❌ 不凭文件时间戳断"今天几号"（先 `date`）；
- ❌ 不编造回测/账本数字——拿不到就如实说"数据未出/需跑"。

---

## 9. 当前状态速查（写 AGENTS.md 时）

- 系统日期与数据源不一致：**系统时钟 2026-09-07（周一），但 baostock/本地数据最新仅 2026-09-04**。
  运营 mark 以数据为准，四账户已 mark 到 **09-04**（60w +0.19% / 100w +0.15% / 300w +0.05% / 600w −0.04%）。
- 最近 commit 链含：R12-16 实验（集中版/满仓/行业中性/20万/拥挤度择时）、fetch_daily_incremental、
  运营手册 + README 标注。
- 后续任何变体实验 → 从 `docs/factor_round17_..._plan.md` 起编号，先预注册。
