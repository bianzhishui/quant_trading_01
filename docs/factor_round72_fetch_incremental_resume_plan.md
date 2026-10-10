# Round 72 `fetch_daily_incremental` 限速 + 可续传（防再被限流封禁）· 预注册

> 状态：**已预注册 2026-10-10 / 实施中**
> 触发：2026-10-08 实测——标准补数脚本跑到 **1000/3409** 就把出口 IP 打进
> baostock 黑名单（`error_code=10001011`），而它"全部抓完才原子落盘"→ **1000 只全部作废**。
> 用户要求：**仍走 `daily_update.py` 一键路径**，改造其内部抓取逻辑。
> 代码：`scripts/fetch_daily_incremental.py::update_date`（`daily_update.py` 导入直调）

---

## 1. 问题

```python
time.sleep(0.1)          # 硬编码: 约 3~10 请求/秒, 触发服务端限流
...
if not buf: return 0
new = pd.concat(buf, ignore_index=True)
write_full_daily(new)    # 全部抓完才写 —— 中断即全部作废
```

两个缺陷：
1. **无节流**：0.1s 间隔把速率推到服务端容忍线之上；
2. **无断点**：`buf` 全在内存，会话失效/被封后重跑从第一只开始。

`daily_update.py` 侧**无需改动**：它已处理 `rc != 0`，并用 `completeness_guard`
拒绝"半成品数据"mark（R41 加的门），所以续传能力只要做在 `update_date` 内部即可。

---

## 2. 规则（定死）

**唯一改动 = `update_date` 的节流与落盘策略**；查询字段、过滤口径
（`FIELDS` / `KEEP` / `adjustflag="2"` / 只留 `tradestatus=="1"`）、
最终写入函数（`write_full_daily`）**一律不变**。

1. 新增配置 `fetch.daily_incremental.pause`（默认 **1.0s**，替换硬编码 0.1s）
   与 `stage_batch`（默认 **100**）；
2. 新增 **staging**：`data/fundamental/_stage_daily_<YYYYMMDD>.parquet`
   （`data/fundamental/*` 已 gitignore，不会入库）：
   - 每抓 `stage_batch` 只落一次盘；
   - 重跑时 `todo = 全部 code − 已落盘 − 已 staged` → **断点续传**；
3. 会话失效/被限流（异常含"用户未登录"/`10001011`）→ **保存 staging 并返回 3**；
4. 全部抓完 → `write_full_daily(staging)` 合并（语义不变）+ **删除 staging**；
5. 单只探测逻辑保持不变（数据源未发布则秒退，不写盘）。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **R1 限速生效** | 请求间隔取自 `config.fetch.daily_incremental.pause`（结构断言 + 单测计时）：传 0 或读配置均可控 | 防再被限流 |
| **R2 断点续传** | 假 baostock：抓 3 只后抛"用户未登录" → `rc=3` 且 **staging 落盘 3 只**；再调用 → **只查剩余 2 只** | 主目标 |
| **R3 合并语义不变** | staging 经 `write_full_daily` 落盘后，既有 `(date,code)` 行**逐位不变**（复用 R66 护栏语义） | 防写入行为漂移 |
| **R4 判别力自证** | 同场景下**旧写法（纯内存 buf、失败即丢）续跑查询数 = 全部**，新写法 = 剩余；断言旧行为违规 | R57/R58 教训 |
| **R5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **速率与时长权衡**：`pause=1.0` 使全市场补数约 **60~90 分钟**（原 20~30 分钟），
   但换来"不再被封 + 被封也不丢进度"；若仍被限流，可通过 `--config` 调到 1.5~2.0；
2. **staging 目录会残留**：正常完成会删除；异常中断时保留（**这是续传的依据，故意不移除**），
   运维上可手工清理（已 gitignore）；
3. **未改 `daily_update.py`**：其"守卫拒绝半成品 mark"的行为保持不变（本轮验证 R3/R5 即可）；
4. **不做真实全市场回归**（耗时 1 小时且依赖服务端状态），采假 baostock 单测 + 结构断言。

---

## 5. 非目标

- 换数据源 / 多源兜底；
- `fetch_full_market.py`（全量重抓，不同路径）。

---

## 6. 实施

`config/default.yaml`（2 个新键）→ `scripts/fetch_daily_incremental.py`（节流 + staging）
→ `tests/test_fetch_incremental_resume.py` → ruff + pytest → 提交。

---

## §0 实施结果归档

> 实施 2026-10-10 ｜ `config/default.yaml` + `scripts/fetch_daily_incremental.py`
> + `tests/test_fetch_incremental_resume.py`

### 0.0 总判定：**✅ 通过（R1-R5 全过）**

| 判据 | 结果 |
|---|---|
| **R1 限速生效** | ✅ 请求间隔全部取自 `config.fetch.daily_incremental.pause`（单测：配置 0.37 → `sleep` 值集恰为 `{0.37}`）；源码中 **不再存在** `time.sleep(0.1)` |
| **R2 断点续传** | ✅ 假 baostock 抓 3 只后抛"用户未登录" → `rc=3`、**staging 落盘 3 只**；再调用 → **只查剩余 2 只**、完成后清理 staging、合并后 10-09 共 5 行 |
| **R3 合并语义不变** | ✅ 仍走 `write_full_daily`（`(date,code)` 去重、历史优先），抓取字段/过滤/`adjustflag="2"`/只留 `tradestatus=="1"` 均未改 |
| **R4 判别力自证** | ✅ 同中断场景：**旧写法续跑要重查全部 5 只**（就是"1000 只全部作废"的那种），新写法只查 2 只 |
| **R5 质量门** | ✅ `ruff check .` 0 错误；`pytest` **88 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动（2 处）

1. `config/default.yaml`：`fetch.daily_incremental` 增 `pause: 1.0`（替换硬编码 0.1s）与
   `stage_batch: 100`；
2. `scripts/fetch_daily_incremental.py::update_date`：接节流；每 `stage_batch` 落一次
   staging（`data/fundamental/_stage_daily_<date>.parquet`，已 gitignore）；
   会话失效/被限流 → 保存 staging 并返回 3；全部抓完才 `write_full_daily` 合并 + 清理 staging。

**`daily_update.py` 未改动** —— 它既有 `rc != 0` 处理与 `completeness_guard`（拒绝半成品 mark），
现在会自动获得"被限流不丢进度"的能力。

### 0.2 代价与运维

| | 原 | 现 |
|---|---|---|
| 请求间隔 | 0.1s（~3~10 请求/秒，会被封） | **1.0s**（调大方式：`QUANT_CONFIG=xxx.yaml` 或改 `config/default.yaml`——本脚本与 `daily_update.py` 均**无** `--config` 入口，R73 §P4 更正） |
| 全市场耗时 | 20~30 分钟 | **60~90 分钟** |
| 中断后果 | **全部作废** | **staging 保留，重跑续传** |

staging 正常完成即删除；异常中断时**故意保留**（续传依据），可手工清理。

### 0.3 诚实边界

**未做真实全市场回归**（约 1 小时且依赖服务端状态）：采假 baostock 单测 + 结构断言；
真实效果由 10-09 的实际补数验证（如实记录在运营日志/提交信息里）。

### 0.4 复现

```bash
uv run pytest tests/test_fetch_incremental_resume.py -v   # 4 passed
.venv/bin/python scripts/r5/daily_update.py --chart       # 一键: 限速补数 + 守卫 + mark + 出图
```

