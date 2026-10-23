# Round 77 `rs.next()` 死循环护栏 + 进度可见性（实测卡死 58 分钟 / 100% CPU）· 预注册

> 状态：**已预注册 2026-10-23 / 实施中（阻塞性故障，优先修复）**
> 症状（用户实测）：`daily_update --chart` 启动后一直停在
> `▶ 补 2026-10-22: 待补 3409 只 | 间隔 1.0s | 预计约 91 分钟`，**CPU 100%**，
> staging 文件 mtime 冻结在 08:59、58 分钟零进度。
> 代码：`scripts/fetch_daily_incremental.py::update_date`

---

## 1. 根因

```python
rows = []
while rs.error_code == "0" and rs.next():     # ← 无界循环
    rows.append(rs.get_row_data())
```

会话被限流/连接半断时，baostock 的 `next()` 可能**持续返回 True 但不前进**
→ 无限循环 + `rows` 无限增长 → **100% CPU 空转、永不前进、内存持续吃**。
（AGENTS §8 已记"`rs.next()` 会挂起"，但挂起是 0% CPU；本例是**忙等**，属未覆盖的变体。）

**放大器**：`print_every: 500` → 第一条进度要 ~12 分钟才打印，用户无法区分"忙等"与"正常等待"。

---

## 2. 规则（定死）

1. **行数上限**：单日查询预期 1 行，超过 `max_rows`（默认 **10**）立即中止该只；
2. **单只墙钟超时**：`query_timeout`（默认 **25s**），用 `signal.setitimer` 实现，
   超时抛内部异常 → 记为该只失败并**继续下一只**（不中断整体）；
3. **进度可见性**：`print_every` 500 → **50**（约 1~2 分钟一行）；
4. **行为不变**：正常路径（返回 1 行）的抓取/过滤/写盘逻辑一律不动；
   会话失效仍返回 3 且 staging 保留。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **X1 死循环必被掐断** | 假 baostock 的 `next()` **永远返回 True** → `update_date` 必须**在超时内返回**（不挂），且该只记为失败、继续后续 code | 主目标 |
| **X2 判别力自证** | 同一假实现下，**旧的无界 while 必然超过行数上限**（模拟跑 1000 次仍 True） | 证明判据有判别力 |
| **X3 正常路径不变** | 返回 1 行的正常假实现 → 抓取成功、写入、staging 清理，全流程通过 | 不误伤 |
| **X4 超时后继续** | 第 1 只超时、第 2 只正常 → 第 2 只仍被正确抓入 | 不因单只失败中断整体 |
| **X5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **`signal.setitimer` 只在主线程可用**：本脚本是命令行主线程调用，成立；
   若将来在子线程里调用 `update_date`，超时护栏会失效（如实记录）；
2. **超时/超行数的 code 会被跳过**（该只当天数据缺失），需下次重跑或人工补；
   `fail` 计数会体现（失败 >0 时打印一行汇总）；
3. 未改 baostock 库本身，只是**给我们的循环加上限**。

---

## 5. 非目标

- 不换数据源、不做重试退避策略；
- 不改 `step`/回测路径。

---

## 6. 实施

`config/default.yaml`（`print_every: 50`、新增 `query_timeout`/`max_rows`）
→ `scripts/fetch_daily_incremental.py`（`_time_limit` 上下文管理器 + 循环护栏）
→ `tests/test_query_guard.py` → ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-23 ｜ `config/default.yaml` + `scripts/fetch_daily_incremental.py`
> + `tests/test_query_guard.py`

### 0.0 总判定：**✅ 通过（X1-X5 全过）**

| 判据 | 结果 |
|---|---|
| **X1 死循环必被掐断** | ✅ 假 `next()` 永远 True → 行数上限（3 行）**立即掐断**、`update_date` 正常返回；另测"上限设极大 + 墙钟超时 0.3s"也能兜底（**0.3s 返回**） |
| **X2 判别力自证** | ✅ 同输入下**旧的无界 while 跑到 1000+ 次仍未停**（正是 100% CPU 卡死的成因） |
| **X3 正常路径不变** | ✅ 正常 1 行返回 → 全部 code 入库、staging 清理 |
| **X4 超时后继续** | ✅ 第 1 只忙等被跳过，其余 code **全部照常入库**（不中断整体） |
| **X5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **125 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动（3 处）

1. `config/default.yaml`：`print_every: 500 → **50**`（首条进度从 ~12 分钟缩到 ~1 分钟，
   让"忙等"与"正常等待"立刻可区分）；新增 `query_timeout: 25.0`、`max_rows: 10`；
2. 新增 `_time_limit(seconds)` 上下文管理器（`signal.setitimer` + `SIGALRM`）；
3. `update_date` 的抓取循环：整段查询（含 `rs.next()` 循环）包进 `_time_limit`，
   且 `len(rows) > max_rows` 立即抛 `_QueryTimeout`；该异常**单独捕获** → 记 fail 并
   **继续下一只**（不会被误判成"会话失效"而中断整轮）。

### 0.2 现场处置（重要）

用户当前那个进程仍在**100% CPU 空转**（staging mtime 冻结在 08:59，58 分钟零进度）——
**必须先杀掉**（`kill <pid>` 或 Ctrl-C），再重跑。staging 里的 **87 只进度不会丢**，
重跑会自动跳过并从第 88 只继续。

### 0.3 诚实边界

1. **`signal.setitimer` 只在主线程有效**：本脚本是命令行主线程调用（成立）；
   若将来在子线程里调 `update_date`，超时护栏失效；
2. **超时/超行数的那只当天数据会缺失**：`fail` 计数会体现（>0 时打印一行汇总），
   需下次重跑或人工补；
3. 未改 baostock 库本身，只是给我们的循环加上限。

### 0.4 复现

```bash
uv run pytest tests/test_query_guard.py -v      # 4 passed（1.1s）
.venv/bin/python scripts/r5/daily_update.py --chart   # 现在每 ~1 分钟一行进度
```

