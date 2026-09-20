# round39_candidates — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-20 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 已否决
- **结论摘要**：'同向但异法'候选因子验证(4因子月频筛+组合验证): C1低换手21/C2换手波动21std 部分通过(3/4, IC显著−0.084/−0.092 t≤−5.6, 单调完美, Jaccard 16.9%极异法, 但超额仅+1.7/+2.0%<3pp不进组合验证); C3市值代理 通过(4/4,+9.4%)但10%并入w* 组合验证3/5不并入(超额+0.24pp<+1pp, Jaccard 90.6%同法重复暴露→R22教训重演); C4短动量5/21 未通过(月频方向=反转, 高动量组−10.5%); 框架结论: 异法度是必要不充分条件, 最终裁判=组合增量门禁; 无新因子并入, R5/w*生产不变
- **归档日期**：2026-09-20
- **相关脚本**：factor_round39_candidates
- **plan 文档**：factor_round39_candidates_plan.md
- **结论输出**：round39_candidates_summary.csv
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
