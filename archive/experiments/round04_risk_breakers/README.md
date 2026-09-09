# round04_risk_breakers — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-09 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🟡 部分通过
- **结论摘要**：风控系列：4b 回撤熔断/4c 均线择时正交互补（部分通过）；4d 双熔断否决（防守过度，股灾恢复期钳制踏空）
- **归档日期**：2026-09-09
- **相关脚本**：factor_round4, factor_round4b, factor_round4c, factor_round4d
- **plan 文档**：factor_round4_plan.md, factor_round4b_drawdown_breaker_plan.md, factor_round4c_trend_breaker_plan.md, factor_round4d_dual_breaker_plan.md
- **结论输出**：factor_round4b.png, factor_round4b_summary.csv, factor_round4c.png, factor_round4c_summary.csv, factor_round4d.png, factor_round4d_summary.csv, factor_round4.png, factor_round4_summary.csv
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
