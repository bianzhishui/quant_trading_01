# migrate_full_daily_partitions — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-14 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🛠 工具/演示
- **结论摘要**：一次性迁移工具：full_daily.parquet 单文件 → 按年分区（已完成使命，R17 基建产物）
- **归档日期**：2026-09-14
- **相关脚本**：migrate_full_daily_partitions
- **plan 文档**：（无）
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
