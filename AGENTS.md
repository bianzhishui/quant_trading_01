# AGENTS.md — 给 AI 代理与本仓库维护者的操作指南

本文件给在本仓库工作的 AI 代理（及任何人）提供**关键上下文、纪律与禁忌**。改动任何
策略/账本前先读本文件；README 顶部 ⭐ 标注是策略总览入口，本文是"怎么干活"细则。

---

## 1. 这是什么项目

个人 **A 股量化**：免费数据（baostock 首选 / akshare 兜底）+ 本地事件式回测引擎（含
A 股规则：T+1、1手=100股、涨跌停、佣金/印花/过户/红利税全口径）+ 多轮因子研究 +
**模拟盘长期运营（四账户）**。

- 当前最终策略 = **R5 等权575**（Amihud × 中期动量 × F4低成交额，行业内百分位打分，前 20% 等权，月频调仓）。
- 完整运营文档：`docs/strategy_operations_handbook.md`（**只维护 R5 一版内容**）；
  **P3 运营文档：`docs/p3_operations_handbook.md`**（低价股策略，八账户，独立于 R5 手册）。
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
- 工作目录 = 仓库根目录；**脚本都在 `scripts/` 下**。
- 数据：`data/fundamental/full_daily/` 年分区（全市场主板行情 ~930万行，date/code/close/amount/tradestatus/isST…，经 data_io 统一读取）、
  `data/round2/adjust_factor.parquet`（复权因子）、`data/round2/industry_full.parquet`（行业）；
  **低价股研究补抓（Round 数据工程）**：`data/round2/financial_quality.parquet`（全市场主板 3485 只
  全历史质量财务：扣非净利润/每股经营现金流/ROE/资产负债率，akshare 同花顺，含退市股）、
  `data/round2/dividends.parquet`（全市场在市全历史分红，东财；退市股分红接口不可得如实记录）；
  详见 `docs/data_backfill_low_price_report.md`。
- 输出：`output/`（账本 JSON、每日/月度 CSV、图）。**运营产物按策略分子目录**：
  `output/r5/`（R5 四账户 + 年度场景/全量回测图）与 `output/p3/`（P3 八账户，2026-09 起运营）。
  `output/*.csv` 与 `output/*.png` 被 gitignore 不入库；**例外（入库跟踪）**：
  `output/r5/` 下 R5 运营产物——5 张每日图（`daily_nav_aum*.png` ×4 + `daily_gains_live.png` ×1，
  `daily_update.py --chart` 刷新，README 靠上位置引用）+ 12 个运营 CSV（`daily_nav_aum*.csv`
  每日净值 / `monthly_funds_aum*.csv` 月度资金 / `monthly_holdings_aum*.csv` 月度持仓快照）+
  年度场景 CSV/图 + `ledger_aum*.json` 账本；`output/p3/ledger_p3_aum*.json` 账本也入库，
  P3 每日/月度 CSV 不入库。

---

## 2.5 配置系统（Round 34，全量配置化）

**所有可配置项集中在 YAML 文件，代码不 hardcode 配置值**：

- **默认配置**：`config/default.yaml`（全量，含冻结参数基准；缺失/字段缺失 → 报错，无兜底便于查 bug）；段结构：paths / **r5**（冻结：R5 公式窗口 + 四账户 + 分段窗口）/ **p3**（冻结：P3 参数 + 八账户）/ costs（冻结，共享费率）/ **fetch**（5 个抓取脚本的参数、数据窗口与路径，fetch 路径键同 paths 一样相对仓库根解析为绝对）/ **monitor**（factor_health 基准与运营期窗口）；
- **自定义配置**：`--config config/custom.yaml`（CLI）或 `QUANT_CONFIG` 环境变量 → **深合并覆盖 default.yaml**（同 key 覆盖，缺失项继承 default）；指定文件不存在 → 报错；
- **代码读取**：函数内 `quant_trading_01.config.get_config()` 惰性单例（方案二）；**全仓无模块级配置读取**（二次审计后，7 处模块级全部下沉函数内）；各脚本 `main()` 里 `load_config(args.config)` 建立单例，之后函数内生效；被 import 的脚本用默认配置；
- **冻结参数校验**：配置值 ≠ default.yaml 冻结基准 → 打印醒目警告（不阻止），提示需预注册；
- **支持格式**：YAML（pyyaml）；
- **代价**：CLI 参数（如 `--slip`）默认取配置值（`--slip` 显式指定时覆盖配置）；各脚本均可 `--config` 指定。

## 3. 核心脚本一览

| 脚本 | 用途 | 典型耗时 |
|---|---|---|
| `scripts/r5/paper_trade.py` | PaperPortfolio 引擎 + 历史全口径回放（`replay`/`replay_w`/`init`）+ `r5_rebalances` 信号；`--slip` 默认 15bp（Round 33 三口径统一，0 回退纯因子口径） | 单个 share 级回放 ~8-15 分钟 |
| `scripts/r5/paper_live.py` | **模拟盘四账户**：`init` 建仓 / `step` 月调仓 / `mark` 每日涨幅 / `report` 报告；`--slip` 滑点默认 15bp（Round 32 账本真实化，0 回退旧口径） | mark 数百只 ~1-2 分钟/账户 |
| `scripts/p3/paper_live_p3.py` | **P3 模拟盘八账户**（3万~600万）：`init`/`step`/`mark`/`report`；策略参数与账户列表读 `config/default.yaml` 的 `p3` 段（冻结）；账本 `output/p3/` | mark 50 只 ~2 分钟/账户 |
| `scripts/r5/scenario_ytd.py` | 年度场景回放（`--start`/`--end`），输出 daily_nav/monthly_funds | 同回放 |
| `scripts/r5/plot_daily_gains.py` | 四账户每日图：每账户 NAV 单图 `daily_nav_aum{tag}.png` ×4 + 累计净值/每日涨幅%双面板 `daily_gains_live.png`；`--prefix/--title` 年度场景、`--live` 建仓以来实时场景（读无前缀 daily_nav_aum*.csv） | 秒级 |
| `scripts/fetch_full_market.py` | 全市场数据更新（按 code 增量，新 code 才抓） | 分钟~小时 |
| `scripts/fetch_daily_incremental.py` | **日常收盘后只补当日 K 线**（`<日期>` 参数，按已有 code 补指定日） | 全市场 ~20-30 分钟 |
| `scripts/fetch_stock_basic.py` | **宇宙清单（stock_basic+universe）低频刷新**（季度/半年，src/fundamental 迁移，config paths 段） | baostock 全表, 低频 |
| `archive/experiments/` | 已结束探索归档（R12-16 集中版/满仓/行业中性/20万/拥挤度、R21-47 筛选/组合/低价股全链），见 `archive/INDEX.md` | — |
| `scripts/archive_experiment.py` | **探索归档工具**：已结束探索 → `archive/experiments/`（依赖闭包/import改写/git mv/索引更新/校验回滚，`--dry-run` 预览） | 秒级 |
| `scripts/r5/factor_health.py` | **R5 因子失效监控**（Round 18）：逐月末 RankIC（Amihud/动量/合成分，全池+行业内），对比历史基准出状态灯，只读不操作；`--chart` 画 μ±2σ 带 | ~1-3 分钟 |

---

## 4. 冻结参数（**改前必须预注册 + 用户批准**）

> **Round 34 配置化后**：冻结参数已迁移到 `config/default.yaml` 的 `r5`/`p3`/`costs` 段（即冻结基准）；
> 自定义配置覆盖冻结值会触发醒目警告（见 §2.5）。改冻结参数仍需预注册 + 用户批准。

```
佣金 万1.5(单笔最低5元, COMM_MIN=5.0) · 印花税 万5(仅卖出) · 过户费 万0.1(双边)
红利税 10%(DIV_TAX, 保守) · 现金无息
MIN_N=50(池<50跳过月) · MIN_IND=5(行业<5剔除) · LIMIT_THR=0.098(涨停阈值)
R5 公式窗口(config r5 段, 冻结): Amihud 21/15/×1e6 · 动量 21/250 · F4 5日均成交额 · seasoning 375 · 5分位取前1/5
START=2013-06-01 · 信号=月末T → 执行=T+1收盘 · 等权575 前20% · 1手=100股
三因子打分权重 = 0.40 Amihud : 0.10 动量 : 0.50 F4低成交额 (Round 38 样本外验证采纳, 和=1)
```

- **R5 等权575 是用户明确要求"策略不变"的版本**——不经预注册讨论，不要改任何选股/打分/参数。
- 成本/费率（佣金/印花/过户/红利税/滑点）在 `config/default.yaml` 的 `costs` 段（冻结基准）；
  `paper_trade`/`paper_live` 通过 `_cfg().costs.*` 读取（Round 34 已配置化，不再硬编码）。
- 打分权重（0.40:0.10:0.50）是 2026-09-18 用户批准落地的（Round 38 三因子样本外验证：
  训练段 2014-21 选权 w\*=A0.40/M0.10/F40.50 → 验证段 2022-26 超额差 +2.30pp + 双侧高原
  判据全过；取代原 0.85:0.15 二因子，原 2026-09-10 批准记录作废）——**再次调整须重走预注册**。

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
     `from scripts.fetch_daily_incremental import update_date`、
     `from scripts.r5.paper_live import mark`（省 4 次进程冷启动 + 4 次字体缓存，治发热）；
   - 被导入的脚本须满足：逻辑放函数、`main()` 只做 argparse 壳、**模块级不读 sys.argv**
     （否则 import 时读错调用方参数）；
   - subprocess 只留给：跨环境/跨语言、独立一次性工具、需超时强杀的场景；
   - 退出码语义用函数返回值（如 update_date 返回 0/3）+ try/except 保留，不靠进程码。
7. **探索结束必须归档（不手删、不留在 scripts/）**：
   - 流程：plan 写 §0 结论 → 跑 `python scripts/archive_experiment.py <脚本或单元>`
     （依赖闭包/import改写/git mv/输出入库/INDEX 更新/校验，`--dry-run` 先预览）
     → `archive/INDEX.md` 自动登记；
   - `scripts/` 只留生产链 + 共享基座（`reversal_factor.py`/`dividend_factor.py` 被
     `paper_live`/`paper_trade` 依赖，**脚本留位**，其 plan/输出照常归档）；
   - 归档单元自包含（脚本闭包 + plan + 结论输出 csv/png），结论输出随单元入库
     （`archive/**` 不受 `output/*.csv` gitignore 影响）；复现命令见单元 README；
   - 归档一律 `git mv` 保留历史，**禁止 rm/cp 搬移**；归档后须 `py_compile`/import 校验通过。

---

## 6. 模拟盘运营（四账户）

- 账户：`60万/100万/300万/600万`，账本 `output/r5/ledger_aum{60w,100w,300w,600w}.json`。
- **建仓 2026-09-01（信号 2026-08-31）**。注意：**生产账户跑的是"三因子 575 等权"**
  （Round 38 权重 Amihud 0.40/动量 0.10/F4 0.50，2026-09-18 落地重建账本），
  小账户因 1手 约束天然退化（60万 只持有 307 只、58% 现金）——**这是现状，不是 bug**。
- 每日：**一键 `python scripts/r5/daily_update.py`**（自动判断最新交易日 → 缺则补当日
  行情 → 四账户 mark → 输出"账户/本金/最新NAV/当日涨幅/盈亏(元)/盈亏率/建仓日NAV"总表；
  数据源未发布当天会自动探测跳过并以最新已有数据为准；`--table` 只读表不重跑；
  `--chart` mark 后自动出建仓以来每日图（NAV 单图 `daily_nav_aum{tag}.png` ×4 + 双面板 `daily_gains_live.png`，均在 `output/r5/`）；
  单独出图可跑 `python scripts/r5/plot_daily_gains.py --live`）。
  手动分解：`python scripts/fetch_daily_incremental.py <日期>` → 四账户各跑一次 `python scripts/r5/paper_live.py mark --aum NNNN`。
- 每月：`python scripts/r5/paper_live.py step`（自动推进四账户调仓）+ `report`。
- **对账不变量**（每次 step 后抽查）：① 期末净值=现金+持仓；② 期末≈期初−费用(<1%)；
  ③ 月涨幅连乘=累计。
- **"今日涨幅"以数据源最新 K 线为准**，不是系统日历——先 `date` 确认今天，再查
  `full_daily.parquet` 最大日期，数据没出就等数据出了再 mark。

### P3 模拟盘运营（低价股，八账户，2026-09-01 建仓）

- 策略 **P3** = 真实价 3.0-4.0 元 + 近 3 年扣非为正 + 负债率<70% + 流动性 + 分红 + 等权月频
  （Round 41-47 预注册定稿，参数冻结在 `config/default.yaml` 的 `p3` 段，**改动须预注册**）；
  账本 `output/p3/ledger_p3_aum{3w..600w}.json`，每日/月度 CSV 同目录（不入库）。
- 账户：`3万/10万/20万/30万/60万/100万/300万/600万`（`p3.aum_list`，小账户 1 手约束天然退化）。
- 每日：**一键 `python scripts/p3/daily_update_p3.py`**（自动补行情 → 八账户 mark →
  总表；`--chart` 出图；`--table` 只读总表）——分解：`python scripts/p3/paper_live_p3.py mark`；
  每月：`python scripts/p3/paper_live_p3.py step`；报告：`... report`。
- 对账不变量同 R5：期末净值=现金+持仓；期末≈期初−费用；月涨幅连乘=累计。

---

## 7. 资金规模结论（已实测，别推翻）

| 资金 | 可行口径 | 超额 | 结论 |
|---|---|---|---|
| <20万 | — | — | 不可行 |
| 20万 | 前150+补买 | +1.86pp | 不建议（费用吃光） |
| **60万** | **前100+满仓补买** | +3.4~3.6pp | 绝对可行下限 |
| **300万** | 原版 575 等权 | **+7.29pp**（0.85口径；旧0.5口径 +4.43pp） | 最优起点 |
| 600万 | 原版满配 | **+7.67pp**（0.85口径；旧0.5口径 +4.72pp） | 效率饱和 |

> 注：300万/600万 超额为 Round 29 权重调整（Amihud 0.85:动量 0.15）后 0.85+阻塞口径重跑值
> （2026-09-10）；60万 前100+补买 为 Round 13 集中版实验口径（未在 0.85 下重测，方向性结论不变）。

**风控五轮总收束（R4b/4c/4d/6/16）**：熔断/均线/双熔断/拥挤度择时都压不住回撤且牺牲超额——
`−50% 级回撤是 Amihud+满仓小盘的市场定价，扛住+深坑不割肉是唯一验证可行的应对`。

---

## 8. 禁忌清单

- ✅ **每次改动 Python 代码后必须格式化**：`uv run ruff format .` + `uv run ruff check .`
  （ruff 默认格式风格，已配 pyproject；提交前 check 必须 0 错误；pre-commit 可选装 `.pre-commit-config.yaml`）；
- ❌ 不跑多次重回测去"试"：share 级回放 10-20 分钟，**先预注册、后台跑、不重复**；
- ❌ 不改冻结参数 / 不改 R5 选股逻辑；
- ❌ 不提交 `output/*.csv`、`output/*.png`（gitignored，可再生成）——**仅当前四账户运营产物豁免
  （5 张每日图 + 12 个运营 CSV：daily_nav_aum*/monthly_funds_aum*/monthly_holdings_aum*）**，
  每日 mark/每月 step 后须随 commit 更新；
- ❌ 不把其他策略版本写进 `docs/strategy_operations_handbook.md`（它只维护 R5）；
- ❌ 不凭文件时间戳断"今天几号"（先 `date`）；
- ❌ 不编造回测/账本数字——拿不到就如实说"数据未出/需跑"；
- ❌ **测试/验证代码绝不直接读写真实数据文件**（曾因 `shutil.move` 用只含 date/code
  的副本覆盖 full_daily.parquet，导致全部历史价格丢失）——先在 /tmp 副本或备份上测，
  测完恢复，再碰真实文件；
- ✅ **临时/验证脚本统一放项目内 `tmp/` 文件夹**（不入库，gitignore）：跑数据探查、
  一次性对照实验、临时验证时写 `tmp/xxx.py` 并 `python tmp/xxx.py` 执行，**不要丢系统
  /tmp 或散落仓库根目录**（避免跨会话丢失/污染工作区/误提交）；`tmp/` 已在 .gitignore；
  数据副本/备份仍可放系统 /tmp（与脚本分开）。
- ✅ **目录布局（Round 40 对齐 exploration-project skill）**：`src/quant_trading_01/` = 共享框架包（`config`/`data_io`/`data_loader`/`dividend_factor`/`reversal_factor`，勿删）；`scripts/` = 可执行脚本；旧 `research/` 已由 `git mv` 拆分迁移。历史：Round 34 曾删除旧 `src/`（`stock_basic` 宇宙刷新 → `scripts/fetch_stock_basic.py`，季度低频，运营手册 §349；旧测试引擎 → `tests/legacy_backtest.py`+`tests/legacy_costs.py`，勿删）；`src/quant_trading_01/data_loader.py` 供 `dividend_factor` 基准 lazy 导入与归档实验复现（`from quant_trading_01.data_loader import ...`）。
- ⚠️ **baostock 服务不稳定时不要连续重试**（全历史大结果集 `rs.next()` 会挂起、
  持续连接会被拒"用户未登录"）——停止猛打、等待恢复再跑；代码优先用本地代码清单
  （`query_stock_basic` 在本环境会挂起）。
