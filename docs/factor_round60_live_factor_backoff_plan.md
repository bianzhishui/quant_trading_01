# Round 60 `_live_factors` 退避误判修复（"空结果" 被当成 "限流"）· 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 触发：2026-10-09 首次 R5 月度 `step`（exec=2026-10-08）实测——每查满 50 只
> 就打印 `[live因子] 疑似限流, 休眠90s` 并 `logout/login`，反复循环。
> 代码：`scripts/r5/paper_live.py::_live_factors` ｜ 判据：F1-F4

---

## 1. 问题（代码级，已定位）

`scripts/r5/paper_live.py` 第 211-234 行：

```python
for c in todo:
    got = False
    for _ in range(3):
        try:
            rs = bs.query_adjust_factor(code=c, start_date=since, end_date=fac_end)
            while rs.error_code == "0" and rs.next():
                r = rs.get_row_data()
                buf.append({...})
                got = True  # ← 只有"查到事件"才置 True
            break
        except Exception:
            time.sleep(2.0)
    streak = streak + 1 if not got else 0
    if streak >= ca.empty_streak:  # empty_streak = 50
        print(f"  [live因子] 疑似限流, 休眠{ca.backoff}s")
        bs.logout()
        time.sleep(ca.backoff)
        bs.login()  # backoff = 90
        streak = 0
    time.sleep(0.1)
```

`got` 把**两种语义完全不同**的情况混为一谈：

| 情况 | 现状 | 应然 |
|---|---|---|
| 查询成功，但该股在窗口内**没有**除权事件（常见） | `got=False` → 计入 streak | 视为**成功**，不计入 |
| 请求异常（真限流 / 会话失效） | `got=False` → 计入 streak | 视为失败，计入 |

**后果**：窗口 [2026-09-01, 2026-12-31] 内绝大多数股票没有任何分红送转（9-10 月本就是空窗期），
于是连续 50 只正常空结果就被判成限流，白睡 90s 并强制重登。实测 600~750 只持仓
→ 约 13 轮 → 约 **20 分钟纯休眠** + 13 次多余的重登（重登本身也可能加重服务端限流）。

**附带缺陷（本轮不改，见 §5）**：无事件的 code 不会进缓存，`have = set(prev["code"])`
只认"有事件"的股票 → 每次 step 都重查全部持仓股。

---

## 2. 规则（定死，唯一改动）

**唯一改动 = 失败判定语义**；查询范围、窗口、缓存格式、写盘时机、账本/净值一律不动。

1. 新增纯函数（可单测、无 IO）：

```python
def _streak_after(ok: bool, streak: int, threshold: int) -> tuple[int, bool]:
    """ok=本次查询是否成功(空结果也算成功)。返回(新 streak, 是否退避)。"""
    s = 0 if ok else streak + 1
    return (0, True) if s >= threshold else (s, False)
```

2. 循环内：
   - 查询调用返回且 `rs.error_code == "0"` → `ok = True`（**空结果同样算成功**）；
   - `rs.error_code != "0"`（如"用户未登录"）→ **抛异常**，走既有的 3 次重试 → `ok=False`；
   - 异常 → `ok=False`（保持既有语义）；
   - 退避由 `_streak_after` 决定（阈值/backoff 仍读 `config.fetch.corporate_actions`，不改配置）。

3. **不做**的事：不改 `since`/`fac_end`、不改缓存路径与字段、不改 `todo`/`have` 逻辑、
   不加 negative cache、不加登录失败早退（见 §5）。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **F1 语义正确** | 连续 N（≥threshold）次**成功空结果** → **不退避**；连续 threshold 次**异常** → 退避 | 本次修复的主目标 |
| **F2 产出零改动** | 修复前后，`buf` 累积的 `{code,date,foreAdjustFactor}` 集合与写盘内容**逐位一致**（行序可不同）；账本/净值/对账不变量不变 | 只删副作用，不改数据 |
| **F3 判别力自证** | 单测必须包含"**旧写法必然违规、新写法 0 违规**"的断言（R57-W2 / R58-I5 教训：判据必须有判别力） | 防"无判别力的判据" |
| **F4 质量门** | `ruff check .` 0 错误 + `pytest` 全过 | 仓库硬性要求 |

**判定**：F1-F4 全过 → 通过；任一不过 → 如实归档，不强行收尾。

---

## 4. 诚实风险

1. **真限流时的退避频次下降**：修复后只有**异常**才计入 streak。若服务端以
   "成功响应但恒空"的方式限流（极端假设），则不再退避——但那种形态等价于
   "真的没有事件"，重登也无法改善，故不列为风险敞口。
   保留的防线：异常仍走 3 次重试（每次间隔 2s）+ `empty_streak` 阈值 + 90s 退避。
2. **"用户未登录" 不抛异常**：baostock 把它放在 `rs.error_code` 里。因此必须显式
   检查 `error_code != "0"` 并抛错，否则修复会**削弱**原有的退避（这是本次实现的关键点）。
3. **F2 的验证方式**：本次不重跑全量 step 比对（baostock 当前限流，且用户 step 在跑）。
   采**结构性论证 + 单测**：改动只涉及 `ok`/`streak`/退避分支，`buf.append(...)` 的条件与
   `todo`/`have` 完全未动 → 输出集合恒等。**如实记录为"分析论证 + 单测，非端到端重跑"**。
4. **运行中的进程不受影响**：正在跑的 step 已把模块载入内存，改文件只对下次生效。

---

## 5. 非目标（记录，另议）

- **negative cache**：把"已查询成功但无事件"的 code 也记下来，避免每次 step 重查全部持仓。
  需要新增 sidecar 产物 + 处理"查询失败不得负缓存" + 窗口推进语义 → 另开一轮。
- **登录失败早退**：`_live_factors` 顶部 `bs.login()` 未检查返回值。补上可避免
  被黑名单时白跑 600 只 ×3 重试 → 另开一轮。
- **静态因子重抓**（`fetch_corporate_actions.py`）→ 根治手段，跟本 bug 无关。

---

## 6. 实施

`scripts/r5/paper_live.py`（`_streak_after` + 循环内语义）→ `tests/test_live_factor_backoff.py`
（纯函数 + 判别力自证）→ ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `scripts/r5/paper_live.py` + `tests/test_live_factor_backoff.py`
> §2 规则与 §3 判定标准**实施前写死，实施后未改**。

### 0.0 总判定：**✅ 通过（F1-F4 全过）**

| 判据 | 结果 |
|---|---|
| **F1 语义正确** | ✅ 空结果不计入失败；连续 threshold 次真失败才退避；成功打断连击；阈值 1/2/5/50/500 全成立 |
| **F2 产出零改动** | ✅（**分析论证 + e2e 假 baostock 测试**，非端到端账本重跑，见 §0.3） |
| **F3 判别力自证** | ✅ 同一场景：新语义 **0 次**退避 vs 旧语义 **20 次**（1000 只无事件）= 30 分钟纯休眠；真失败场景两版**一致**（260 只 → 各 5 次） |
| **F4 质量门** | ✅ `ruff check .` 0 错误；`pytest` **39 passed**（新增 9 条） |

### 0.1 改动（2 处，唯一语义变更）

1. 新增纯函数 `_streak_after(ok, streak, threshold) -> (新 streak, 是否退避)`；
2. `_live_factors` 循环内：
   - 查询调用成功 **且** `rs.error_code == "0"` → `ok = True`（**空结果同样算成功**）；
   - `rs.error_code != "0"`（如"用户未登录"）→ **抛错**，走既有 3 次重试 → `ok=False`；
   - 退避改由 `_streak_after` 判定（阈值/backoff 仍读配置，未改配置）。

> ⚠️ 第 2 条中的 `error_code != "0"` 显式抛错是**必需的**：baostock 把"用户未登录"放在
> `rs.error_code` 里而不抛异常。若不补这一条，修复会**削弱**真会话失效时的退避
> （被计入"成功"）。这正是 §4.2 预判的风险点，已按预案处理。

### 0.2 修复效果（可量化）

触发场景为 2026-10-09 首次 R5 `step`（exec=2026-10-08，窗口 [2026-09-01, 2026-12-31]）：

- 旧代码：连续 50 只"查询成功但无除权事件"即被判限流 → `休眠90s` + 强制 `logout/login`；
- 新代码：端到端测试（120 只全部查询成功、无事件）→ **只登录 1 次、logout 1 次、0 次 90s 休眠**，
  退避休眠序列恰为 `[0.1] * 120`；
- 真失败场景（连续 50 次抛异常）→ **仍然退避**、**仍然重登**（保护未被削弱）。

### 0.3 诚实边界（F2 的验证方式）

**未做**端到端账本重跑比对（原因：baostock 当日仍在限流，且用户 `step` 正在运行、不宜并发占用）。
采两条替代证据：

1. **结构性论证**：改动只影响 `ok`/`streak`/退避分支；`buf.append(...)` 的触发条件
   由 `while rs.error_code == "0" and rs.next()` 改为"先断言 `error_code == "0"`，再 `while rs.next()`"
   —— **语义恒等**（不满足即已抛错）；`todo`/`have`/写盘时机/字段均未动 → 输出集合恒等。
2. **e2e 假 baostock 测试**：断言查询只登录 1 次、无 90s 休眠、无事件时不写缓存文件。

**如实记录：F2 为"分析论证 + 单测"，不是端到端逐位比对。**

### 0.4 附带发现（实测确认，非本轮范围）

`data/round2/adjust_factor_live.parquet` 实测内容：**50 条 / 50 只 code**（全部
`foreAdjustFactor=1.0`）——即 `buf` 只累积**有事件**的股票，无事件的 code **不进缓存**。
而 `have = set(prev["code"])` 只认已缓存 code → **每个账户都会重查自己几乎全部持仓**：

| 项 | 实测/推算 |
|---|---|
| 账户 1（60w）live 查询耗时 | 11:10:53 → 11:17（**约 6 分钟**，含 2~3 次误退避约 3~5 分钟） |
| 四账户合计 | 约 4 次全量重查 ≈ 20~25 分钟，其中误退避白耗约 10~20 分钟 |
| 修复后 | 误退避归零；剩余 ~11 分钟为 4 账户重查（**negative cache 缺陷仍在**） |

→ **建议 Round 61**：negative cache（把"查询成功但无事件"的 code 也记账），
可把四账户 4 次重查压成 1 次。需处理"查询失败不得负缓存"+ 窗口推进语义 + 新增 sidecar。

### 0.5 复现

```bash
uv run pytest tests/test_live_factor_backoff.py -v     # 9 passed
uv run ruff check .
```

