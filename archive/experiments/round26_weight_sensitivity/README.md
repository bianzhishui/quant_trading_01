# round26_weight_sensitivity — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-10 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：⏸ 搁置
- **结论摘要**：R5权重敏感性: 50:50非最优且脆弱(邻域波动+3.17pp>0.5pp); Amihud权重单调递增超额(−0.37→+6.38pp)——Amihud是超额主源, 动量是稀释项; 生产不动(冻结), 是否调权重=用户决策点(需另开预注册+细扫防过拟合)
- **归档日期**：2026-09-10
- **相关脚本**：factor_round26_weight_sensitivity
- **plan 文档**：factor_round26_weight_sensitivity_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
