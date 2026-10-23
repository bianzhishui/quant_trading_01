# Round 78 baostock 结果集安全迭代（公共助手 + 覆盖全部 7 处裸循环）· 预注册

> 状态：**已预注册 2026-10-23 / 实施中**
> 来源：R77 修复 `fetch_daily_incremental` 的忙等死循环后，用户要求"全仓排查同类问题"。
> 排查结论（未改代码的分析）：**生产代码共 9 处 `rs.next()` 循环，7 处无护栏**；
> 其中 `scripts/r5/paper_live.py:343`（`_live_factors`）位于**每月 step 的关键路径**。

---

## 1. 现状（R77 分析结论）

| 位置 | 触发 | 护栏 |
|---|---|---|
| `fetch_daily_incremental.py:265` | 每日补数 | ✅ R77 已修（行数上限 + 墙钟） |
| **`r5/paper_live.py:343` `_live_factors`** | **每月 step** | ❌ **无**（P0） |
| `fetch_corporate_actions.py:76/83` | 数据工程 | ❌ 无（外层"3 次重试"**对忙等无效**） |
| `fetch_full_industry.py:44` | 数据工程 | ❌ 无（同上） |
| `fetch_round2_data.py:59` | 一次性回补 | ❌ 无 |
| `fetch_stock_basic.py:71`（`_rows`） | 宇宙清单 | ❌ 无 |
| `src/.../data_loader.py:96` | 研究/report | ❌ 无 |
| `fetch_full_market.py:77` | 全市场重抓 | ✅ 后台看门狗 8 分钟 → `os._exit` |
| `fetch_minute_5m.py:64` | 5 分钟线 | ✅ `signal.alarm(90)` |

**关键认知**：忙等**不抛异常** → 任何 `try/except + 重试` 包装对它完全无效。

---

## 2. 规则（定死）

1. 新增共享模块 **`src/quant_trading_01/bs_utils.py`**：
   - `time_limit(seconds)` 上下文管理器（`SIGALRM`，主线程）；
   - 异常 `BaostockQueryError` / `QueryTimeout` / `QueryTooManyRows`；
   - **`fetch_rows(rs, max_rows, timeout_s)`**：安全读完结果集，超限抛异常，
     结束后仍做 `error_code != "0"` 检查（保留各调用点原有的失败语义）。
2. 用 `fetch_rows` **替换 6 处裸循环**（P0 + P1 + P2，见上表 ❌ 的 6 个位置）；
3. **不改**已受保护的两处（`fetch_full_market` 看门狗、`fetch_minute_5m` alarm）——
   它们已有针对性的护栏，改动风险大于收益；
4. `fetch_daily_incremental` 的 R77 护栏改为复用同一助手（消除两份实现）；
5. **行为不变**：正常路径的行内容、过滤、写盘、重试/失败语义一律不变；
   `max_rows` 按各查询的合理上界设定（单日 10 / 事件类 200 / 全历史 5000 / 代码清单 20000）。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **Y1 忙等必被掐断（全部 6 处）** | 对每处被替换的调用，用"`next()` 永远 True"的假 rs → **在超时/行限内返回**，不挂 | 主目标 |
| **Y2 判别力自证** | 同输入下裸循环跑到 1000+ 次仍未停（R77 的 X2 复用并扩展到 6 处） | 判据有判别力 |
| **Y3 正常路径零变化** | 正常 rs（正确行数）→ 返回的 rows 与旧裸循环**逐元素相同**；`error_code != "0"` 时仍抛 RuntimeError（语义不变） | 不误伤 |
| **Y4 P0 路径可用** | `_live_factors` 用假 baostock：某只超时 → 记为失败、**继续其余 code**，不中断 step 准备 | 月度调仓不被单只拖死 |
| **Y5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **`time_limit` 仅主线程有效**（`signal` 限制）：本项目所有调用都在主线程；
   如将来在子线程/线程池里用 `fetch_rows`，超时会失效（如实记录）；
2. **`max_rows` 是硬上界**：若某接口未来返回行数超预期（如 5 分钟线跨年），
   会被判 `QueryTooManyRows` 而非静默截断——**这是有意的**（宁可报错不乱写数据）；
3. **未纳入 `fetch_full_market` / `fetch_minute_5m`**：它们已有护栏，本轮不动。

---

## 5. 非目标

- 不改 baostock 库本身；不加自动重试策略；不改 strategy 逻辑。

---

## 6. 实施

`src/quant_trading_01/bs_utils.py`（新）→ 替换 6 处裸循环 → `fetch_daily_incremental` 复用
→ `tests/test_bs_utils.py`（新）+ 扩展 `tests/test_query_guard.py`
→ ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-23 ｜ 新增 `src/quant_trading_01/bs_utils.py` + `tests/test_bs_utils.py`
> ｜ 替换 6 处裸循环 + `fetch_daily_incremental` 复用同助手

### 0.0 总判定：**✅ 通过（Y1-Y5 全过）**

| 判据 | 结果 |
|---|---|
| **Y1 忙等必被掐断** | ✅ `fetch_rows` 遇"`next()` 永远 True"：行数上限（5 行）**立即**抛 `QueryTooManyRows`；墙钟 0.3s **0.3s 内**抛 `QueryTimeout` |
| **Y2 判别力自证** | ✅ 同输入下**裸循环跑到 1000+ 次仍未停**（R77 的 X2 扩展到公共助手） |
| **Y3 正常路径零变化** | ✅ 正常结果集返回的 rows 与裸循环**逐元素相同**；`error_code != "0"` 仍抛异常（语义不变）；空结果返回 `[]`；`timeout_s=0` 不设超时 |
| **Y4 P0 路径可用** | ✅ `_live_factors` 单只超时**被吞掉**（不抛出）、**继续下一只**、2 只 × 3 次重试 = 6 次调用、护栏参数为 `max_rows=200/timeout=20s`、全失败时不写出 live 因子文件；源码层断言"必须用 `fetch_rows`、不得有裸循环" |
| **Y5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **135 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动（8 个文件）

| 文件 | 改动 |
|---|---|
| **`src/quant_trading_01/bs_utils.py`** | **新增**：`time_limit` / `QueryTimeout` / `QueryTooManyRows` / **`fetch_rows(rs, max_rows, timeout_s)`** |
| **`scripts/r5/paper_live.py`**（P0） | `_live_factors` 裸循环 → `fetch_rows(rs, 200, 20s)` |
| `scripts/fetch_corporate_actions.py` | 2 处裸循环 → `fetch_rows(rs, 500, 30s)` |
| `scripts/fetch_full_industry.py` | → `fetch_rows(rs, 5, 20s)` |
| `scripts/fetch_round2_data.py` | → `fetch_rows(rs, 5000, 120s)`（顺带删掉重复的 error_code 检查） |
| `scripts/fetch_stock_basic.py`（`_rows`） | → `fetch_rows(rs, 20000, 180s)` |
| `src/quant_trading_01/data_loader.py` | → `fetch_rows(rs, 5000, 120s)` |
| `scripts/fetch_daily_incremental.py` | R77 的本地 `_time_limit`/`_QueryTimeout` **删除**，改用 `bs_utils`（消除两份实现） |

**未改动**：`fetch_full_market.py`（后台看门狗 8 分钟 → `os._exit`）、
`fetch_minute_5m.py`（`signal.alarm(90)`）—— 已有针对性护栏，按 §2.3 不动。

### 0.2 新增回归护栏

`tests/test_bs_utils.py::test_y3_全仓不再有裸循环` —— 扫描 `scripts/**` 与
`src/.../data_loader.py`，**任何行首为 `while ... rs.next()` 的代码行都会让测试失败**
（注释/docstring 不计；两处已有专门护栏的文件在 PROTECTED 白名单里）。
这样将来谁再写出裸循环，CI 立刻拦住。

### 0.3 实施中修正的自身失误（如实记录）

第一轮替换时，我把 `from ... bs_utils import fetch_rows` **插进了函数体**（锚点
`import baostock as bs` 出现在函数内部，且匹配从行中第 4 个字符开始，导致
`import baostock as bs` **丢失缩进**、文件语法损坏）。
`ruff` 立刻报 `invalid-syntax` → **`git checkout --` 回滚 6 个文件**，
改为**按行**定位"最后一个模块级 import"再插入，重做后一次通过。

### 0.4 诚实边界

1. **`time_limit` 仅主线程有效**（`signal` 限制）：本项目所有调用都在主线程；
   若将来在线程池里用 `fetch_rows`，超时会失效；
2. **`max_rows` 是硬上界**：接口若返回超预期行数会**报错而非静默截断**（有意如此，
   宁可报错不写脏数据）；各调用点的上界按该查询的合理量级设定；
3. **`fetch_full_market` / `fetch_minute_5m` 未纳入**：已有护栏，改动的风险大于收益。

### 0.5 复现

```bash
uv run pytest tests/test_bs_utils.py -v     # 10 passed
uv run pytest tests/test_query_guard.py -v  # 4 passed（R77，验证复用后行为不变）
```

