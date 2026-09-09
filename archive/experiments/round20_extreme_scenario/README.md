# round20_extreme_scenario — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-09 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🛠 工具/演示
- **结论摘要**：极端行情回放演练(4场景): 满配极端段-20~-50%级回撤(印证风控收束); 60万现金缓冲减震约一半(S1差18pp/S3差17pp); S4扛住31-41交易日恢复全年+4~6%; S3微盘危机唯一跑输大盘——实操指南入运营手册§10.4
- **归档日期**：2026-09-09
- **相关脚本**：extreme_scenario
- **plan 文档**：factor_round20_extreme_scenario_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
