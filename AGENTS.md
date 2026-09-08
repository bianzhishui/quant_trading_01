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
uv run <tool>               # uv 缓存已在项目内(uv.toml cache-dir=.uv-cache), 无需外部权限
```

- **uv 缓存已配置在项目内**（`uv.toml` 的 `cache-dir = ".uv-cache"`，已 gitignore）——
  `uv run`/`uv sync` 不依赖工作区外的 `~/.cache/uv`，沙箱默认权限即可，**不要改回全局缓存**。
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
5. **预注册判定边界**：同一条件未达标持续 ≥3 轮才算 blocked（见工具纪律）；
6. **同仓库 Python 脚本间调用用"导入模块"，不用 subprocess**：
   - 已重构范例：`daily_update.py` 直接
     `from research.fetch_daily_incremental import update_date`、
     `from research.paper_live import mark`（省 4 次进程冷启动 + 4 次字体缓存，治发热）；
   - 被导入的脚本须满足：逻辑放函数、`main()` 只做 argparse 壳、**模块级不读 sys.argv**
     （否则 import 时读错调用方参数）；
   - subprocess 只留给：跨环境/跨语言、独立一次性工具、需超时强杀的场景；
   - 退出码语义用函数返回值（如 update_date 返回 0/3）+ try/except 保留，不靠进程码。

---

## 6. 模拟盘运营（四账户）

- 账户：`60万/100万/300万/600万`，账本 `output/ledger_aum{60w,100w,300w,600w}.json`。
- **建仓 2026-09-01（信号 2026-08-31）**。注意：**生产账户跑的是"原版 575 等权"**，
  小账户因 1手 约束天然退化（60万 只持有 267 只、37% 现金）——**这是现状，不是 bug**。
- 每日：**一键 `python research/daily_update.py`**（自动判断最新交易日 → 缺则补当日
  行情 → 四账户 mark → 输出"账户/本金/最新NAV/当日涨幅/盈亏(元)/盈亏率/建仓日NAV"总表；
  数据源未发布当天会自动探测跳过并以最新已有数据为准；`--table` 只读表不重跑）。
  手动分解：`fetch_daily_incremental.py <日期>` → 四账户各跑一次 `paper_live.py mark --aum NNNN`。
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

- ✅ **每次改动 Python 代码后必须格式化**：`uv run ruff format .` + `uv run ruff check .`
  （ruff 默认格式风格，已配 pyproject；提交前 check 必须 0 错误；pre-commit 可选装 `.pre-commit-config.yaml`）；
- ❌ 不跑多次重回测去"试"：share 级回放 10-20 分钟，**先预注册、后台跑、不重复**；
- ❌ 不改冻结参数 / 不改 R5 选股逻辑；
- ❌ 不提交 `output/*.csv`、`output/*.png`（gitignored，可再生成）；
- ❌ 不把其他策略版本写进 `docs/strategy_operations_handbook.md`（它只维护 R5）；
- ❌ 不凭文件时间戳断"今天几号"（先 `date`）；
- ❌ 不编造回测/账本数字——拿不到就如实说"数据未出/需跑"；
- ❌ **测试/验证代码绝不直接读写真实数据文件**（曾因 `shutil.move` 用只含 date/code
  的副本覆盖 full_daily.parquet，导致全部历史价格丢失）——先在 /tmp 副本或备份上测，
  测完恢复，再碰真实文件；
- ⚠️ **baostock 服务不稳定时不要连续重试**（全历史大结果集 `rs.next()` 会挂起、
  持续连接会被拒"用户未登录"）——停止猛打、等待恢复再跑；代码优先用本地代码清单
  （`query_stock_basic` 在本环境会挂起）。

---

## 9. 当前状态速查（写 AGENTS.md 时）

- **本地数据已补全**：`full_daily/` 年分区，**3409 只 / 9,269,410 行**（3194 在市 + 215 有数据的
  主板退市股），2012-06-01 → 2026-09-07；在市缺失=0；退市股缺因子用 qfq 回退（Round 17）。
- **系统日期可能与数据源不一致**（如数据源未发布当日）——运营 mark 以数据为准，先 `date`
  再查 `load_full_daily` 最大日期。
- **daily_nav_aum*.csv 已修复**（2026-09-08 重建：init×4 重新选股 + mark×4，09-01→09-07 连续；
  当日涨幅 60w +0.24% / 100w +0.31% / 300w +0.57% / 600w +0.68%，盈亏率 −0.37%~−0.51%）。
- 最近 commit 链含：R17 基建（年分区/退市股宇宙/data_io）、R17 回测归档（偏差 0.13pp）、
  fetch 加固、subprocess→导入重构、ruff/uv 项目内缓存。
- 后续任何变体实验 → 从 `docs/factor_round18_..._plan.md` 起编号，先预注册。
