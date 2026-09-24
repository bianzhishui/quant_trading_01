# round42_low23_quality — 已归档探索

> 由 `scripts/archive_experiment.py` 于 2026-09-24 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过
- **结论摘要**：2-3元+质量筛选预注册通过(全样本19.8%/0.86/-40.6%)
- **归档日期**：2026-09-24
- **相关脚本**：factor_round42_low23_quality
- **plan 文档**：factor_round42_low23_quality_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 scripts/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `src/quant_trading_01/reversal_factor.py` / `src/quant_trading_01/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
