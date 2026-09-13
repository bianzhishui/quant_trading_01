# round32_execution_cost — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-13 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过并入
- **结论摘要**：模拟盘账本补上滑点15bp(账本真实化): 300万 replay_w 对照 slip=0 +8.78%→15bp +7.63%; 每省1bp实际成本≈超额+0.072pp(成本敏感度回测); 四账户从9月重新建仓含滑点
- **归档日期**：2026-09-13
- **相关脚本**：（无，脚本留位=共享基座）
- **plan 文档**：factor_round32_execution_cost_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
