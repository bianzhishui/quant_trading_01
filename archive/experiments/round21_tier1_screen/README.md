# round21_tier1_screen — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-09 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🟡 部分通过
- **结论摘要**：梯队一4因子筛选: 价格水平(低价股)单因子4/4通过(+3.0pp@15bp/换手1.1/三段全正/与Amihud截面-0.19)进候选池, 但Round22组合验证否决并入; 低beta/长期反转/下行波动未通过
- **归档日期**：2026-09-09
- **相关脚本**：factor_round21_tier1_screen
- **plan 文档**：factor_round21_tier1_screen_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
