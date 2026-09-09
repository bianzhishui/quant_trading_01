# 探索归档能力建设方案（预注册）

> 状态：**已实施（2026-09-09），20 个单元全部归档，见 §0**。本文档是"怎么归档"的
> 规则定死稿；归档动作由 `research/archive_experiment.py` 自动化执行（见 §8）。
> 与 AGENTS.md 纪律一致：先预注册、后实施。

## 0. 实施结果归档（2026-09-09）

**判定：通过。** 20/20 归档单元落地，`research/` 仅剩生产链 15 个白名单脚本 + 工具本身，
`archive/INDEX.md` 覆盖全部单元，生产链 import 冒烟通过，git 历史经 `--follow` 验证保留。

### 0.1 归档批次（4 个 commit）

| commit | 内容 |
|---|---|
| `fc121b9` | 试点 3 单元：`round16_crowding_timing`（❌）、`reversal_short_term`（❌，基座留位）、`round12_15_concentrated`（⏸，闭包合并 4 脚本 + 3 处 import 改写） |
| `d6c9f0c` | 风控系列：`round04_risk_breakers`（4/4b/4c/4d 合并）+ `round06_r5_ma` |
| `743e6f9` | 主策略系列：`screen01`/`screen02`/`round03`/`round05`/`round07`/`round08`/`round09`/`round11` |
| `5c5xx`（收尾） | 独立方向：`dividend_factor`（基座留位）/`convertible_double_low`/`ew_base`/`etf_exploration`/`weekday_effect`/`grid_demo`/`yearly_breakdown` + AGENTS.md/README 更新 |

### 0.2 与方案的偏差（如实记录）

1. **单元合并**：`round4/4b/4c/4d` 合并为 `round04_risk_breakers`（同一风控系列连续迭代，
   无 import 链但语义一体）；`round12~15` 由依赖闭包强制合并（`round13→12`、`round14→13`、
   `round15→12/13`），且 3 处闭包内 import 改写为 `research.X → X`（同目录可导入，
   已冒烟验证 `r5_topN_rebalances` 可用）。最终 **20 个单元**（方案预估 23，因合并减少）。
2. **输出归属**：初版按"单单元前缀"收集导致 `screen01` 抢走 `factor_corr_*_round2.csv`
   （属 screen02）——已改为**全局最长前缀**判定并归位（commit `743e6f9` 含修复）。
3. **.gitignore 无需例外**：核实 `output/*.csv`/`output/*.png` 规则仅匹配 `output/` 下文件，
   `archive/` 结论输出天然可入库，方案 §4 的 `!archive/` 例外不必要。
4. **校验口径**：归档脚本未逐一真跑全量回放（share 级 10-20 分钟/个，代价过高），
   以 `py_compile` + 静态依赖检查 + 生产链/闭包脚本 import 冒烟替代；复现命令见各单元 README。

### 0.3 判定标准自查（方案 §10）

- [x] `archive/INDEX.md` 覆盖 20 个单元，状态与结论齐全
- [x] 抽样校验（round12_15 闭包改写、round16、生产链）：py_compile 通过、import 链完整
- [x] 归档后 `research/` 仅剩白名单 15 + `archive_experiment.py`
- [x] 全程 git mv，`git log --follow` 历史保留（如 round16 脚本可追溯到 `864a224` 格式化 commit）
- [x] AGENTS.md（§3 表格 + §5.7 归档纪律）/ README（目录结构 + 探索表指向 INDEX）已更新

### 0.4 遗留

- 各归档单元的重跑真实验证留待需要时按 README 复现命令执行（数据依赖不变）。
- `etf_candidates.py`/`etf_lowvol_replica.py` 无独立 plan 文档（仅 `etf_momentum_plan.md`），
  结论摘要以 README 表为准。

## 1. 背景与动机

项目经 17+ 轮因子研究产生了大量**已结束的探索**，但探索的"结束"目前是隐式的：
plan 文档写了 §0 结论、README 手工维护探索历史表，却没有"归档"这个动作本身。由此：

1. **生产与探索混居**：`research/` 44 个脚本中约 26 个属于已结束探索，与
   `paper_live` / `daily_update` 等生产链无区分，新人/代理难以判断"哪些在服役"。
2. **结论产物不入库**：`output/*.csv` 与 `*.png` 整体 gitignore，探索的 summary/图
   只存在于工作区，换机器即失。
3. **无状态机**："探索中 / 已结束 / 已否决 / 已归档"无统一登记，README 表靠手工同步易漂移。

## 2. 目标与原则

| 原则 | 含义 |
|---|---|
| 可发现 | 总索引 `archive/INDEX.md` 一眼列出全部已归档探索：状态、结论、位置 |
| 可复现 | 归档单元自包含（脚本+plan+结论输出），import 依赖完整，可重跑 |
| 不污染生产 | 生产链与探索链物理分离（`research/` 只留生产 + 共享基座） |
| 不毁历史 | 全程 `git mv`，保留文件 git 历史 |
| 低成本 | 归档 = 一个命令（工具自动算依赖闭包、搬文件、更新索引、校验） |

## 3. 现状依赖图快照（2026-09-09 实测，归档规则的依据）

### 3.1 共享基座（被生产链依赖，**必须留位 `research/`**）

| 模块 | 被谁依赖 | 生产链用途 |
|---|---|---|
| `reversal_factor.py` | 22 个脚本 | `paper_live` 用 `ew_nav`；`paper_trade` 用 `build_pool, ew_nav` |
| `dividend_factor.py` | 19 个脚本 | `paper_trade` 用 `month_last_days, metrics` |
| `paper_trade.py` | 11 个脚本 | 回放引擎核心 |
| `data_io.py` | 13 个脚本 | 数据 IO 核心 |

> 结论：`reversal_factor.py` / `dividend_factor.py` 虽是探索产物，但已被升格为
> 共享库——**脚本留位，其 plan 文档与结论输出照常归档**，INDEX 中登记"留位原因"。

### 3.2 探索脚本间的 import 链（归档闭包规则）

```
factor_round13 ← factor_round12
factor_round14 ← factor_round13
factor_round15 ← factor_round12 + factor_round13
```

- 归档时**依赖闭包必须整体移动**：round13/14/15 与 round12 属于同一方向（集中度系列），
  工具按闭包自动合并为一个归档单元 `round12_15_concentrated/`。
- 其余探索脚本对基座/生产模块的 import（`from research.reversal_factor import …` 等）
  **移动后依然有效**：脚本以仓库根为 cwd 运行，`research/` 包路径不变。

## 4. 目录结构设计

```
research/                                # 只留生产链 + 共享基座（白名单见 §6）
archive/
  INDEX.md                               # 总索引登记表（格式见 §8）
  experiments/
    round03_combination/                 # 单元 = 一个已结束探索（或依赖闭包合并）
      README.md                          # 结论/判定/复现命令/数据依赖（工具生成）
      factor_round3_combination_plan.md  # 原 plan（含 §0 归档章节）
      factor_round3_combination.py       # 原脚本（git mv）
      factor_round3_summary.csv          # 结论型输出（入库，覆盖 gitignore）
      factor_round3.png
    round12_15_concentrated/             # 闭包合并示例
    reversal_short_term/                 # 基座脚本留位，但 plan+输出归档于此
    ...
```

- `.gitignore` 增加例外：`!archive/`（或 `!archive/**` 白名单规则），使归档单元的
  结论型输出（csv/png）**入库**。
- `output/` 保持运营产物（ledger/daily_nav/monthly_funds/daily_gains）不变。

## 5. 归档单元定义

一个归档单元 = `{README.md, plan 文档, 脚本(依赖闭包), 结论型输出}`。

**状态机**：

```
探索中（research/ 原位，plan 无 §0）
  → 已结束（plan 写入 §0 结论 + README 探索表登记）
  → 已归档（跑 archive_experiment.py：移入 archive/experiments/ + INDEX 登记）
```

**状态值**（写入 plan §0 与 INDEX）：`✅ 通过并入生产` / `❌ 已否决` / `🟡 部分通过` / `⏸ 搁置（无结论）`。

## 6. 候选归档清单（定死）

### 6.1 探索单元（26 个脚本 → 23 个单元，闭包合并后）

| 归档单元 | 脚本 | plan 文档 | 状态（README 判定） |
|---|---|---|---|
| `screen01_momentum` | factor_screen_round1.py | factor_screen_round1_plan.md | 🟡 部分通过 |
| `screen02_amihud` | factor_screen_round2.py | factor_screen_round2_plan.md | ✅ 通过并入 |
| `round03_combination` | factor_round3_combination.py | factor_round3_combination_plan.md | ✅ 通过并入 |
| `round04_*`（4 个） | factor_round4/4b/4c/4d.py | 对应 4 个 plan | 🟡/❌ 风控系列 |
| `round05_industry_neutral` | factor_round5.py | factor_round5_industry_neutral_plan.md | ✅ 通过并入 |
| `round06_r5_ma` | factor_round6.py | factor_round6_r5_ma_plan.md | ❌ 否决 |
| `round07_fullmarket` | factor_round7_fullmarket_validate.py | 对应 plan | ✅ 通过 |
| `round08_live_validation` | factor_round8_live_validation.py | 对应 plan | ✅ 通过 |
| `round09_holdings_count` | factor_round9_holdings_count.py | 对应 plan | （实验） |
| `round11_fullbuy` | factor_round11_fullbuy.py | factor_round11_fullbuy_plan.md | ❌ 否决 |
| `round12_15_concentrated` | round12+13+14+15 四脚本（闭包） | 对应 4 个 plan | ❌ 否决/不建议 |
| `round16_crowding_timing` | factor_round16_crowding_timing.py | 对应 plan | ❌ 否决（风控收束） |
| `reversal_short_term` | （脚本留位=基座） | reversal_factor_plan.md | ❌ 否决 |
| `dividend_factor` | （脚本留位=基座） | dividend_factor_plan.md | （实验） |
| `convertible_double_low` | convertible_double_low.py | convertible_double_low_plan.md | 独立方向 |
| `ew_base` | ew_base.py | ew_base_plan.md + ew_base_execution.md | 独立方向 |
| `etf_momentum` / `etf_lowvol_replica` / `etf_candidates` | 3 脚本 | etf_momentum_plan.md | 独立方向 |
| `weekday_effect` | weekday_effect.py | （无 plan） | 独立方向 |
| `grid_demo` | grid_demo.py | （无 plan） | 演示 |
| `yearly_breakdown` | yearly_breakdown.py | （无 plan） | 分析工具 |

### 6.2 永不归档白名单（生产链 + 共享基座，共 14 个脚本）

```
data_io.py · fetch_corporate_actions.py · fetch_daily_incremental.py ·
fetch_full_industry.py · fetch_full_market.py · fetch_round2_data.py ·
migrate_full_daily_partitions.py · paper_live.py · paper_trade.py ·
daily_update.py · plot_daily_gains.py · scenario_ytd.py · export_holdings.py ·
reversal_factor.py（基座） · dividend_factor.py（基座）
```

> 注：`factor_round10`（paper sim）与 `factor_round17`（基建）无独立脚本，不归档；
> `factor_round10_paper_sim_plan.md` 与 `factor_round17_delisted_plan.md` 留 docs/ 原位
> （前者是运营手册前身，后者是基建记录）。

### 6.3 输出归属映射规则

- 前缀匹配（有则搬入对应单元）：`factor_roundN_*`、`factor_screen_roundN_*`、
  `factor_corr_*`（→screen01）、`reversal_factor_*`（→reversal_short_term）、
  `dividend_factor*`（→dividend_factor）、`weekday_effect_*`、`etf_*`、
  `ew_base*`、`convertible_double_low*`。
- **不动**：`ledger_*`、`daily_nav_*`、`monthly_funds_*`、`daily_gains_*`、
  `paper_init_*`、`account_comparison*`、`strategy_holdings/`、`backtest/`。

## 7. 元数据格式（INDEX.md 登记表）

```markdown
| 单元 | 方向 | 状态 | 结论摘要 | 位置 | 归档日期 |
|---|---|---|---|---|---|
| round05_industry_neutral | R5 行业中性 | ✅ 通过并入 | 行业内 alpha 真实，升级为策略主体 | archive/experiments/round05_industry_neutral/ | 2026-09-XX |
| reversal_short_term | 短期反转 | ❌ 否决 | IC 不足 + 15bp 成本致命 | archive/experiments/reversal_short_term/ | 2026-09-XX |
```

每个单元 `README.md` 含：结论摘要、判定、复现命令（原运行方式）、数据依赖
（full_daily 等）、留位说明（基座时写"脚本留位原因：被生产链依赖"）。

## 8. 自动化工具规格：`research/archive_experiment.py`

```
用法: .venv/bin/python research/archive_experiment.py <单元名或脚本名> [--dry-run]
```

流程（全部原子、可 dry-run 预览）：
1. **解析依赖闭包**：grep 目标脚本的 `from research.X import`，递归展开，命中白名单
   （§6.2）即停；闭包内若有 round12~15 链 → 自动合并单元名并提示。
2. **git mv**：脚本 + 对应 plan 文档 → `archive/experiments/<unit>/`。
3. **搬结论输出**：按 §6.3 前缀匹配移动 csv/png，并 `git add`（依赖 `!archive/` 例外）。
4. **生成 README.md**：读 plan §0 结论摘要 + 判定 + 提取复现命令。
5. **更新 INDEX.md 与 README 探索表**：新增/标记该单元。
6. **校验**：`py_compile` 全部归档脚本 + import 冒烟（在仓库根跑
   `python -c "import archive.experiments.<unit>.<mod>"` 形态或直接试运行 dry 路径），
   失败则回滚（git checkout + 反向移动）并报错。
7. `--dry-run` 只打印将执行的动作清单，不落盘。

## 9. 落地步骤（分批 commit）

1. `docs/` 本方案定稿（本文件）→ 用户批准。
2. 建 `archive/` 骨架 + INDEX.md 模板 + `.gitignore` 例外 + 写 `archive_experiment.py`。
3. **试点**：归档 2 个单元（推荐 `round16_crowding_timing`、`reversal_short_term`），
   校验可重跑 + git 历史保留，结果回写本文档 §0。
4. **批量**：按 §6.1 分组归档其余单元（每批一个 commit：风控系列 / R5 系列 /
   独立方向系列）。
5. 更新 `AGENTS.md`（新增纪律：探索结束 → 写 §0 → 跑归档工具 → 更新 INDEX）与 README
   （探索历史表改为指向 INDEX.md）。

## 10. 判定标准（"归档能力上线成功"）

- [ ] `archive/INDEX.md` 覆盖 §6.1 全部 23 个单元，状态与结论齐全
- [ ] 随机抽 3 个归档单元：`py_compile` 通过、import 链完整、可重跑（或记录明确的重跑命令）
- [ ] 归档后 `research/` 仅剩白名单 15 个脚本 + 进行中探索
- [ ] 全程 git mv，抽查 `git log --follow` 历史保留
- [ ] AGENTS.md / README 已更新，归档动作可被代理按文档执行

## 11. 风险与边界

| 风险 | 应对 |
|---|---|
| import 断裂 | 依赖闭包 + py_compile/import 校验 + 试点先行；失败自动回滚 |
| gitignore 吞掉归档输出 | `!archive/` 例外 + 工具 `git add` 显式加入 |
| 基座脚本（reversal/dividend）被误当探索删掉 | 白名单硬编码 + 工具拒绝归档白名单文件 |
| README 探索表漂移 | 工具同步更新；表头注明"由归档工具维护" |
| 归档后重跑依赖数据（data/round2 等） | README 数据依赖字段写明；数据文件一律不动 |

## 12. 不纳入本方案（边界外）

- 运营产物（ledger/daily_nav/monthly_funds）不归档不移动；
- `data/` 任何文件不归档不移动；
- `src/`、`tests/` 不移动（`src/fundamental.py` 生成生产宇宙清单 stock_basic.parquet、`src/data_loader.py` 被生产基座依赖、`src/backtest.py`+`costs.py` 被单元测试保护）；
- 不删除任何历史文件，只做 git mv（历史归档），不做物理删除。
- **后续变更**：`strategies/` 与 `run_backtest.py`（根目录演示入口）已于 2026-09-09 演示层清理时
  **直接删除**（非归档；不影响生产链/研究链/pytest，README 快速开始与 .vscode/launch.json 已同步改为
  运营入口）。
