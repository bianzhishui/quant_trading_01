# round49_event_momentum — 已归档探索

> 由 `scripts/archive_experiment.py` 于 2026-09-29 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 已否决
- **结论摘要**：涨停事件动量否决(E1胜率44.7%<50%): 1-2日动量为正但5日胜率转负, 可交易(换手)子集5日胜率43%多数亏, 暴涨在买不进的缩量/一字; 游资打板=对手盘负和, 数据终结叙事
- **归档日期**：2026-09-29
- **相关脚本**：factor_round49_event_momentum
- **plan 文档**：factor_round49_event_momentum_plan.md
- **结论输出**：（无）
- **复现命令**：`.venv/bin/python archive/experiments/round49_event_momentum/factor_round49_event_momentum.py   # cwd=仓库根`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `src/quant_trading_01/reversal_factor.py` / `src/quant_trading_01/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
