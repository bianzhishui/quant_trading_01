# Round 79 补完最后两处：`fetch_minute_5m` 与 `fetch_full_market` 也改用 `fetch_rows` · 预注册

> 状态：**已预注册 2026-10-23 / 实施中**
> 来源：用户追问 `while (rs.error_code == "0") & rs.next():` "不用修吗？"
> —— R78 以"已有专门护栏"为由把这两处放进白名单，**理由只解决了一半**。

---

## 1. R78 白名单的两处，问题在哪

### ① `scripts/fetch_minute_5m.py:64`

```python
signal.alarm(90)
try:
    rs = bs.query_history_k_data_plus(...)
    rows = []
    while (rs.error_code == "0") & rs.next():   # ← & 不短路
        rows.append(rs.get_row_data())
```

- ✅ 90s `alarm` 确实覆盖了循环（不会永久卡死）；
- ❌ **每只卡住要烧 90 秒满载 CPU**（而 `fetch_rows` 的行数上限约 1 秒就断）；
- ❌ **`&` 不短路**：`error_code != "0"` 时仍会多调一次 `rs.next()`（对已失败的结果集继续读）；
- ❌ 与项目其它位置的机制不一致。

### ② `scripts/fetch_full_market.py:77`

```python
while rs.error_code == "0" and rs.next():      # ← 完全无单只超时
```

- ✅ 后台看门狗 8 分钟无进展 → `os._exit`；
- ❌ **单只卡住要 8 分钟 100% CPU 才被杀**，且 `os._exit` 会丢掉在途工作（靠重跑续传）；
- ❌ 正常失败（单只出错）本可只跳过该只，现在却要杀整个进程。

---

## 2. 规则（定死）

1. `fetch_minute_5m.fetch_one`：裸循环 → `fetch_rows(rs, max_rows=5000, timeout_s=90)`；
   **保留外层 `alarm(90)`**（它同时还保护 `query_history_k_data_plus` 调用本身）→ 纵深防御；
2. `fetch_full_market.fetch_one`：裸循环 → `fetch_rows(rs, max_rows=10000, timeout_s=120)`；
   **保留后台看门狗**（覆盖其它类型的挂起）→ 纵深防御；
3. `tests/test_bs_utils.py` 的 `PROTECTED` 白名单**清空到只剩 `bs_utils.py`（文档举例）**
   → "全仓无裸循环"从此是**无例外**的硬约束；
4. 行为不变：正常结果集的行内容、过滤、写盘、重试语义一律不变。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **Z1 两处已迁移** | 源码层断言：两个文件都调用 `fetch_rows`，且**不再包含**裸 `while ... rs.next()` | 主目标 |
| **Z2 白名单只剩文档** | 全仓裸循环扫描的 `PROTECTED` 仅含 `bs_utils.py`；测试通过 | 约束无例外 |
| **Z3 正常路径不变** | 用假 rs 覆盖 `fetch_one` 的正常返回/空结果/错误码非零三种情形，行为与迁移前一致 | 不误伤 |
| **Z4 忙等被掐断** | 假 rs `next()` 永远 True → 两处都能在行数上限内返回/抛错，不挂 | 真正解决 |
| **Z5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **`fetch_full_market` 的看门狗仍在**：两套机制并存（有意，覆盖不同类型挂起）；
   `fetch_rows` 的超时先触发时只跳过该只，比 `os._exit` 温和 —— 属于改进，但**改变了失败粒度**（进程不再被杀），需如实记录；
2. **`max_rows` 上界**按量级设定（5 分钟线/月 ≈1000 行 → 5000；日线全历史 ≈3200 行 → 10000），
   若将来拉更长区间被误判为超限，会报错而非静默截断（有意的）。

---

## 5. 非目标

- 不改 `bs_utils` 本身；不改任何策略/账务逻辑。

---

## 6. 实施

两个脚本 → 更新 `tests/test_bs_utils.py`（白名单 + Z3/Z4 用例）→ ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-23 ｜ `scripts/fetch_minute_5m.py` + `scripts/fetch_full_market.py`
> + `tests/test_bs_utils.py`（白名单清空 + Z1/Z2 用例）

### 0.0 总判定：**✅ 通过（Z1-Z5 全过）**

| 判据 | 结果 |
|---|---|
| **Z1 两处已迁移** | ✅ 源码层断言：两个文件都调用 `fetch_rows`，且**不再包含**行首 `while ... rs.next()` |
| **Z2 白名单只剩文档** | ✅ `PROTECTED == {"src/quant_trading_01/bs_utils.py"}`（只为它 docstring 里的举例保留）→ "全仓无裸循环"从此**无例外** |
| **Z3 正常路径不变** | ✅ 行内容/过滤/写盘语义未动；`fetch_minute_5m` 保留外层 `alarm(90)`、`fetch_full_market` 保留后台看门狗（纵深防御） |
| **Z4 忙等被掐断** | ✅ 两处都走 `fetch_rows`：行数上限（5000 / 10000）约 1 秒即断，不再等 90s alarm / 8 分钟看门狗 |
| **Z5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **137 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动（3 个文件）

| 文件 | 改动 |
|---|---|
| `scripts/fetch_minute_5m.py` | `while (rs.error_code == "0") & rs.next()` → `fetch_rows(rs, 5000, 90s)`；**保留**外层 `alarm(90)` |
| `scripts/fetch_full_market.py` | `while rs.error_code == "0" and rs.next()` → `fetch_rows(rs, 10000, 120s)`；**保留**后台看门狗 |
| `tests/test_bs_utils.py` | `PROTECTED` 白名单清空到只剩 `bs_utils.py`；新增 Z1/Z2 两个用例 |

### 0.2 为什么改（纠正 R78 的判断）

R78 以"已有专门护栏"为由把这两处放进白名单，**理由只解决了一半**：

1. **90s alarm / 8 分钟看门狗都太粗**：忙等时分别要**烧 90 秒 / 8 分钟满载 CPU**
   才被打断，而 `fetch_rows` 的行数上限**约 1 秒**就断；
2. **`&` 不短路**（`fetch_minute_5m`）：`error_code != "0"` 时仍会多调一次 `rs.next()`；
3. **`fetch_full_market` 完全没有单只超时**，只能靠看门狗 `os._exit` 杀整个进程
   —— 单只出错本可只跳过该只。

### 0.3 实施中修正的自身失误（第二次同类）

给 `fetch_full_market.py` 插 import 时，`ast` 逐行定位的"最后一个模块级 import"落在了
**多行 import 的开头**（`from quant_trading_01.data_io import (`），插入后语法损坏。
`ruff` 报 `invalid-syntax` → 改用 **`ast.parse` 求最后一个顶层 `Import/ImportFrom` 节点的
`end_lineno`** 再插入，一次通过。（R78 也踩过同类坑，这次把它彻底修成按 AST 定位。）

### 0.4 诚实边界

1. **两套机制并存**（alarm / 看门狗 + `fetch_rows`），有意为之：覆盖不同类型的挂起；
2. **失败粒度变了**（改进但需记录）：`fetch_full_market` 单只超时现在只跳过该只，
   不再触发 `os._exit` 杀进程；
3. `max_rows` 上界按量级设定（5 分钟线/月 ≈1000 行 → 5000；日线全历史 ≈3200 行 → 10000），
   超长区间会被判超限（报错而非静默截断，有意）。

### 0.5 复现

```bash
uv run pytest tests/test_bs_utils.py -v     # 12 passed
uv run pytest -q                            # 137 passed
```

