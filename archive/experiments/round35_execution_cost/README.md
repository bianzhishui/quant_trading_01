# round35_execution_cost — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-16 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过并入
- **结论摘要**：执行成本模型评估: A固定15bp +7.57%维持生产口径; B流动性依赖 +7.02%(−0.55pp, 等权加权滑点21.1bp>15bp, flat低估小盘真实成本) 以 --slip-by-amount 监控并入; C VWAP否决(免费分钟源历史不足官方文档证实+第三方源不可低成本验证); 18测试通过
- **归档日期**：2026-09-16
- **相关脚本**：（无，脚本留位=共享基座）
- **plan 文档**：factor_round35_execution_cost_plan.md（含 §0 归档、§0.5 后补核实、§0.6 后补发现、§0.7 抽查验证记录）
- **决策备忘**：factor_round35_decision_memo.md（一页纸 A/B/C 对比，供拍板生产口径）
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
