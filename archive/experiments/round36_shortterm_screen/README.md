# round36_shortterm_screen — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-18 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🟡 部分通过
- **结论摘要**：周频短线因子筛选(5日持有,全市场非ST池,639期): F4低成交额5 通过(4/4)(IC−0.077 t=−10.8, 超额15bp+11.9pp/35bp+7.1pp, 三段全正, 换手10.3) 但与生产Amihud截面相关−0.85强同源, 正交残差IC−0.075显著, 控制市值后仍−0.060,B口径31.7bp成本存活+7.9pp→非成本/市值假象, 需组合验证守门(R22/R30协议); F3低换手5 部分通过(3/4,超额仅+1.3pp量级不足); 短反转/低波动/换手突变/短动量 否决(周频反转Q1接飞刀−12.6pp, 与月频对照更不可交易)
- **归档日期**：2026-09-18
- **相关脚本**：factor_screen_round36_shortterm
- **plan 文档**：factor_round36_shortterm_screen_plan.md
- **结论输出**：round36_F3低换手5_ic.csv, round36_F4低成交额5_ic.csv, round36_F4低成交额5_navs.csv, round36_shortterm_summary.csv
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
