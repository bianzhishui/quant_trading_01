# Round 63 `step` 控制台"月涨 +0.00%"显示 bug · 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 触发：2026-10-09 首次 R5 `step` 控制台打印 `月涨 +0.00%`，而 `monthly_funds_*.csv`
> 同一次调仓写的是 `−0.53% / −0.41% / −0.29% / −0.26%`——**两者不可能同时正确**。
> 代码：`scripts/r5/paper_live.py:527,542`

---

## 1. 问题（代码级，已定位）

```python
506:  post_nav = pf.value(raw_e.loc[rb["exec"]])
517:  "mret": (post_nav / prev_post - 1) * 100,     # ← 先算, 正确
527:  prev_post = post_nav                          # ← 覆盖
539:  print(f"... 月涨 {((post_nav / prev_post) - 1) * 100:+.2f}% ...")   # ← 分母已是自己
```

`prev_post` 在第 527 行被更新为 `post_nav`，第 542 行的 print 再用它做分母
→ `post_nav / prev_post ≡ 1` → **永远打印 `+0.00%`**。

- **CSV 值正确**（第 517 行在覆盖之前求值）；
- **纯显示缺陷**：不影响账本、净值、费用、换手、对账不变量；
- 建账以来第一次 `step` 才暴露（此前无任何 step 记录）。

---

## 2. 规则（定死）

1. 把月收益只算一次，存成局部变量 `mret`，**同时**供 `_append_monthly_funds` 与 print 使用；
2. print 语句内**不得再引用 `prev_post`**（它在同一作用域内已被覆盖）；
3. `prev_post = post_nav` 的赋值时机不变（它管下一轮），顺序改动仅限"先取值再用"。

```python
mret = (post_nav / prev_post - 1) * 100
_append_monthly_funds(aum, {..., "mret": mret, ...})
prev_post = post_nav
...
print(f"... 月涨 {mret:+.2f}%, NAV {nav / 1e4:.1f}万")
```

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **I1 打印=CSV** | 打印所用的 `mret` 与写入 CSV 的 `mret` 是**同一个表达式值**（结构断言：print 行引用 `mret` 且不含 `prev_post`） | 主目标 |
| **I2 判别力自证** | 用真实数字（post=594897.98, prev=598087.91）：**旧顺序必然得 0.00**、新顺序得 **−0.53%**（与 CSV 一致，误差 <0.01pp） | 防无判别力的判据 |
| **I3 数据零改动** | `monthly_funds` / 账本 / `nav_history` 任何字段不得变化（纯显示修复） | 防"顺手改了数字" |
| **I4 质量门** | `ruff check .` 0 错误 + `pytest` 全过 | 仓库硬性要求 |

---

## 4. 诚实风险

- `step` 完整重跑要 ~5 分钟且需 baostock；本轮用**结构断言 + 真实数字算式**验证，
  **不做**端到端 step 重跑比对（如实记录）。
- 该 bug 只影响人眼读控制台，不影响任何入库产物；但会**误导判断**（本次就骗到了我），
  故按缺陷修复而非"小事跳过"。

---

## 5. 非目标

- `report` / 图表里的月涨显示（另查）；
- R64 的 `bench_base` 重算（同批次但独立预注册）。

---

## 6. 实施

`scripts/r5/paper_live.py`（提取 `mret`）→ `tests/test_month_return_display.py` → ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `scripts/r5/paper_live.py` + `tests/test_month_return_display.py`

### 0.0 总判定：**✅ 通过（I1-I4 全过）**

| 判据 | 结果 |
|---|---|
| **I1 打印=CSV** | ✅ print 行只引用 `mret`、不再出现 `prev_post`；`mret` 计算位置早于 `prev_post = post_nav` |
| **I2 判别力自证** | ✅ 真实数字（post 594897.98 / prev 598087.91）：**旧顺序恒为 `+0.00`**，新顺序 **`−0.5334`**（= CSV `月涨幅%` −0.5334，误差 <0.002pp） |
| **I3 数据零改动** | ✅ CSV 写入改用同一变量 `"mret": mret`；`last_signal`/`last_exec`/`shares`/`cash`/`total_fees`/`last_blocked` 赋值均未动 |
| **I4 质量门** | ✅ `ruff check .` 0 错误 + `pytest` 全过 |

### 0.1 改动（1 处）

```python
mret = (post_nav / prev_post - 1) * 100      # ← 新增: 只算一次
_append_monthly_funds(aum, {..., "mret": mret, ...})
prev_post = post_nav
print(f"... 月涨 {mret:+.2f}%, NAV ...")        # ← 不再用已覆盖的 prev_post
```

### 0.2 诚实边界

**未做端到端 `step` 重跑比对**（`step` 当前已无待处理调仓，重跑是空操作），
采"结构断言 + 真实数字算式"验证。该 bug 仅影响控制台可读性，
不改变任何入库产物（`monthly_funds`/账本/`nav_history` 均不受影响）。

### 0.3 复现

```bash
uv run pytest tests/test_month_return_display.py -v   # 5 passed
uv run ruff check .
```

