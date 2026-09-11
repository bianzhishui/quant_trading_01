# round31_lhb — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-11 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 已否决
- **结论摘要**：龙虎榜净买占比: 未通过(1/4)——机制假设被否定: 上榜后1/2/5日均值+0.32/+0.28/+0.37%(上榜=强势延续非散户追高看空); IC无效/分组U型/超额+0.3pp; 正交(-0.04)但无信号; 月度截面无预测力, 不进入组合验证
- **归档日期**：2026-09-11
- **相关脚本**：factor_round31_lhb, fetch_lhb
- **plan 文档**：factor_round31_lhb_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
