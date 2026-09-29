# round50_p3_optimize — 已归档探索

> 由 `scripts/archive_experiment.py` 于 2026-09-29 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 未达标
- **结论摘要**：P3 优化空间封闭(R50): 经营现金流质量否决(验证段 -0.4/-0.8pp, 全样本 -4.7~-5.2pp) + 双周频否决(-3.05pp@45bp, 换手翻倍) + 阻塞口径验证段稳健(全样本 +1.8pp/年 高估, 集中 2014-17); 行业上限探查即否决(大类 HHI 0.05-0.08 已分散); 剩余空间仅框架外(扩池/行业排序补位)
- **归档日期**：2026-09-29
- **相关脚本**：factor_round50_p3_optimize
- **plan 文档**：factor_round50_p3_optimize_plan.md
- **结论输出**：（无）
- **复现命令**：`.venv/bin/python archive/experiments/round50_p3_optimize/factor_round50_p3_optimize.py   # cwd=仓库根`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `src/quant_trading_01/reversal_factor.py` / `src/quant_trading_01/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
