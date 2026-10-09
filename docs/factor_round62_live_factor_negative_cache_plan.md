# Round 62 `_live_factors` negative cache（"查询成功但无事件"也记账）· 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 触发：R60 §0.4 / R61 §5 记录的遗留缺陷——实测 live 缓存只有 **50 条 / 50 只 code**，
> 因为 `buf` 只累积**有事件**的股票；而 `have = set(prev["code"])` 只认已缓存 code。
> 代码：`scripts/r5/paper_live.py::_live_factors`

---

## 1. 问题（实测）

```python
have = set(prev["code"]) if prev is not None else set()
todo = [c for c in sorted(held) if c not in have]  # 无事件的 code 永远不在 have 里
```

- `buf.append(...)` 只在 `while rs.next()` 里执行 → **只有查到除权事件的股票进缓存**；
- 实测 `adjust_factor_live.parquet` = **50 条 / 50 只**，而查询过的持仓是 **685 只**；
- 于是**每次调用都会重查几乎全部持仓**。`step` 在一个进程内顺序跑四账户
  → 四账户各查一遍 ≈ **20~25 分钟**，其中只有第一遍是必要的。

---

## 2. 规则（定死）

新增 **negative cache**：把"**查询成功**（`error_code == "0"`）"的 code 也记账，
下次窗口被覆盖时跳过。

1. 新增 sidecar：`data/round2/adjust_factor_live_queried.parquet`，列 `[code, since, fac_end]`
   （路径由 `paths.live_fac` **派生同目录兄弟文件**，不改配置）；
2. 新增纯函数（可单测、无 IO）：

```python
def _covered(queried: pd.DataFrame, since, fac_end) -> set[str]:
    """已被成功查询覆盖的 code：旧窗口 ⊇ 新窗口（since' <= since 且 fac_end' >= fac_end）。"""
```

3. `todo` 判定改为：`c not in have and c not in covered`（`have` = 事件缓存，语义不变）；
4. 循环内 `ok=True` 时把 code 记入 `ok_codes`；循环结束后（**不受 `if buf:` 约束**）
   追加写 sidecar，按 `(code, since, fac_end)` 去重；
5. **窗口语义**：`fac_end` 固定为 2026-12-31，`since` 随 `last_exec` 前移 → 旧窗口是
   新窗口的超集 → 可安全跳过。若将来 `fac_end` 前移，旧记录不覆盖 → 自动重查。
6. **只记成功**：查询失败（异常 / `error_code != "0"`）的 code **不写负缓存**，下次仍会重试。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **H1 窗口覆盖正确** | 同窗口覆盖 ✅；更晚 `since` 被覆盖 ✅；`fac_end` 前移**不**覆盖 ✅；`since` 更早的记录覆盖更晚的 ✅ | 防"窗口变宽后错误跳过" |
| **H2 只记成功** | 混合场景（部分成功、部分抛异常）→ sidecar **只含成功的 code**；异常 code 下次仍会重查 | 防"把失败当已查"永久漏事件 |
| **H3 二次调用跳过** | e2e：第一次查 N 只（全成功）→ 第二次用同窗口、**重叠的 held** → 查询数 = 只剩未覆盖的 | 主目标（四账户 4 次 → 1 次） |
| **H4 判别力自证** | 同场景下**旧写法（无负缓存）必然重复查询**、新写法不重复 | R57-W2 / R58-I5 教训 |
| **H5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

**判定**：H1-H5 全过 → 通过。

---

## 4. 诚实风险

1. **语义依赖"`fac_end` 只增不减 + `since` 只前移"**：本轮用 H1 把该假设写成断言，
   但若将来把 `fac_end` **前移**（缩小窗口）又**后移**，旧记录会误判为已覆盖。
   已通过 H1 的"覆盖"定义（旧 ⊇ 新）把错误方向限制在"漏查"而非"误跳"。
2. **缓存中毒不可自愈**：一旦某 code 被成功查询且负缓存，后续窗口扩大**不会**重查它
   —— 这正是设计意图（窗口超集），但意味着**数据源当时返回空 ≠ 真的没有事件**时无法自愈。
   若出现账本对不上，删除 sidecar 即可强制全量重查（已在 §5 记录为运维手段）。
3. **本次首次跑仍需全量查一遍**：sidecar 尚不存在，账户 1 会查 ~635 只；
   收益体现在**账户 2~4 直接跳过**（同一进程内共享 sidecar）→ 今晚从 ~25 分钟降到 ~7 分钟。
4. **未做端到端账本比对**：与 R60/R61 一致，采单测 + e2e（假 baostock）验证，如实记录。

---

## 5. 非目标

- 收窄 live 查询窗口为 `max(last_exec, 静态截止日 + 1)`（R61 §5 已记）——省几日冗余查询，量级小；
- live 因子文件的提交策略调整（当前 3KB 已入库）。

---

## 6. 实施

`scripts/r5/paper_live.py`（`_covered` + `_live_fac_queried_path` + `_live_factors` 接入）
→ `tests/test_live_factors_negative_cache.py` → ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `scripts/r5/paper_live.py` + `tests/test_live_factors_negative_cache.py`
> §2 规则与 §3 判定标准**实施前写死，实施后未改**。

### 0.0 总判定：**✅ 通过（H1-H5 全过）**

| 判据 | 结果 |
|---|---|
| **H1 窗口覆盖正确** | ✅ 5 条断言全过：同窗口覆盖 / 旧窗口更宽覆盖 / **`fac_end` 前移不覆盖** / **`since` 更晚不覆盖** / 空表与部分覆盖 |
| **H2 只记成功** | ✅ 10 只中 2 只抛异常 → sidecar **只含 8 只**；再跑时**只重试失败的 2 只** |
| **H3 二次调用跳过** | ✅ 首次查 **100** 只 → 第二次（100+20 只）只查 **20** 只；窗口变宽（`since` 前移）则**重新查询** |
| **H4 判别力自证** | ✅ 同场景：**旧写法第二次仍查 100 只** vs 新写法 **0 只** |
| **H5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **52 passed**（默认）+ **3 passed**（`-m slow`） |

### 0.1 改动（4 个新 helper + `_live_factors` 接入）

1. `_live_fac_queried_path()`：sidecar 路径 = `live_fac` 的**同目录兄弟文件**
   `data/round2/adjust_factor_live_queried.parquet`（派生，不改配置）；
2. `_load_queried()` / `_save_queried()`：读写 `[code, since, fac_end]`，按三元组去重；
3. `_covered(queried, since, fac_end)`：覆盖定义 = 旧窗口 ⊇ 新窗口
   （`since' <= since` 且 `fac_end' >= fac_end`）；
4. `_live_factors`：`todo = c not in have and c not in covered`；
   `ok=True` 时记入 `ok_codes`；循环后**不受 `if buf:` 约束**地追加写 sidecar。

### 0.2 收益（本轮主目标）

`step` 在**一个进程内顺序跑四账户**，且各账户的 `held ∪ target` 高度重叠：

| | 修复前 | 修复后 |
|---|---|---|
| 账户 1 | 查 ~635 只 | 查 ~635 只（sidecar 首次建立） |
| 账户 2~4 | **各再查 ~635 只** | **~0 只（直接跳过）** |
| 合计 | **~25 分钟** | **~7 分钟** |

### 0.3 诚实边界

1. **首次跑仍要全量查一遍**：sidecar 尚不存在，账户 1 必须查；收益体现在账户 2~4。
2. **未做端到端账本比对**（与 R60/R61 一致）：采单测 + e2e（假 baostock + tmp_path）。
3. **缓存中毒不可自愈**：若数据源当时返回空但实际有事件，负缓存不会自动纠正。
   **运维手段：删除 `data/round2/adjust_factor_live_queried.parquet` 即强制全量重查**
   （该文件 gitignore——它是记账缓存，不是账本输入，与 `adjust_factor_live.parquet` 性质不同）。

### 0.4 复现

```bash
uv run pytest tests/test_live_factors_negative_cache.py -v   # 9 passed
uv run ruff check .
```

