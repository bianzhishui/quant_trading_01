# round19_concentrated200 — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-09 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 已否决
- **结论摘要**：60万 前200+满仓补买 +2.96pp/82%用/2.32%费 未达标; 集中度补买曲线闭合 100(+3.59)>150(+3.41)>200(+2.96), 最优仍为前100+补买; 补买对前200仅堆仓位不增超额
- **归档日期**：2026-09-09
- **相关脚本**：factor_round19_concentrated200
- **plan 文档**：factor_round19_concentrated200_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
