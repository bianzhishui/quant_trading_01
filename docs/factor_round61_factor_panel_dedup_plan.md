# Round 61 `_factor_panel` 合并去重修复（静态×live 重叠 → 重复索引标签）· 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 触发：2026-10-09 首次 R5 月度 `step` 在 `_live_factors` **成功之后**崩溃：
> ```
> [live因子] 新增 50 条(685 只持仓)
>   File "scripts/r5/paper_live.py", line 259, in _factor_panel
>     f_series[c] = g.reindex(idx).ffill().bfill().fillna(1.0)
> ValueError: cannot reindex on an axis with duplicate labels
> ```
> 影响面：**R5 与 P3 共用** `_factor_panel_cached`（`paper_live_p3.py:41,284,391`）
> → P3 的 `step`/`mark` 会以完全相同方式失败。
> 代码：`scripts/r5/paper_live.py::_factor_panel`

---

## 1. 问题（实测证据，非推测）

两个因子表的 `date` 范围**天然重叠**：

| 文件 | 行数 | date 范围 |
|---|---|---|
| 静态 `data/round2/adjust_factor.parquet` | 32,332 | 2012-01-05 ~ **2026-09-03** |
| live `data/round2/adjust_factor_live.parquet` | 50 | **2026-09-03** ~ 2026-10-08 |

- live 的查询窗口起自 `led["last_exec"]` = **2026-09-01**，静态截止 **2026-09-03**
  → 窗口 **[09-01, 09-03] 重叠 3 天**；
- 实测：`sz.003008` 在**两个文件里都有 2026-09-03 一行**（值均为 1.0）
  → `pd.concat` 后同一 `(code, date)` 出现两次
  → `fac.groupby("code")` 后 `g` 的索引含重复标签
  → `g.reindex(idx)` 抛 `cannot reindex on an axis with duplicate labels`。

**只要有任何一只股票在 [last_exec, 静态截止日] 这 3 天内有除权事件，step 必崩**
（本次恰好 1 只）。

`_load_corp()` 读的是**纯静态**表，无此问题；只有 `_factor_panel()` 做静态×live 合并。

---

## 2. 规则（定死，唯一改动）

**唯一改动 = 合并后按 `(code, date)` 去重（live 优先）**；查询范围、窗口、缓存格式、
账本/净值/选股一律不动。

1. 新增可单测的纯函数：

```python
def _merge_factor_tables(
    static: pd.DataFrame, live: pd.DataFrame | None
) -> pd.DataFrame:
    """静态+live 复权因子表合并: 按 (code,date) 去重, live 优先。

    live 查询窗口自 last_exec 起, 与静态截止日重叠 → 不去重会产生重复索引标签,
    下游 reindex 直接抛 "cannot reindex on an axis with duplicate labels"。
    """
    if live is None:
        return static
    return (
        pd.concat([static, live], ignore_index=True)
        .drop_duplicates(subset=["code", "date"], keep="last")
        .reset_index(drop=True)
    )
```

2. `_factor_panel()` 改用它（`live_fac.exists()` 时传 live，否则传 `None`）；
3. 循环内加**双保险**：`g = g[~g.index.duplicated(keep="last")]` 后再 `reindex`；
4. `keep="last"` 的选择依据：live 是**新查**的值，同 `(code,date)` 冲突时以 live 为准。
   实测冲突样本 `sz.003008@2026-09-03` 两表值均为 `1.0`（见 G2）。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **G1 复现与修复** | 用**当前真实数据**调 `_factor_panel`：修复前必抛 `ValueError`，修复后正常返回且形状 = `close.shape` | 主目标 |
| **G2 取值零改动** | 对两表重叠的全部 `(code, date)`，`foreAdjustFactor` **逐位相等**（断言 max abs diff == 0）→ 去重不改变任何取值，`keep` 方向无歧义 | 防"去重改变了数字" |
| **G3 判别力自证** | 合成含重复 `(code,date)` 的输入：**旧写法（concat 不去重）必然抛 ValueError**，新写法通过 | R57-W2 / R58-I5 教训 |
| **G4 质量门** | `ruff check .` 0 错误 + `pytest` 全过 | 仓库硬性要求 |

**判定**：G1-G4 全过 → 通过；任一不过 → 如实归档。

---

## 4. 诚实风险

1. **G2 仅覆盖当前重叠样本**：若将来两表对同一 `(code,date)` 给出**不同**值，
   `keep="last"`（live）是正确选择（新查 > 旧抓），但本轮无法用数据证明该分支；
   G2 只能证明"当前冲突样本取值相同"。**如实记录**。
2. **未做端到端账本重跑**：`step` 的完整重跑要 ~15 分钟且需 baostock 在线；
   本轮验证到"`_factor_panel` 不再抛错 + 面板数值与去重前对非重叠部分逐位一致"。
3. **上游窗口重叠仍在**：查询窗口 `[last_exec, fac_end]` 与静态表重叠 3 天，
   每次多查几日（量级可忽略）。收窄窗口属另一处语义改动 → **非目标**（§5）。

---

## 5. 非目标（记录，另议）

- 收窄 live 查询窗口为 `max(last_exec, 静态截止日 + 1 天)`（省几日的冗余查询）；
- R60 §0.4 记的 **negative cache**（把"查询成功但无事件"的 code 也记账，四账户 4 次重查压成 1 次）。
  两者都改查询语义，与本轮"只修合并去重"正交。

---

## 6. 实施

`scripts/r5/paper_live.py`（新增 `_merge_factor_tables` + `_factor_panel` 改用 + 双保险去重）
→ `tests/test_factor_panel_merge.py`（合成数据快测 + 真实数据 `-m slow` 复现门）
→ ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `scripts/r5/paper_live.py` + `tests/test_factor_panel_merge.py`
> §2 规则与 §3 判定标准**实施前写死，实施后未改**。

### 0.0 总判定：**✅ 通过（G1-G4 全过）**

| 判据 | 结果 |
|---|---|
| **G1 复现与修复** | ✅ 用**当前真实数据**：修复前写法在 `sz.003008@2026-09-03` 上抛 `ValueError: cannot reindex on an axis with duplicate labels`；修复后 `_factor_panel` 正常返回 **3243×3409、0 NaN** |
| **G2 取值零改动** | ✅ 两表重叠样本 `foreAdjustFactor` **max abs diff = 0**（且断言"必须真有重叠样本"，否则判据无判别力） |
| **G3 判别力自证** | ✅ 合成重复输入：**旧写法必然抛 ValueError，新写法通过**；并验证 `keep="last"` → live 优先 |
| **G4 质量门** | ✅ `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow` 两个门） |

### 0.1 改动（3 处）

1. 新增纯函数 `_merge_factor_tables(static, live)`：`concat` → `date` 归一 → 按
   `(code, date)` `drop_duplicates(keep="last")`；`live is None/空` 时原样返回 `static`；
2. `_factor_panel()` 改用它（原来 `if live_fac.exists(): fac = pd.concat([...])` 无去重）；
3. 循环内加双保险 `g = g[~g.index.duplicated(keep="last")]`。

### 0.2 端到端验证（原崩溃调用点，真实全市场面板）

```
close: (3243, 3409)  | 末交易日 2026-10-08
F    : (3243, 3409)  | NaN 0        ← 原先在此抛 ValueError
待处理调仓: 1 个（2026-09-30 信号）
✅ 原崩溃点已通过
```

### 0.3 影响面

`_factor_panel_cached` 被 **R5 `paper_live.py` 与 P3 `paper_live_p3.py`（:41 导入,
:284/:391 调用）共用** → 本轮一处修复，**两个策略的 `step`/`mark` 同时解除阻塞**。
`_load_corp()` 读纯静态表，无此问题。

### 0.4 诚实边界

- **未做完整 `step` 账本重跑**：本轮验证到"面板构建通过 + 未抛错"，
  step 的完整跑（含 live 查询 ~4-8 分钟 + 四账户调仓）由用户在 2026-10-09 执行；
- **G2 只覆盖当前重叠样本**（`sz.003008@2026-09-03`，两表值均为 1.0）。若将来两表对同一
  `(code,date)` 给出**不同**值，`keep="last"`（live 优先）是设计选择，但本轮无数据证明该分支
  —— 已如实记录，见 §4.1。

### 0.5 复现

```bash
uv run pytest tests/test_factor_panel_merge.py -v        # 4 passed（快）
uv run pytest tests/test_factor_panel_merge.py -m slow   # 2 passed（真实数据门）
uv run ruff check .
```

