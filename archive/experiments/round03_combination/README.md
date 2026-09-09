# round03_combination — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-09 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过并入
- **结论摘要**：Amihud+中期动量等权组合确立为策略主体（+9.8pp，夏普0.91）
- **归档日期**：2026-09-09
- **相关脚本**：factor_round3_combination
- **plan 文档**：factor_round3_combination_plan.md
- **结论输出**：factor_round3.png, factor_round3_summary.csv
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
