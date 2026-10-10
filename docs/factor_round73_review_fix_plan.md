# Round 73 R72 代码 Review 修复（登录崩栈 / 单只探测误判 / 中间数据洞）· 预注册

> 状态：**已预注册 2026-10-10 / 实施中**
> 来源：R72 的代码 review（用户要求）。三个问题都在 **10-09 运营的关键路径**上。
> 代码：`scripts/fetch_daily_incremental.py` + `scripts/r5/daily_update.py`

---

## 1. 三个问题（review 结论）

### P1 登录失败用 `assert` → 整个 `daily_update` 抛栈崩溃

```python
lg = bs.login()
assert lg.error_code == "0", lg.error_msg      # 被限流时抛 AssertionError
```

10-08 实测被限流（`10001011`）时正是这里抛栈，`daily_update.py:149` 无 try/except
→ 一键流程整体崩掉。与 R72"被限流不丢进度、重跑续传"的目标自相矛盾。

### P2 单只探测用 `codes[0]` → 可能整天静默跳过

```python
probe = bs.query_history_k_data_plus(codes[0], "date", ...)
if not (...): return 0                          # 整天跳过
```

用**字母序第一个** code 代表"全市场是否已发布"。实测 **227/3409 只 code 在某日常无行情**
（停牌/退市）→ 首只一旦停牌即误判"未发布"，整天静默跳过（返回 0，调用方无感）。

### P3 `daily_update` 发现不了中间缺失的交易日

`target_date` 只试"今天"；数据止于 10-08、今天 10-10 时会**直接抓 10-10**，
而 `backfill_missing` 只在"目标日未发布"分支内调用
→ 中断留下的中间交易日（如 10-09）**永久跳过**。R72 引入 staging 后此风险被放大。

---

## 2. 规则（定死）

1. **P1**：登录失败改为优雅返回 —— 打印 `error_code`/`error_msg` 并 `return 3`
   （契约仍为 `0/3`，且**不发起任何请求**）；
2. **P2**：探测改为**按步长抽样 5 只**（跨 sh./sz. 分散），**任一有数据**即视为已发布；
3. **P3**：`daily_update.main` 改为**无条件**调用 `backfill_missing(tgt, have)`
   （不再只在"目标日未发布"分支内）；
4. **P4**：更正 R72 §0.2 中"可 `--config` 调 pause"的说法（两个脚本都无 `--config` 入口，
   只能 `QUANT_CONFIG` 环境变量或改 `config/default.yaml`）。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **S1 登录失败不崩** | 假 baostock `login()` 返回非 0 → `update_date` **返回 3**、**零查询**、无异常抛出 | P1 |
| **S2 探测抽样** | 假 baostock：首只无数据、第 3 只有 → 判定"已发布"（`update_date` 继续抓）；判别力：旧写法（只看首只）必然误判为未发布 | P2 |
| **S3 中间洞必补** | 假 `update_date`/`data_max_date`：`have=10-08, tgt=10-10`，10-09 为交易日 → **`update_date("2026-10-09")` 必被调用**；`main` 中 `backfill_missing` **不在** `if tgt > have:` 分支内（结构断言） | P3 |
| **S4 文档更正** | R72 §0.2 不再出现"可 `--config`"的错误说法 | P4 |
| **S5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **抽样探测仍是概率性**：5 只全停牌的理论概率极低但非零（抽样跨市场分散后进一步下降）；
2. **P3 会为每个缺失自然日调用一次 `update_date`**（含周末/节假日，各一次 login+探测）：
   跨度大时多几次登录；真实缺失交易日则各触发一次全市场补数（正确但慢）；
3. **未改 `backfill_missing` 的逐日探测策略**（保持既有行为，仅改调用时机）。

---

## 5. 非目标

- 数据源切换/多源兜底；
- `fetch_full_market.py`。

---

## 6. 实施

`scripts/fetch_daily_incremental.py`（P1+P2）→ `scripts/r5/daily_update.py`（P3）
→ `tests/test_review_fixes_r73.py` → 更正 R72 文档（P4）→ ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-10 ｜ `scripts/fetch_daily_incremental.py` + `scripts/r5/daily_update.py`
> + `tests/test_review_fixes_r73.py` + R72 文档更正

### 0.0 总判定：**✅ 通过（S1-S5 全过）**

| 判据 | 结果 |
|---|---|
| **S1 登录失败不崩** | ✅ 假 baostock `login()` 返回 `10001011` → `update_date` **返回 3**、**零查询**、无异常、不留空 staging（旧写法在此抛 `AssertionError` 崩掉整个 `daily_update`） |
| **S2 探测抽样** | ✅ 首只无数据、第 6 只有 → 判定"已发布"（等距抽样 `[0,2,5,8,11]`，探测到第 3 只即命中）；**判别力**：旧写法（只看首只）必然误判为未发布 → 整天静默跳过 |
| **S3 中间洞必补** | ✅ 新增 `fill_missing_days(start, end)`：**逐自然日**比对 `_panel_dates()`，只对**面板里确实缺**的日期调 `update_date`。单测：跨 10-08→10-12 → 调 3 次（10-09/10/11）；已有的日期不重抓；端点相同/倒退 → 0 次；结构断言 `main` 顶层无条件调用 |
| **S4 文档更正** | ✅ R72 §0.2 已改：本脚本与 `daily_update.py` **无 `--config` 入口**，调大 `pause` 需 `QUANT_CONFIG` 或改 `config/default.yaml` |
| **S5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **94 passed**（默认）+ **5 passed**（`-m slow`）；`daily_update.py --table` 冒烟正常 |

### 0.1 改动（4 处）

1. **P1**：`bs.login()` 的 `assert` → `if lg.error_code != "0": print(...); return 3`；
2. **P2**：新增 `_probe_published(bs, codes, date_s, n=5)` —— **等距抽样且两端都取到**，
   任一有数据即视为已发布；
3. **P3**：`daily_update.main` 把 `backfill_missing(tgt, have)` 提到顶层**无条件**调用
   （原只在"目标日未发布"分支内）；
4. **P4**：更正 R72 §0.2 的 `--config` 说法。

### 0.2 实施中修正的自身缺陷（两处，均由自查/单测暴露）

**① 抽样首版**用 `codes[::step][:n]`：`step = len(codes)//n` 会**系统性跳过近一半**索引
（如 12 只、n=5 → 只取偶数位），且**覆盖不到尾部**。
改为 `idx = [i*(len-1)//(k-1) for i in range(k)]`（等距、两端包含）。

**② P3 初版无效（重要，已纠正）**：初版只是把 `backfill_missing(tgt, have)` 提到 `main` 顶层
无条件调用 —— 但**这解决不了真正的中断场景**：

> 数据止于 10-08，今天跑时 `update_date("2026-10-12")` **成功** → `have` 直接变成 10-12
> → 此时 `have == tgt`，`backfill_missing` **一次都不会调用**，10-09/10-10 的洞照旧永久留下。

且 `backfill_missing` 内部用 `data_max_date()` 推进指针，**当末端已在前方时会直接跳过去**。
故改为新增 `fill_missing_days(have0, data_max_date())`：**逐自然日检查面板里是否真的缺**，
不依赖任何"末端推进"假设。判别力测试专门断言了"旧写法在此情形零调用、新写法 3 次调用"。

### 0.3 诚实边界

1. 抽样探测仍是**概率性**：5 只全停牌的理论概率极低但非零（已跨市场分散降低）；
2. **P3 会为每个缺失自然日调用一次 `update_date`**（含周末/节假日各一次 login+探测）；
   真实缺失交易日则各触发一次全市场补数（正确但慢）；
3. 未改 `backfill_missing` 的逐日探测策略本身（仅改调用时机）。

### 0.4 复现

```bash
uv run pytest tests/test_review_fixes_r73.py -v      # 6 passed
.venv/bin/python scripts/r5/daily_update.py --chart  # 一键: 限速补数 + 守卫 + mark + 出图
```

