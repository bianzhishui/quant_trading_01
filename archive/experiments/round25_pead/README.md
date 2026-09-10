# round25_pead — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-10 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 已否决
- **结论摘要**：PEAD业绩预告后漂移: IC+0.003(t=0.46)极弱/分组不单调(Q3峰)/超额+0.4pp, 1/4未通过; 与中期动量IC序列相关+0.629强重叠(非独立信息源)——不进入组合验证, R5不变
- **归档日期**：2026-09-10
- **相关脚本**：factor_round25_pead, fetch_earnings_forecast
- **plan 文档**：factor_round25_pead_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
