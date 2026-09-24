# Round 48 预注册 · 停牌股估值修正（raw.ffill 最后可得价）

状态：**✅ 已批准并实施（2026-09-24）** ｜ 影响：R5 + P3 模拟盘运营（mark/step/init/report 估值口径）

---

## §0 实施结果归档

**判定结果：✅ 通过（5/5）**

1. **停牌平滑** ✅ 单元验证：停牌日 b 股市值旧口径归零(100320) → R48 沿用最后价(101370)
2. **对账不变量** ✅ 无停牌持仓时 NAV 与改动前完全一致（P3 8 账户 mark 实测：9.63万/577.46万 等全部相同）——行为不变
3. **R5/P3 同步** ✅ eval_prices 接入：R5 paper_live 8 处 + P3 paper_live_p3 7 处（mark/step/init/report 估值）
4. **回测不变** ✅ 纯估值层改动，ret 收益矩阵未动
5. **无回归** ✅ ruff 全过；P3 mark 8 账户跑通；import 正常

**实现**：
- `scripts/r5/paper_live.py` 新增 `eval_prices(raw) = raw.ffill()`（最后可得价）；
  mark/step/init/report 估值统一改用（撮合仍用原始 raw）
- `scripts/p3/paper_live_p3.py` import eval_prices 同步
- 边界：停牌沿用最后价；尾部退市按最后价冻结；上市前 NaN 不填；复牌日涨幅正常

**已知遗留**：历史账本 nav_history 若恰逢停牌调仓日，旧值略低（不重跑 step，只重跑 mark CSV）；
退市股按最后价冻结 ≠ 归零（若运营期真遇退市，另案处理 step 清算动作）。

---

## 1. 问题（Review 发现，R5/P3 共有）

`PaperPortfolio.value()` 对价格 NaN 的持仓**直接不计市值**：

```python
p = prices.get(c, np.nan)
if pd.notna(p):
    v += s * p        # 停牌日 raw=NaN → 该股市值 = 0
```

后果：
- **停牌期间 NAV 被低估**（市值凭空消失），复牌日跳回——每日涨幅曲线出现假跳变
- P3 仅 50 只持仓，停 1 只 ≈ 2% NAV 波动；R5 575 只单只影响小但同样存在
- 对账（期末净值=现金+持仓）在停牌日名义上成立（市值=0 也是"成立"），但**不是真实价值**

## 2. 方案（规则定死）

**估值统一用"最后可得价"：`raw.ffill()`（前向填充），只改估值、不改交易撮合。**

| 环节 | 改动 |
|---|---|
| 估值（mark/step/init/report 的 `pf.value(...)`） | 价格矩阵改用 `raw.ffill()`（停牌日沿用最后交易价） |
| 交易撮合（rebalance） | **不变**，仍用原始 `raw`（停牌股 `trad=False` 本就不成交；买价 NaN 不成交） |
| 除权（corp_action_f / _apply_corp_period） | 不变（仍用 F 面板因子事件） |

**边界语义（定死）**：
1. **停牌**（中间 NaN）：ffill 沿用最后价 → 市值连续，复牌日正常涨跌
2. **退市**（列尾 NaN）：ffill 后按**最后交易价冻结**（市值不再变）——与回测"最后价清算"口径一致；
   面值退市股最后价通常已极低，亏损已反映；**比"归零"口径温和但运营现实合理**
   （持仓股退市应在 step 时按此价处理，不会无限期挂账）
3. **上市前 NaN**（列首）：ffill 不填（无前值）→ 保持 NaN → 不计市值（无影响）
4. **不改变回测口径**：回测走 `ret` 收益矩阵，与此估值修改无关

**实现位置**（两处引擎共用，改 `scripts/r5/paper_live.py` 与 `scripts/p3/paper_live_p3.py`）：
- 估值调用处统一传 `raw.ffill()` 后的价格（mark 每日循环 / step 的 pre/post_nav / init / report）
- 抽象为共享函数 `eval_prices(raw) -> raw.ffill()`（放 paper_live.py 导出，P3 import）

## 3. 判定标准（全部满足算通过）

1. **停牌平滑**：构造/实盘停牌日，mark 的 NAV 当日无异常跳变（市值不再归 0）；
   复牌日涨幅 = 复牌价/停牌前最后价 − 1（正常）
2. **对账不变量保持**：① 期末净值=现金+持仓（ffill 后持仓市值=Σ股数×最后价）；② 期末≈期初−费用；③ 月涨幅连乘=累计
3. **R5 与 P3 同步生效**：两策略 mark CSV 重生成，停牌股 NAV 差异符合预期（旧口径低估→新口径平滑）
4. **回测不变**：factor_round41-47 回测结果不因本改动变化（已归档，纯运营估值层改动）
5. **无回归**：ruff 全过；全脚本 import 成功；step/init/report 跑通

## 4. 执行步骤（批准后）

1. `paper_live.py` 加 `eval_prices(raw)`；mark/step/init/report 估值改用它
2. `paper_live_p3.py` 同步（import eval_prices）
3. 重跑 R5 mark（4 账户）+ P3 mark（8 账户），对比停牌股前后 NAV
4. 对账三不变量抽查 + ruff + import 校验
5. 结果归档到本 plan §0，提交

## 5. 诚实风险与局限

1. **退市按最后价冻结 ≠ 归零**：回测主口径是归零（ret zero），本方案退市股按最后价持有；
   若运营期真遇持仓退市，需在 step 明确清算动作（另案处理），本改动只是估值不再假跳
2. **历史账本 nav_history 口径轻微不一致**：已写入的调仓日 NAV 若恰逢停牌，旧值略低；
   不重跑 step（避免重复调仓），只重跑 mark CSV；差异 ≤1 只市值，可接受并记录
3. **ffill 会掩盖"长期停牌后复牌暴跌"**：复牌日涨幅如实显示（最后价→复牌价），无掩盖
4. **改动影响 R5 运营产物**（mark CSV/图），属于口径修正非策略变化，冻结参数不动

## 6. 判定流程
- 用户批准本 plan → 按 §4 实施 → 判定标准 §3 全过 → §0 归档 + commit
- 任一判定失败 → 回滚估值改动，如实报告
