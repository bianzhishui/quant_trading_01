# round24_prod_limit_aware — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-13 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过并入
- **结论摘要**：生产引擎内置涨跌停阻塞(S3-跟随)+账本统一真实口径; 回测+账本口径一致
- **归档日期**：2026-09-13
- **相关脚本**：（无，脚本留位=共享基座）
- **plan 文档**：factor_round24_prod_limit_aware_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
