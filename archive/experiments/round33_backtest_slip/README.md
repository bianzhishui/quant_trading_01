# round33_backtest_slip — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-13 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过并入
- **结论摘要**：回测默认滑点0→15bp, 回测=运营=基准三口径统一; replay四账户重跑: 60/100/300/600万超额+2.83/+4.92/+6.08/+6.28%, 费用4.48/4.35/3.62/3.36%/年
- **归档日期**：2026-09-13
- **相关脚本**：（无，脚本留位=共享基座）
- **plan 文档**：factor_round33_backtest_slip_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
