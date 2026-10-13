# Round 75 运营输出降噪（探测前置 / 静音 baostock / 回退汇总一行）· 预注册

> 状态：**已预注册 2026-10-13 / 实施中**
> 触发：用户反馈"这打印是怎么打印的，我怎么看不到重点？"——实测一次回退补洞刷出 12 行，
> 其中只有 2 行有意义。
> 代码：`scripts/fetch_daily_incremental.py` + `scripts/r5/daily_update.py` + `scripts/p3/daily_update_p3.py`

---

## 1. 问题（逐行溯源后的三个根因）

实测输出（数据末端 10-09、目标 10-13、10-12 缺失）：

```
== 目标交易日: 2026-10-13 (数据源现有: 2026-10-09, ...) ==
[1/2] 补 2026-10-13 行情(全市场约20-30分钟)...
共 3409 只, 2026-10-13 已有 0, 已暂存 0, 待补 3409 (间隔 1.0s)     ← ① 顺序反了
login success!                                                      ← ③ baostock 库自己打的
⚠️ 数据源尚未发布 2026-10-13 的行情 (抽样探测为空), 跳过本轮
logout success!                                                     ← ③
⚠️ 2026-10-13 数据源未发布, 仍以 2026-10-09 为准                     ← 误导!
  → 回退探测中间洞 2026-10-10: 补数据源最新日的下一交易日...          ← ② 每天整套走一遍
共 3409 只, ... 待补 3409 (间隔 1.0s)                                ← ①
login success! / ⚠️ ... / logout success!                            ← ②③
  → 回退探测中间洞 2026-10-11: ...
  → 回退探测中间洞 2026-10-12: ...
共 3409 只, 2026-10-12 已有 0, 已暂存 0, 待补 3409 (间隔 1.0s)
login success!
```

| 根因 | 说明 |
|---|---|
| **① 顺序反了** | `update_date` 先算完整 todo 并打印"待补 3409"，**再**探测；探测为空就白打印 |
| **② 每个自然日整套走一遍** | `backfill_missing` 逐日调 `update_date` → 每日各 1 次 login/logout + 一组"待补" |
| **③ baostock 自带打印** | `login success!`/`logout success!` 来自库本身（`baostock/login/loginout.py:86,152`），非我们的代码 |

**真正重要的信息根本没打印出来**："找到了 10-12（已发布的交易日），现在开始抓，约 60~90 分钟"。

---

## 2. 规则（定死）

**只改打印与探测顺序，不改任何写盘/抓取/账务逻辑。**

1. `fetch_daily_incremental` 新增 `_login/_logout`：用 `contextlib.redirect_stdout` **静音
   baostock 自带的 login/logout 打印**（错误信息仍从返回的 `error_code/error_msg` 读，不丢）；
2. `update_date` **探测前置**：登录 → 探测 → 未发布则**只回一行**并返回；
   已发布才计算 todo，并打印一行 `▶ 补 <日期>: 待补 N 只 | 间隔 Ps | 预计约 T 分钟`；
   完成打印一行 `✅ <日期> 完成: 现共 N 行`；
3. 新增 `probe_dates(days)`：**一次登录**探完多日；
4. 新增 `fill_days(cands, label)`：一次探完 → **一行汇总**（哪些无行情、需补哪些）→
   只对已发布日调 `update_date`；所有 print 都是 `flush=True`（R72 的 flush 纪律）；
5. `daily_update` / `daily_update_p3` 的 `backfill_missing`、`fill_missing_days` 改用 `fill_days`；
6. 删掉误导的 `⚠️ <目标日> 数据源未发布, 仍以 X 为准`，改为
   `目标日 <tgt> 尚未发布 → 回退补历史缺失交易日（最终以补到的最新日为准）`。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **U1 未发布只回一行** | 对未发布日，`update_date` 的输出**恰为 1 行**，且**不含"待补"**；判别力：旧实现输出含"待补 3409" | 去掉最刺眼的误导 |
| **U2 baostock 打印被静音** | 假 baostock 的 `login()`/`logout()` 各 `print("login success!")`/`("logout success!")` → 新输出**不含**这两串；判别力：不静音时必然含 | 区分"库噪音"与"我们的输出" |
| **U3 回退只汇总一行** | 候选 3 天（2 天无行情 + 1 天已发布）→ `fill_days` 汇总输出**恰为 1 行**，且该行同时含"无行情"与"需补 10-12" | 重点可见 |
| **U4 写盘结果不变** | 同场景下走**真实 `main()` 流程**，最终面板日期集合与旧逻辑**完全一致**（含"今天已发布 + 昨天缺失 → 昨天必须被补"） | 降噪不得改行为 |
| **U5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **静音是全局的**：`redirect_stdout` 会吞掉 `login/logout` 期间的**一切** stdout
   （包括潜在的服务端提示）——但 `error_code/error_msg` 仍被检查并打印，且本轮不引入 `--verbose`；
2. **探测次数略增**：`probe_dates` 对每个候选日探 5 只（原每日本来也要探 5 只），
   但**登录次数从 N 次降到 1 次**；
3. **日期标签用"月-日(周X)"**：跨年场景下会缺年份（如 12-31→01-01 的洞）——本轮如实记录，
   不做年份补全（运营中回退跨度不会跨年）。

---

## 5. 非目标

- 不改 `--chart`/mark/账务；
- 不引入 `--verbose` 开关（把库噪音放回来）——如需要另开一轮。

---

## 6. 实施

`scripts/fetch_daily_incremental.py`（静音 + 探测前置 + `probe_dates` + `fill_days`）
→ `scripts/r5/daily_update.py`、`scripts/p3/daily_update_p3.py`（改用 `fill_days` + 文案）
→ `tests/test_output_quiet.py` → ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-13 ｜ `scripts/fetch_daily_incremental.py` + `scripts/r5/daily_update.py`
> + `scripts/p3/daily_update_p3.py` + `tests/test_output_quiet.py`

### 0.0 总判定：**✅ 通过（U1-U5 全过）**

| 判据 | 结果 |
|---|---|
| **U1 未发布只回一行** | ✅ 未发布日输出**恰 1 行**、**不含"待补"**（判别力：旧实现会先打印"共 3409 只…待补 3409"） |
| **U2 baostock 打印被静音** | ✅ 假 baostock 的 `login/logout` **确实会 print**（已单独验证），但 `update_date` 输出中**不含** `login success!`/`logout success!` |
| **U3 回退只汇总一行** | ✅ 3 个候选日（2 无行情 + 1 已发布）→ 汇总**恰 1 行**，同时含"无行情"与"需补 10-12(一)"，并标出星期；全文只出现 1 次"待补" |
| **U4 写盘结果不变** | ✅ 端到端 `main()`：数据末端 10-09 + 昨天(10-12)缺失 + 今天(10-13)已发布 → `fetched == ['2026-10-13','2026-10-12']`、最终面板 `{10-09,10-12,10-13}`、mark 基于最新日；**判别力**：关掉补洞后 10-12 必然丢失 |
| **U5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **108 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 真实输出演示（场景：10-12 漏拉 + 10-13 已发布）

用**真实代码路径**（`main → fill_missing_days → fill_days → probe_dates → update_date`，
只把网络/路径换成假实现）实测输出：

```
== 目标交易日: 2026-10-13 (数据源现有: 2026-10-09, 系统日期: 2026-10-13 周二) ==
[1/2] 检查目标交易日 2026-10-13 …
  ▶ 补 2026-10-13: 待补 20 只 | 间隔 1.0s | 预计约 1 分钟
  ✅ 2026-10-13 完成: 现共 60 行 (按年分区原子写)
  中间洞: 10-10(六)、10-11(日) 无行情 | ▶ 需补 10-12(一)
  ▶ 补 2026-10-12: 待补 20 只 | 间隔 1.0s | 预计约 1 分钟
  ✅ 2026-10-12 完成: 现共 80 行 (按年分区原子写)
[2/2] 数据守卫 2026-10-12 20 行 (100.0% vs 基线)
四账户 mark...
```

对比改前：**同样场景 12+ 行 → 现在 8 行**，且"**要抓哪天、多久**"变成显式一行；
库的 6 行 `login/logout success!` 全部消失。

### 0.2 顺带发现并修复的问题

**P3 的 `daily_update_p3.py::main` 仍是 R73 之前的结构** ——
`backfill_missing` 只在"目标日未发布"分支内调用，**"今天已发布 + 昨天缺失"时 P3 不会补洞**
（R5 已在 R73 修好，P3 漏了）。本轮已把 P3 的流程对齐 R5（`have0` + 无条件 `fill_missing_days`）。

### 0.3 诚实边界

1. **静音是全局的**：`redirect_stdout` 会吞掉 `login/logout` 期间的一切 stdout；
   但 `error_code/error_msg` 仍被检查并打印。未引入 `--verbose` 开关；
2. **日期标签用"月-日(周X)"**：跨年回退会缺年份（运营中回退跨度不跨年）；
3. **探测次数略增**（每个候选日 5 只），但**登录次数从 N 次降到 1 次**。

### 0.4 补正（同一轮内自查发现，重要）

**R75 主提交是在 4 个测试失败的情况下提交的** —— 我的 shell 脚本没用 `&&` 串联，
`git commit` 在 `pytest` 报 `4 failed` 后照样执行了。**这是纪律失误**，随即修正如上。

**失败原因**：R73 的 4 个测试 mock 的是 `du.update_date`，但 R75 把接缝移到了
`du.fill_days`（内部调 `fdi.update_date` + `probe_dates`）→ 这 4 个测试**真的去连了
baostock**（默认测试耗时 4s → **583s**）。

**修正**：把这 4 个测试的 mock 接缝改到 `du.fill_days`，断言"候选日集合"（这才是
`fill_missing_days` 的职责边界）；"已发布才真抓 / 未发布只回一行"由 `test_output_quiet.py` 覆盖。
修正后该文件 **1.9s** 跑完（583s → 1.9s，证明网络调用消失）。

**数据损伤核查**：失控期间真跑了 `update_date("2026-10-09")`，结论是**零损伤** ——
`full_daily` 最大日期仍 10-09（3183 行）、账本未变；只在盘上留了一个 **0 行 staging**
（那 226 只当天全是 `tradestatus=0`，过滤后为空）。已删除，并顺手补上"过滤为空时不留
空 staging"的一行清理 + 对应测试 `test_全部停牌时不留空staging`。

### 0.5 复现

```bash
uv run pytest tests/test_output_quiet.py -v      # 5 passed
.venv/bin/python tmp/demo_quiet_output.py        # 打印上面的真实输出
```

