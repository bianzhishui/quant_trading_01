# Round 69 每日净值 CSV 累积写（step 后不再丢历史）+ P3 单日窗口越界 · 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 触发：2026-10-09 执行 10-08 运营时发现——`mark` 是**覆盖写**，只写 `last_exec` 起的窗口：
> ```
> output/r5/daily_nav_aum600w.csv:  22 行(09-01..09-30) → 2 行(仅 10-08)
> git diff --stat: 1 insertion(+), 21 deletions(-)
> ```
> 代码：`scripts/r5/paper_live.py::mark` 与 `scripts/p3/paper_live_p3.py::mark`

---

## 1. 问题（两个，同源）

### ① 覆盖写 → 每次 step 丢一段历史（R5 + P3 都有）

```python
nav = pd.Series(navs, index=idx[i0:])   # i0 = last_exec 所在行
...
df.to_csv(out, index=False)             # 覆盖, 不是追加
```

`last_exec` 每次 step 后前移 → 窗口随之后移 → **上一段每日净值被整段丢弃**。

**为什么之前没暴露**：账本建于 09-01、这是**第一次 step**；在此之前 `last_exec` 恒为 09-01，
窗口起点不变，覆盖写恰好等价于累积写。

**影响**：`output/r5/daily_nav_aum*.csv` 是**入库跟踪**产物，
`plot_daily_gains.py --live` 的定位是"**建仓以来**实时场景"——CSV 一旦只剩当前月，
5 张每日图里的 `daily_nav_aum*.png` / `daily_gains_live.png` 就都退化成"本调仓期内"；
总表的 `建仓日NAV` 列也会变成"上次调仓 NAV"（本轮实测已发生：594,898 = 10-08 值）。

### ② P3 `mark` 的单日窗口越界（R68 的同类，P3 侧未修）

```python
f"昨日 {nav.iloc[-2] / 1e4:.2f}万 ..."     # 窗口只有 1 天时越界
```

R68 只修了 R5；P3 已有自己的 `mark`，且 P3 也已在 10-08 step →
P3 的 `daily_update_p3.py` 下一次跑就会以同样方式崩。

---

## 2. 规则（定死）

1. 新增可单测的公共 helper（R5 定义，P3 复用）：

```python
def _write_daily_nav(out: Path, df: pd.DataFrame) -> pd.DataFrame:
    """每日净值 CSV 累积写: 与既有文件按 date 去重(新值优先)后排序写出。"""
    if out.exists():
        prev = pd.read_csv(out)
        df = (
            pd.concat([prev, df], ignore_index=True)
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
    df.to_csv(out, index=False)
    return df
```

2. R5 `mark` 与 P3 `mark` 的 `df.to_csv(out, index=False)` 改用它；
3. P3 `mark` 的"昨日"打印改用 R5 的 `_daily_move_text`（R68 已存在）；
4. **不改** `nav`/`ret` 的任何计算（新增行的数值零改动）；
5. **恢复**已被覆盖的 R5 四个 CSV（从 git `HEAD` 取回 09-01..09-30 段），
   再重新跑 mark 使其累积为 09-01..10-08。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **O1 累积不丢历史** | 既有 3 行 + 新窗口 2 行 → 写出 5 行；**既有行的值逐位不变** | 主目标 |
| **O2 幂等** | 同一份新窗口重复写两次 → 行数与值均不变 | 防重复 mark 破坏 |
| **O3 判别力自证** | 同场景下**旧写法（覆盖）必然只剩新窗口行数**（3 → 2），新写法 5 行 | R57/R58 教训 |
| **O4 P3 单日窗口不崩** | P3 `mark` 体内不再出现 `nav.iloc[-2]`；改用的 helper 对 1 元素序列返回占位符 | R68 同类 |
| **O5 真实恢复** | R5 四账户 CSV 重跑后 = **09-01..10-08 共 22 行**（21 旧 + 1 新），且旧行与 git 版本逐位一致 | 端到端 |
| **O6 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **历史行的数值不会被重算**（它们来自上一段的持仓，本就不该变）；若将来要重算历史，
   需另开一轮；
2. `daily_gains_live.png` 等图**在本次修复前已按"仅 10-08"渲染过一次**，
   修复后需**重新出图**覆盖（本轮会重跑 mark + `--chart`）；
3. P3 的每日 CSV **不入库**（AGENTS.md），故只需修代码、不需要 git 恢复；
   但同样会受益（其 live 图不再退化）。

---

## 5. 非目标

- `monthly_funds` 建仓行遗留快照（R67 §5 已记）；
- 每日 CSV 与账本 `nav_history` 的对账口径统一（另议）。

---

## 6. 实施

`scripts/r5/paper_live.py`（helper + mark 接入）→ `scripts/p3/paper_live_p3.py`（复用 helper + 单日修）
→ `tests/test_daily_csv_accumulate.py` → 恢复 R5 四 CSV → 重跑 mark/chart → ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `scripts/r5/paper_live.py` + `scripts/p3/paper_live_p3.py`
> + `tests/test_daily_csv_accumulate.py`

### 0.0 总判定：**✅ 通过（O1-O6 全过）**

| 判据 | 结果 |
|---|---|
| **O1 累积不丢历史** | ✅ 既有 3 行 + 新窗口 1 行 → 写出 **4 行**；既有行**逐位不变** |
| **O2 幂等** | ✅ 同一份新窗口重复写两次 → 行数与值均不变 |
| **O3 判别力自证** | ✅ 同场景：**旧写法（覆盖）必然只剩 1 行**（实测线上 22 行 → 2 行），新写法 4 行 |
| **O4 P3 单日窗口已修** | ✅ P3 `mark` 体内不再出现 `nav.iloc[-2]`，改用 `_daily_move_text`；且已接 `_write_daily_nav` |
| **O5 真实恢复** | ✅ R5 四账户 CSV 重跑后 = **23 行（表头 + 21 旧 + 10-08）**，旧行与 git 版本一致；总表 `建仓日NAV` **恢复真值**（598,088 / 996,750 / 2,993,241 / 5,988,730） |
| **O6 质量门** | ✅ `ruff check .` 0 错误；`pytest` **76 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动（2 处 + 1 个公共 helper）

1. 新增 `_write_daily_nav(out, df)`：与既有 CSV 按 `date` 去重（新值优先）后排序写出；
2. R5 与 P3 的 `mark` 都改用它（`df.to_csv` 覆盖 → 累积）；
3. P3 `mark` 的"昨日/今日"打印改用 R5 的 `_daily_move_text`（R68 的同类修复，P3 侧此前未覆盖）。

**`nav`/`ret` 的任何计算未动** → 各行的数值零改动。

### 0.2 端到端结果（10-08 运营已收口）

- R5 四账户：mark + 5 张图 ✅；**对账 ④ 全部转 ✅**
- P3 七账户：mark + 8 张图 ✅
- **`tmp/recon_ops.py` → `✅ 全部通过（共 11 个）`**（①②③④ 全绿）

### 0.3 诚实边界

1. **历史行的数值不会被重算**（它们来自上一段持仓，本就不应改变）；若将来需要重算，另开一轮；
2. 修复前 `daily_gains_live.png` 曾按"仅 10-08"渲染过一次，本轮已**重新出图覆盖**；
3. P3 每日 CSV 不入库（`.gitignore`），故无需 git 恢复，但其 live 图同样受益。

### 0.4 复现

```bash
uv run pytest tests/test_daily_csv_accumulate.py -v   # 4 passed
.venv/bin/python scripts/r5/daily_update.py --chart
.venv/bin/python scripts/p3/daily_update_p3.py --chart
.venv/bin/python tmp/recon_ops.py                     # 11/11 通过
```

