# 探索归档索引

> 本索引由 `research/archive_experiment.py` 维护。归档纪律（AGENTS.md）：
> 探索结束 → 在 plan 文档写 §0 结论 → 跑 `archive_experiment.py <脚本或单元>` → 本表登记。
> 状态：`✅ 通过并入生产` · `❌ 已否决` · `🟡 部分通过` · `⏸ 搁置` · `🛠 工具/演示`
>
> 已归档探索的完整清单（代码 + plan + 结论输出）见各单元目录；共享基座
> `reversal_factor.py` / `dividend_factor.py` 因被生产链（`paper_live`/`paper_trade`）依赖而**脚本留位**，
> 其 plan 与结论输出照常归档，详见对应单元。

| 单元 | 方向 | 状态 | 结论摘要 | 位置 | 归档日期 |
|---|---|---|---|---|---|
| reversal_short_term | 短期反转 | ❌ 已否决 | 短期反转否决（IC 不足 + 15bp 成本致命） | archive/experiments/reversal_short_term/ | 2026-09-09 |
| round04_risk_breakers | 风控·熔断/择时 | 🟡 部分通过 | 风控系列：4b 回撤熔断/4c 均线择时正交互补（部分通过）；4d 双熔断否决（防守过度，股灾恢复期钳制踏空） | archive/experiments/round04_risk_breakers/ | 2026-09-09 |
| round06_r5_ma | R5+均线择时 | ❌ 已否决 | R5+4c 均线择时叠加否决（择时代价占比过高） | archive/experiments/round06_r5_ma/ | 2026-09-09 |
| round12_15_concentrated | 小资金规模研究 | ⏸ 搁置 | 小资金规模研究收束：20万不建议（费用吃光）/ 60万可行下限(+3.4~3.6pp) / 300万最优起点(+4.43pp) / 600万效率饱和(+4.72pp) | archive/experiments/round12_15_concentrated/ | 2026-09-09 |
| round16_crowding_timing | 拥挤度择时 | ❌ 已否决 | 拥挤度极值择时否决（风控五轮收束：压不住回撤且牺牲超额） | archive/experiments/round16_crowding_timing/ | 2026-09-09 |
