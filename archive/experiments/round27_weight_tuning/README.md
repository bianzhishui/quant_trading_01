# round27_weight_tuning — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-10 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：⏸ 搁置
- **结论摘要**：权重细扫0.55~0.80: 超额单调递增至0.80(+7.04pp)但无高原(双侧高原判据全❌); 端点0.80伪通过被双侧判据拦截(数据挖掘陷阱); 结论: 趋势真实但无稳健选择——由Round28扩展扫描+样本外验证接续
- **归档日期**：2026-09-10
- **相关脚本**：factor_round27_weight_tuning
- **plan 文档**：factor_round27_weight_tuning_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
