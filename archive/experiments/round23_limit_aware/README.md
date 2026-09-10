# round23_limit_aware — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-10 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过并入
- **结论摘要**：涨跌停阻塞验证(S3-跟随): 阻塞损失-0.31pp@300万/-0.95pp@60万(四账户全≥-1.0pp), 三段全正策略结论不变; 结论并入生产Round24(引擎内置+实盘SOP入运营手册§8.7)
- **归档日期**：2026-09-10
- **相关脚本**：factor_round23_limit_aware
- **plan 文档**：factor_round23_limit_aware_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
