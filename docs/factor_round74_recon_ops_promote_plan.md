# Round 74 运营对账脚本正式化（`tmp/recon_ops.py` → `scripts/recon_ops.py`）· 预注册

> 状态：**已预注册 2026-10-10 / 实施中**
> 触发：用户指出——"这个对账不是运营中所需要的吗？为什么在 tmp 目录下？"
> **用户是对的**：手册 §9.1 明确要求"每次 step 后抽查三不变量"，而它覆盖 11 个账户、
> 每次调仓/每日运营都要跑，属**运营工具**，却被我当初当一次性验证脚本丢进 `tmp/`（gitignore）。

---

## 1. 问题

`tmp/recon_ops.py` 实际承担的是**长期运营职责**：

- 手册 §9.1「三个对账不变量」+ P3 手册 §对账不变量，都要求**每次 step 后抽查**；
- 它已**真实抓出 4 个问题**（R64 基准失准、R70 建仓行遗留、费用跨表口径、step 误报）；
- 但 `tmp/` 被 gitignore → **不入库、不随仓库分发、无测试、不在手册里**，换个环境就没了。

结论：应提升为正式脚本，配置化、可 `--config`、带测试、写进手册。

---

## 2. 规则（定死）

1. `git mv` 等价的就地提升：`tmp/recon_ops.py` → **`scripts/recon_ops.py`**（顶层共享，
   因为它同时覆盖 R5 与 P3）；
2. `main()` 改为 **argparse 壳**（`--config`、`--strat {all,r5,p3}`），
   **模块级不读配置/`sys.argv`**（AGENTS §5.6 对"被导入脚本"的要求）；
3. 账户列表与输出目录**全部读配置**（`cfg.r5.aum_list` / `cfg.p3.aum_list` /
   `cfg.r5.out_dir` / `cfg.p3.out_dir`）——**不硬编码任何账户标签**；
4. **只读**：不得写任何文件（含不新建、不改 mtime）；
5. 退出码语义保留：`0`=全过，`1`=有不变量未通过；
6. 手册补一行命令：`strategy_operations_handbook.md` §9.1 与
   `p3_operations_handbook.md` 对账不变量处。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **T1 配置化** | 源码中**无账户标签字面量**（如 `"60w"`）；账户列表取自 `cfg.*.aum_list`（结构断言） | 换账户/加账户不需改代码 |
| **T2 行为等价** | 对当前 11 个账户，新脚本输出与 `tmp/` 版**逐字节一致**；退出码同为 0 | 提升不改判据 |
| **T3 判别力自证** | 在 tmp_path 造假数据：**好账户 → 各不变量 ✅**；**坏账户（净值≠现金+持仓）→ 必有 ❌ 且退出码 1** | 判据有判别力 |
| **T4 只读** | 跑一次真实对账后，被读文件 **mtime 全部不变**、目录无新增文件 | 运营工具不得污染产物 |
| **T5 `--strat` 生效** | `--strat r5` 只跑 R5 四账户，`--strat p3` 只跑 P3 七账户 | 便于分策略抽查 |
| **T6 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **被判据覆盖不到的**：容差常量（`TOL_ABS=1.0` 等）本轮不动——它们是既有口径，
   调参需另开预注册；
2. **不纳入 P3 已退役的 3 万账户**：`cfg.p3.aum_list` 本就不含它（现状，如实记录）；
3. **`tmp/recon_ops.py` 提升后删除**（避免两份分叉）；`tmp/` 内其他脚本不动。

---

## 5. 非目标

- 不把对账塞进 `daily_update.py`（保持单一职责，命令行独立调用）；
- 不改任何不变量判据/容差。

---

## 6. 实施

`scripts/recon_ops.py`（提升 + argparse + 配置化）→ `tests/test_recon_ops.py`
→ 两本手册补命令 → 删除 `tmp/recon_ops.py` → ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-10 ｜ `scripts/recon_ops.py`（由 `tmp/recon_ops.py` 提升）
> + `tests/test_recon_ops.py` + 两本手册 + `AGENTS.md`

### 0.0 总判定：**✅ 通过（T1-T6 全过）**

| 判据 | 结果 |
|---|---|
| **T1 配置化** | ✅ 源码**无任何账户标签字面量**；账户列表/输出目录全部取 `cfg.r5/p3.aum_list`、`cfg.*.out_dir`；文件模板集中在 `SPECS` 字典 |
| **T2 行为等价** | ✅ 11 个账户输出与 `tmp/` 版**逐字一致**（例：P3 100w 两行字符级相同）；退出码同为 0 |
| **T3 判别力自证** | ✅ 造假数据：好账户 → 退出码 **0**；坏账户（净值≠现金+持仓，差 100 元）→ ① ❌ 且退出码 **1**；缺文件 → 退出码 1 |
| **T4 只读** | ✅ 真实全量跑一次后，**188 个 ledger/daily/monthly_funds 文件 mtime 全部未变**，目录无新增 |
| **T5 `--strat` 生效** | ✅ `--strat r5` → 4 账户；`--strat p3` → 7 账户；`all`（默认）→ 11 账户 |
| **T6 质量门** | ✅ `ruff check .` 0 错误；`pytest` **103 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动

1. **提升**：`tmp/recon_ops.py` → `scripts/recon_ops.py`（顶层共享，同时覆盖 R5 与 P3）；
2. **argparse 壳**：新增 `--strat {all,r5,p3}` + `--config`（`add_config_arg`）；模块级不读配置/`sys.argv`；
3. **配置化**：`SPECS` 字典 + `run_strategy(strat, cfg)`；账户/路径全部来自配置；
4. **文档**：`strategy_operations_handbook.md` §9.1、`p3_operations_handbook.md` §6.3、
   `AGENTS.md` §3 脚本表各补一处（含用法与退出码语义）；
5. `tmp/recon_ops.py` 已删除（避免两份分叉）。

### 0.2 诚实边界

1. **容差常量未动**（`TOL_ABS=1.0` / `TOL_REL=0.01` / `TOL_EXACT=1e-6`）——既有口径，调参需另开预注册；
2. **P3 已退役的 3 万账户不纳入**（`cfg.p3.aum_list` 本就不含它，现状如实记录）；
3. 覆盖 11 个账户（R5 4 + P3 7），与运营实际账户一致。

### 0.3 复现

```bash
uv run pytest tests/test_recon_ops.py -v      # 6 passed
.venv/bin/python scripts/recon_ops.py         # ✅ 全部通过（共 11 个）；退出码 0
.venv/bin/python scripts/recon_ops.py --strat r5
```

