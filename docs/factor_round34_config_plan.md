# Round 34 全量配置化（YAML 配置，函数内读取，--config 指定）· 预注册

> 状态：**已实施（2026-09-13），见 §0**。
> **诚实标注：本 plan 为实施后补写（补正流程）**——配置化改造在写此文档前已完成，但设计决策
> 已由用户逐个拍板（A1/B2/B3/C1/Q1/Q2 见 §2.5），代码与验证均已就绪。补写以完成预注册归档。
> 与 AGENTS.md 纪律一致：任何参数/架构改动需预注册；本轮为架构/基建轮（非策略变体），
> 默认配置 = 冻结值，策略选股/打分/参数零改动。

## 0. 实施结果归档（2026-09-13）

**判定：通过（5/5）。** 全量配置化完成：所有可配置项集中 YAML，代码不 hardcode；默认行为不变（回归验证 +7.63% 与 Round 33 一致）；`--config` 自定义配置生效；冻结参数偏离警告触发。

### 0.1 交付清单

- **`config/default.yaml`**：全量配置（paths / strategy 冻结参数 / costs 费率 / accounts 账户），缺失报错无兜底；
- **`research/config.py`**：pyyaml loader + 深合并覆盖 + 冻结参数偏离警告 + `get_config()` 惰性单例；
- **8 个脚本改造**（reversal_factor / paper_trade / paper_live / factor_health / export_holdings / plot_daily_gains / scenario_ytd / config）：模块级配置常量 → 函数内 `get_config()` 读取；main() 加 `--config`；
- **`config/custom.yaml.example`**：自定义配置示例（注释掉，不入库 custom）；
- **AGENTS.md**：新增 §2.5 配置系统说明 + §4 冻结参数迁移说明；
- **launch.json**：加自定义配置运行示例（17 个配置）；
- **补全轮（09-14，提交 b197fb4）**：data_io（paths 段）/ dividend_factor / daily_update 接入 config（原 §6"不改 data_io"边界解除）；
- **fetch 波（09-14，本提交）**：新增 `fetch:` 配置段（corporate_actions / daily_incremental / full_industry / full_market / round2_data）+ 5 个抓取脚本（含 fetch_round2_data）接入 config，全部改**函数内 `get_config()` 读取**（对齐 §2.6 模式）；config.py `_resolve_paths` 扩展为 paths 全键 + fetch 路径键统一相对仓库根解析为绝对（CWD 无关）。

### 0.2 验证（方案 §3 判定自查）

| # | 判据 | 结果 |
|---|---|---|
| ① 默认行为不变 | replay_w 300万 = +7.63%、费用 144.6万=3.64%/年（与 Round 33 完全一致） | ✅ |
| ② ruff/pytest/import | ruff 0 错 + pytest 4 passed + 全部脚本 import 通过 | ✅ |
| ③ --config 生效 | `--config tmp/custom_slip.yaml`（35bp）→ +6.10%、费用 6.54%/年（Round 8 口径数字） | ✅ |
| ④ 冻结警告 | `--config` 改 amihud_w=0.5 → 醒目警告"偏离冻结参数" | ✅ |
| ⑤ 指定文件不存在 → 报错 | `load_config('config/nonexist.yaml')` → FileNotFoundError | ✅ |
| ⑥ 运营链冒烟 | report + mark 300万 正常（NAV 291.81万、mark 到 09-11） | ✅ |
| ⑦ 抓取链回归（本提交） | 5 个 fetch 脚本 ruff 0 错 + import 通过；fetch 路径键全部解析为绝对且值与原硬编码一致 | ✅ |
| ⑧ 运营链回归修复（本提交） | 修复 Round 34 引入的 `aum` 双重前缀 bug（daily_update/plot_daily_gains tag 语义）+ plot_daily_gains OUT 未包 Path；`--table` / `--live` / `--prefix 20250101` 冒烟全通 | ✅ |
| ⑨ 二次配置化审计（本提交） | 硬编码清零：fetch 数据窗口（corporate_actions/full_market/round2_data 各 start/end）、fetch.live.fac_end、monitor 段、export_holdings stock_basic、factor_health OUT、dividend_factor png、fetch_round2_data universe、paper_live live 因子限流参数全部入 config；ruff/pytest/17模块 import/冒烟全通 | ✅ |

### 0.3 遗留 / 已知边界（诚实记录）

1. **CLI 参数 vs 配置优先级**：`--slip` 显式指定时覆盖配置；未指定时默认取配置值（load_config 后填充）。其他 CLI（--aum/--start）同理，均为"显式覆盖"语义；
2. **被 import 的脚本用默认配置**：paper_live import paper_trade 时，paper_trade 的配置为默认（default.yaml），只有入口脚本 main() 的 --config 生效——符合"各模块自负责配置"的设计；
3. **缺失报错无兜底**：default.yaml 缺失或字段缺失 → 报错（用户拍板 Q2，便于查 bug）。副作用：配置项拼错会直接报错而非静默；
4. **仅支持 YAML**（用户拍板先只支持 yaml + pyyaml）；JSON/TOML 为扩展预留（loader 结构可扩展，本轮不做）；
5. **费率等冻结参数在 default.yaml 中即冻结基准**，自定义覆盖触发警告（A1 折中：灵活 + 纪律）；
6. **fetch 脚本无 `--config` CLI**（本提交）：corporate_actions / full_industry / full_market 为独立入口脚本，未加 argparse `--config`——覆盖走 `QUANT_CONFIG` 环境变量（load_config 支持）或改 default.yaml；`fetch_daily_incremental` 被 daily_update 导入，函数内读取使其响应父进程已加载配置；
7. **回归修复记录**（本提交，检查"执行正常"时发现）：b62138b/b197fb4 把 tag 从 `"60w"` 改为 `"aum60w"`，与 `daily_nav_aum{tag}` 模板叠加 → `daily_nav_aumaum60w.csv`（daily_update `--table`、plot_daily_gains `--live/--prefix` 均受影响），且 plot_daily_gains 的 OUT 未包 `Path()`（config 解析后为 str，`OUT / "x.png"` 崩溃）——均已修复并验证（§0.2 ⑧）；
8. **二次配置化审计补全**（本提交，§0.2 ⑨）：新增 `fetch.*.start/end` 数据窗口、`fetch.live.fac_end`、`monitor` 段；清 export_holdings / factor_health / dividend_factor / fetch_round2_data 硬编码路径。**已知边界**：① R5 生产公式窗口（21/250/375 回看、5 分位）为冻结常量、刻意 hardcode 于信号路径（改需预注册），config 的 `lookback`/`n_q` 仅供 reversal_factor 探索用；② archive_experiment 工具按设计硬编码 `output/`（仓库布局约定）；③ fetch_daily_incremental 无参默认日期是每次运行的 CLI 入参（非配置值）。

### 0.4 补全轮与 fetch 波记录（2026-09-14）

- **补全轮（提交 b197fb4）**：data_io（paths 段）/ dividend_factor / daily_update 接入 config；
- **fetch 波（本提交）**：`fetch:` 配置段 + 5 个抓取脚本（corporate_actions / daily_incremental / full_industry / full_market / fetch_round2_data）接入；脚本全部**函数内 `get_config()` 读取**；`round2_data.out_dir` 确认保留并接入 fetch_round2_data（其在 archive 白名单，留位生产）；删除了无脚本读取的死配置键（corporate_actions.src / full_industry.src）；
- **路径绝对化**：config.py `_resolve_paths` 现解析 paths 全键 + fetch 路径键，统一相对仓库根 → 绝对，CWD 无关；
- **回归修复**：`aum` 双重前缀（daily_update / plot_daily_gains tag）+ plot_daily_gains OUT 未包 Path（详见 §0.3 7）；
- **二次配置化审计**：硬编码值清零——fetch 数据窗口（corporate_actions/full_market/round2_data 各 start/end）、fetch.live.fac_end、monitor 段（factor_health 基准/运营期）、export_holdings stock_basic、factor_health OUT、dividend_factor png、fetch_round2_data universe、paper_live live 因子限流参数全部入 config（详见 §0.3 8）；
- **诚实边界**：R5 公式窗口（21/250/375/5）为冻结常量刻意 hardcode（§0.3 8①）；`--config` CLI 仅 paper_trade/paper_live 有，其余脚本覆盖走 `QUANT_CONFIG` 环境变量（`get_config()` 惰性加载默认即读 env）；
- **验证**：ruff 全仓 0 错 + pytest 4 passed + 17 个 research 模块 import 全过 + `daily_update --table` / `paper_live report` / `plot_daily_gains --live` / `--prefix 20250101` 冒烟全通（§0.2 ⑦⑧⑨）。

## 1. 背景与动机

参数散落各脚本 + 重复定义：
- `SLIP_DEFAULT`（paper_trade / paper_live 各一份 15bp）
- `AUM_LIST`（scenario_ytd / paper_live / plot_daily_gains 各一份）
- 路径、费率、冻结参数（MIN_N/MIN_IND/AMIHUD_W/LIMIT_THR/START 等）分散在 paper_trade / reversal_factor / data_io

目标：**全量配置化**——所有可配置项集中在 YAML，代码不 hardcode，执行时可指定配置文件（换参数不改代码）。

## 2. 规则（定死）

### 2.1 格式与库
- 仅 YAML（pyyaml≥6.0）；JSON/TOML 扩展预留（本轮不做）。

### 2.2 加载规则
```
1. 始终加载 config/default.yaml（基底，全量，权威；缺失 → 报错，无兜底）
2. 若指定 --config <file>（CLI）或 QUANT_CONFIG 环境变量 → 深合并覆盖 default.yaml
   （同 key 覆盖，缺失项继承 default）
3. 指定文件不存在 → 报错退出
4. 代码不 hardcode 配置值；函数内 get_config() 惰性单例读取（方案二）
```

### 2.3 配置指定方式（优先级）
```
CLI --config > QUANT_CONFIG 环境变量 > 无（用 default.yaml）
```

### 2.4 配置项缺失行为
- default.yaml 缺失 / 字段缺失 / 指定文件不存在 → **报错**（Q1 B / Q2 无兜底）

### 2.5 用户拍板决策（记录）
| 决策 | 选择 |
|---|---|
| A1 冻结参数抽不抽 | **抽**（+ default.yaml 即冻结基准，偏离警告） |
| B2 CLI vs 配置优先级 | **CLI 显式参数覆盖配置** |
| B3 配置缺失项 | **报错无兜底**（用户后续 Q2 更新为更严格） |
| C1 冻结偏离校验 | **醒目警告 + 继续跑** |
| Q1 指定文件不存在 | **报错** |
| Q2 代码内兜底 | **不要兜底**（default.yaml 缺失即报错，便于查 bug） |

### 2.6 代码改造模式（方案二）
- 模块级配置常量 → 函数内 `config.get_config()` 读取（每次实时取单例）；
- main() 里 `load_config(args.config)` 建立单例，之后函数内生效；
- 被 import 的脚本（未走 main）首次 get_config() 用默认 default.yaml。

## 3. 判定（定死）

| # | 判据 |
|---|---|
| ① 默认行为不变 | 默认配置跑出的结果与改造前完全一致（replay_w 300万 = +7.63%） |
| ② 代码质量 | ruff 0 错 + pytest 4 passed + 全部脚本 import 通过 |
| ③ --config 生效 | 指定文件覆盖 default（改滑点 → 超额/费用变化符合 Round 8 口径） |
| ④ 冻结警告 | 配置偏离冻结基准 → 醒目警告 |
| ⑤ 报错语义 | default 缺失 / 指定文件不存在 → 报错退出 |
| ⑥ 运营链 | report/mark 冒烟正常（不破坏运营） |

判定 = ①②③④⑤⑥ 全过 → **上线**。

## 4. 诚实风险

1. **CLI 与配置双来源**：`--slip` 等 CLI 参数与配置值并存，优先级为"显式覆盖"——文档需写清，避免混淆；
2. **被 import 脚本用默认**：非入口脚本的配置不响应入口的 --config——符合设计但需知晓；
3. **缺失报错无兜底**：配置项拼错即报错（防呆 vs 严格权衡，用户选择严格）；
4. **本轮仅 YAML**：JSON/TOML 扩展预留但未实现，后续如需再加 loader 分支；
5. **这不改策略**：默认配置=冻结值，策略选股/打分/参数零改动；配置化只是"换参数的方式变了，值没变"。

## 5. 实施顺序

1. 本方案定稿 → 用户拍板设计决策（A1/B2/B3/C1/Q1/Q2）→ 用户批准；
2. pyproject.toml 加 pyyaml + uv sync；
3. 写 config/default.yaml + research/config.py；
4. 逐脚本改造（函数内读取 + main 加 --config）；
5. 验证（§3 判定）+ 回归（默认行为不变）；
6. 结果归档 §0 + AGENTS.md/launch.json 更新 + commit。
> 注：实施已在补写本文档前完成（流程补正），上述顺序为应然流程。

## 6. 边界外

- ❌ 不改 R5 选股/打分/参数（默认配置=冻结值）；不改冻结参数语义（改仍需预注册）；
- ❌ 本轮不做 JSON/TOML 支持（仅 YAML，扩展预留）；
- ❌ 不做配置热加载/多环境（单文件 + 覆盖，够用）；
- ⚠️ data_io 原计划"不改路径来源"（遗留项）→ **补全轮（09-14，b197fb4）已接入 config paths 段**，该边界解除，见 §0.4。
