# round37_f4_combo — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-18 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：⏸ 搁置
- **结论摘要**：F4低成交额5组合验证(140期,300万share级,15bp): B等权三因子未通过(核心门禁①超额仅+0.57pp<+1pp, 未崩塌但无增量, 与R30正交崩塌对照: 同源稀释无害/正交破坏互补); C(0.85Amihud+0.15F4) 4/5组合升级候选(+8.30%, 超额+1.10pp, 三段全正, 回撤/换手更优) 唯一失败⑤Jaccard 78.6%(同源高重叠属设计使然); 解释验证: C>纯Amihud1.0(+7.10%)→F4有真实短频增量非权重复现, 但本质是Amihud短频精化非新信息源; 维持R5生产, C为决策点(替换动量=改冻结选股逻辑须另预注册; 建议0.85A+0.10动量+0.05F4微调路径)
- **归档日期**：2026-09-18
- **相关脚本**：factor_round37_f4_combo
- **plan 文档**：factor_round37_f4_combo_plan.md
- **结论输出**：round37_f4_combo_summary.csv
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
