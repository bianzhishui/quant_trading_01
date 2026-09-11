# round30_shareholder — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-11 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 已否决
- **结论摘要**：股东户数/筹码集中度: 单因子3/4(IC-0.02 t=-4.57极显著, 与Amihud/动量正交0.1级), 但等权三因子并入崩塌(+7.31→+3.62pp, 稀释Amihud主源)——正交≠可并入(R22教训重演); 不并入R5; 判据缺陷记录(①超额应为门禁)
- **归档日期**：2026-09-11
- **相关脚本**：factor_round30_shareholder, factor_round30_shareholder_combo, fetch_shareholder_count
- **plan 文档**：factor_round30_shareholder_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
