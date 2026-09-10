# round28_weight_tuning_oos — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-10 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：✅ 通过并入
- **结论摘要**：扩展扫描0.80~1.00顶点0.95(+7.49%)+样本外验证(训练14-21独立选权→验证22-26 超额差+6.5pp)+高原0.90~1.00波动0.15pp——四项全过; 用户批准折中w=0.85落地生产(保留15%动量缓冲), 账本重建
- **归档日期**：2026-09-10
- **相关脚本**：factor_round28_weight_tuning_oos
- **plan 文档**：factor_round28_weight_tuning_oos_plan.md
- **结论输出**：（无）
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
