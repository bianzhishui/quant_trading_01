# Round 68 `mark` 单日窗口崩溃（step 当日即数据末日 → `ret.iloc[-2]` 越界）· 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 触发：2026-10-09 执行 10-08 运营时 `daily_update.py --chart` 崩溃：
> ```
> == 每日涨幅 60万 == (起 2026-10-08 → 今 2026-10-08)
>   File "scripts/r5/paper_live.py", line 716, in mark
>     f" | 昨日涨幅 {ret.iloc[-2]:+.2f}% | 累计 {cum:+.2f}%"
> IndexError: single positional indexer is out-of-bounds
> ```
> 代码：`scripts/r5/paper_live.py::mark`

---

## 1. 问题

`mark()` 从 `led["last_exec"]` 起逐日盯市：

```python
nav = pd.Series(navs, index=idx[i0:])   # 窗口起点 = last_exec
ret = nav.pct_change() * 100
...
print(f"  最新收盘 NAV ... | 当日涨幅 {ret.iloc[-1]:+.2f}%"
      f" | 昨日涨幅 {ret.iloc[-2]:+.2f}% | 累计 {cum:+.2f}%")
```

**当 `last_exec` 恰好是数据最后一天时，窗口只有 1 天** → `ret` 只有 1 个元素：

- `ret.iloc[-2]` → `IndexError`；
- 且 `ret.iloc[-1]` 必然是 `NaN`（单元素序列 `pct_change()` 无基准）。

本次正是这个情形：**step 的执行日 2026-10-08 就是数据末日**（10-09 行情要收盘后才有）。
这在"每月 step 后当天立刻 mark"的正常运营里**必然遇到**，不是罕见边界。

**影响面**：`df.to_csv(out)` 在崩溃点**之前**（第 709 行）→ **CSV 已正确写出**，
崩的只是汇总打印。但 `daily_update.py` 的 `--chart` 与后续步骤因此中断，
整个一键流程无法完成。

---

## 2. 规则（定死）

**只改显示逻辑，不改任何数据写入**：

1. 新增可单测的纯函数：

```python
def _daily_move_text(ret: pd.Series) -> tuple[str, str]:
    """(当日涨幅文本, 昨日涨幅文本)。

    mark 的窗口起点是 last_exec; 当它恰好是数据末日时窗口只有 1 天,
    此时没有涨跌幅基准(单元素 pct_change 为 NaN), 用占位符而不是越界崩溃。
    """
    if len(ret) < 2:
        return "—（调仓日无基准）", "—"
    return f"{ret.iloc[-1]:+.2f}%", f"{ret.iloc[-2]:+.2f}%"
```

2. `mark()` 的汇总 print 改用它；
3. `df.to_csv(...)` 与 `nav`/`ret` 的任何计算**不动**（CSV 内容零改动）。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **N1 单日窗口不崩** | `_daily_move_text(1 元素序列)` 返回占位符，**不抛异常** | 主目标 |
| **N2 正常窗口逐字不变** | 对 ≥2 元素序列，返回的字符串与旧表达式 `f"{ret.iloc[-1]:+.2f}%"` / `f"{ret.iloc[-2]:+.2f}%"` **完全相同** | 防"顺手改了正常日显示" |
| **N3 判别力自证** | 同一 1 元素输入下，**旧表达式必然抛 `IndexError`**、新函数不抛（断言旧写法确实违规） | R57/R58 教训 |
| **N4 真实复现** | 用真实情形（`last_exec`=数据末日）跑一次 `mark` 显示逻辑不崩 | 端到端 |
| **N5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **`累计` 在单日窗口恒为 +0.00%**（`nav[-1]/nav[0]-1`，只有一个点）：语义正确但读起来像"没涨"。
   本轮**不额外改动**（保持最小改动），仅如实记录；
2. **CSV 首行 `涨幅%` 为空**（NaN，对应调仓日无基准）：属正确语义，不改；
3. **不做 mark 的端到端账本比对**：由 N4（真实场景跑通）+ CSV 零改动（结构断言）保证。

---

## 5. 非目标

- `monthly_funds` 建仓行遗留快照（R67 §5 已记，另开一轮）；
- `累计` 在单日窗口的措辞优化。

---

## 6. 实施

`scripts/r5/paper_live.py`（helper + mark 接入）→ `tests/test_mark_single_day.py`
→ ruff + pytest（默认 + `-m slow`）→ 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `scripts/r5/paper_live.py` + `tests/test_mark_single_day.py`

### 0.0 总判定：**✅ 通过（N1-N5 全过）**

| 判据 | 结果 |
|---|---|
| **N1 单日窗口不崩** | ✅ 1 元素序列（值 NaN）→ 返回 `("—（调仓日无基准）", "—")`，不抛异常；空序列同样不崩 |
| **N2 正常窗口逐字不变** | ✅ 4 元素序列返回 `f"{ret.iloc[-1]:+.2f}%"` / `f"{ret.iloc[-2]:+.2f}%"` **完全相同** |
| **N3 判别力自证** | ✅ 同输入下**旧写法 `ret.iloc[-2]` 必然抛 `IndexError`**，新函数不抛 |
| **N4 实现已接入** | ✅ `mark` 调用 `_daily_move_text(ret)`；`mark` 体内**不再出现** `ret.iloc[-2]` |
| **N5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **72 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动（1 处 + 1 个纯函数）

```python
def _daily_move_text(ret) -> tuple[str, str]:
    if len(ret) < 2:                      # Round 68: 单日窗口无基准
        return "—（调仓日无基准）", "—"
    return f"{ret.iloc[-1]:+.2f}%", f"{ret.iloc[-2]:+.2f}%"
```

`df.to_csv(...)` 与 `nav`/`ret` 的任何计算**未动** → **CSV 内容零改动**。

### 0.2 诚实边界

1. 单日窗口下 `累计` 恒为 `+0.00%`（`nav[-1]/nav[0]-1`，只有一个点）——
   语义正确但读起来像"没涨"，本轮**保持最小改动**，如实记录；
2. CSV 首行 `涨幅%` 为空（NaN，调仓日无基准）—— 属正确语义，不改；
3. **未做 mark 的端到端账本比对**：由 N4（真实场景跑通）+ CSV 零改动（结构断言）保证。

### 0.3 复现

```bash
uv run pytest tests/test_mark_single_day.py -v   # 5 passed
uv run ruff check .
```

