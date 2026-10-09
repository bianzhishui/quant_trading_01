# Round 64 `bench_base` 重算（基准冻结值 × 当前面板不同源 → 超额虚高 5.2pp）· 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 触发：2026-10-09 首次 R5 `step` 后对账，发现账本 `bench` 与独立复算差 **5.2pp**。
> 代码：`scripts/r5/paper_live.py:529,534` 与 `scripts/p3/paper_live_p3.py:345,350`

---

## 1. 问题（实测证据）

账本存的 `bench_base` 与当前面板重算值**同一日期不同值**：

| 项 | 值 | 隐含池收益(建仓→10-08) |
|---|---|---|
| 账本 `bench_base`（09-18 建账时冻结） | **2.631265** | **−8.37%** |
| 当前面板重算 `bench_lv[2026-09-01]` | **2.490793** | **−3.20%** |

→ 四个 R5 账户的"超额"**虚高约 5.2pp**：

| 账户 | 账户收益 | 账本隐含超额 | **修正后超额** |
|---|---|---|---|
| 60w | −0.53% | +7.84pp | **+2.67pp** |
| 100w | −0.41% | +7.96pp | +2.79pp |
| 300w | −0.29% | +8.08pp | +2.91pp |
| 600w | −0.26% | +8.11pp | **+2.94pp** |

**根因**：`bench` 的定义是 `bench_lv[exec] / bench_base`（第 534 行）。

- 分子 `bench_lv` 由**当前面板**实时算出（`_bench_levels` → `ew_nav(ret, bench, 15e-4)`）；
- 分母 `bench_base` 是 **09-18 建账时冻结**的值（`led.get("bench_base")`）。

而 `data/round2/industry_full.parquet` 的 mtime = **2026-09-22 21:20**，**晚于建账**。
行业映射是 R5 池的必需输入（`common = a ∩ m ∩ f ∩ ind`）→ 池成员逐月变化 → 整条基准路径平移
→ 分子变了、分母没变 → **不同源**。

**已排除的假设**：R33 前的"基准 0 成本"旧口径。0 成本算出 `bench_lv[09-01] = 2.557295`
（≠ 2.631265），故不是成本口径残留。

**独立验证账户侧无错**：用当前面板直接算 09-01 目标组等权持有（09-02→10-08）= **−0.13%**，
与四账户 −0.26%~−0.53%（含费用）吻合 ✅ → 问题只在基准口径。

---

## 2. 规则（定死）

**唯一改动 = 让 `bench` 的分子分母同源**：`bench_base` 每次 `step` 按**当前面板**重算，
取"建账日"（`nav_history[0]["date"]`）当日的 `bench_lv`。

1. 新增可单测的纯函数（放 `scripts/r5/paper_live.py`，供 P3 复用）：

```python
def _rebased_bench_level(bench_lv: dict, build_date, stored_base: float) -> float:
    """按当前面板重算基准基数 → bench 的分子分母同源(数据修订自愈)。"""
    d = pd.Timestamp(build_date)
    if d in bench_lv and float(bench_lv[d]) > 0:
        return float(bench_lv[d])
    return float(stored_base)  # 建账日不在当前 rebs 中 → 回退存值, 不静默篡改
```

2. R5 `step()`：循环外算一次 `bench_base`，替换 `led.get("bench_base", 1.0)`；
   持久化时 `led["bench_base"] = bench_base`（账本自洽）；
3. P3 `paper_live_p3.py`：同样接入（从 R5 导入该 helper，与既有 `_bench_levels` 同源）；
4. **一次性校准已写账本**（4 个 R5；P3 七账户尚未 step，`nav_history` 只有建账行 `bench=1.0`，
   代码修复即覆盖，无需迁移）：
   - 先备份 → 重算 `bench_base` → 按 `bench_lv[date]/bench_base` 重写每条
     `nav_history[i]["bench"]` → 断言 `nav_history[0]["bench"] == 1.0` 不变 →
     断言 `nav`/`cash`/`shares`/`trades` 零改动 → 写入；
5. **不改**任何选股/调仓/成本逻辑。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **J1 同源自洽** | 真实数据：`bench_lv[10-08]/bench_lv[09-01]` = `0.967990`（= −3.20%）写入 `nav_history[1]["bench"]` | 主目标 |
| **J2 判别力自证** | 旧口径（冻结 base 2.631265）必然给出 `0.916313`（−8.37%），与 J1 差 **>5pp**；断言旧值必然被检出 | 防无判别力 |
| **J3 归一化不变** | `nav_history[0]["bench"] == 1.0`；`nav`/`cash`/`shares`/`trades` 逐位不变 | 防迁移误伤 |
| **J4 数据修订自愈** | 把 `bench_lv` 整体乘任意正数 k：新算法结果**不变**（同源比值），旧算法**漂移** | 这才是根治 |
| **J5 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **`bench_base` 语义变化**：从"建账时冻结"变为"每次按当前面板重算"。
   这会**重写历史 `bench` 值**（本轮仅 1 条：`nav_history[1]`）。
   若将来业界/本项目需要"可复现历史 bench"，冻结才合适——但**冻结 + 会变的分子 = 恒定失真**，
   故选择自洽。**已如实记录该取舍**。
2. **迁移只覆盖 R5 四账户**（P3 无需迁移，理由见 §2.4）；`output/p3` 的 bench 值待其首次 step 由代码修复。
3. **未做端到端 step 重跑**（step 已无待处理调仓，重跑是空操作）；
   验证采"纯函数 + 真实面板数值 + 迁移后断言"。
4. **未追查 industry_full 变更的具体内容**（3484 只 vs 旧的 800 只备份文件，无法还原 09-18 状态）。
   本轮修的是"不同源"这一**结构性缺陷**，与哪个数据文件变了无关（J4 即证）。

---

## 5. 非目标

- 重跑历史 `monthly_funds` 的 `月涨`（它由 nav 计算，与 bench 无关，未受影响）；
- 追查 industry_full 09-22 刷新的影响面（R5 历史回测数字是否整体平移）——**建议另开一轮**，
  因为 `fetch_full_industry.py` 是可再生的数据刷新，不应悄悄改动已发布的历史结论。

---

## 6. 实施

`scripts/r5/paper_live.py`（helper + R5 接入）→ `scripts/p3/paper_live_p3.py`（P3 接入）
→ `tests/test_bench_rebase.py` → `tmp/recalibrate_bench.py`（一次性校准，带备份与断言）
→ ruff + pytest → 迁移 R5 四账本 → 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `scripts/r5/paper_live.py` + `scripts/p3/paper_live_p3.py`
> + `tests/test_bench_rebase.py` + 一次性校准 `tmp/recalibrate_bench.py`

### 0.0 总判定：**✅ 通过（J1-J5 全过）**

| 判据 | 结果 |
|---|---|
| **J1 同源自洽** | ✅ `bench_lv[10-08]/bench_lv[09-01]` = **0.967990**（池收益 **−3.20%**），已写入 `nav_history[1]["bench"]` |
| **J2 判别力自证** | ✅ 旧口径（冻结 2.631265）得 **0.916313**（−8.37%），与 J1 差 **5.17pp > 5pp** |
| **J3 归一化不变** | ✅ slow 门通过：4 个 R5 账本 `bench_base` 全部重算、`nav_history[0].bench == 1.0`、每条 bench 与当前面板自洽；`nav`/`cash`/`shares`/`trades`/`last_*` **逐位不变** |
| **J4 数据修订自愈** | ✅ `bench_lv` 整体 ×1.7：新算法比值差 **<1e-12**（免疫），旧算法漂移 **>0.5** |
| **J5 质量门** | ✅ `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） |

### 0.1 改动（3 处）

1. 新增纯函数 `_rebased_bench_level(bench_lv, build_date, stored_base)`（R5 定义，P3 复用）；
2. R5 `step()`：循环外算一次 `bench_base`，替换 `led.get("bench_base", 1.0)`；
   持久化时写回 `led["bench_base"] = bench_base`；
3. P3 `paper_live_p3.py`：同样接入（导入 helper + 循环外重算 + 写回）。

### 0.2 一次性校准结果（4 个 R5 账本，dry-run 先行 + 备份 + 断言）

| 账本 | base 旧 → 新 | 池收益 旧 → 新 | 末条 bench 旧 → 新 |
|---|---|---|---|
| aum60w / 100w / 300w / 600w | 2.631265 → **2.490793** | −8.37% → **−3.20%** | 0.916313 → **0.967990** |

**修正后的真实超额**：

| 账户 | 账户收益 | 修正前（账本） | **修正后** |
|---|---|---|---|
| 60w | −0.53% | +7.84pp | **+2.67pp** |
| 100w | −0.41% | +7.96pp | +2.79pp |
| 300w | −0.29% | +8.08pp | +2.91pp |
| 600w | −0.26% | +8.11pp | **+2.94pp** |

备份在 `tmp/bench_backup/`（gitignore）；P3 七账户尚未 step，
`nav_history` 只有建账行 `bench=1.0`，**由代码修复覆盖，无需迁移**。

### 0.3 诚实边界

1. **`bench_base` 语义变化**：从"建账时冻结"改为"每次按当前面板重算"，
   会**重写历史 `bench` 值**（本轮仅 1 条）。取舍理由：冻结 base + 会变的分子 = 恒定失真，
   故选择自洽。已如实记录。
2. **`industry_full.parquet` 09-22 刷新的影响面已在 Round 65 量化完成**
   （本文件初稿写的"旧备份仅 800 只、无法还原"有误——**git 里保留了 `f69eef5` 版本**，可精确对比）：
   刷新**只新增 291 只 code、行业标签 100% 未变**（3193→3484）；
   R5 超额差异 **+0.24pp（全区间）/ +0.20pp（训练）/ +0.35pp（验证段）**
   → **低于预注册阈值（0.5pp / 1.0pp），历史结论无需重发**。
   详见 `docs/factor_round65_industry_refresh_impact_plan.md` §0。
   唯一残留：K1 归因残差 0.009%（候选：10-09 `write_full_daily` 重写 2026 分区），待查。
3. **未做端到端 `step` 重跑**（当前无待处理调仓，重跑为空操作）。

### 0.4 复现

```bash
uv run pytest tests/test_bench_rebase.py -v           # 5 passed（快）
uv run pytest tests/test_bench_rebase.py -m slow      # 1 passed（真实面板自洽门）
.venv/bin/python tmp/recalibrate_bench.py             # dry-run 校准
```

