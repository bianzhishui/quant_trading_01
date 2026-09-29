# round52_p3_composite — 已归档探索

> 由 `scripts/archive_experiment.py` 于 2026-09-29 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：❌ 未达标
- **结论摘要**：P3 池内多因子合成打分(首次引入打分机制)全部未达标: 绑定判据为'不劣于单因子 A1'——Z1-Z4 合成抬高收益(Z4 年化 20.2% vs A1 19.8%, 夏普 1.04)但回撤恶化 1.5-1.8pp(-23.1~-23.4% vs -21.6%), Calmar 0.85-0.87 全面低于 A1 0.92, 净效应=用回撤换一点收益, 与'提收益+降回撤'目标相反; Z5 取 50% 回撤 -19.3%(改善 5.7pp)但年化仅 +0.3pp/45bp 持平/持仓 26 只(<30 下限); 探查预测被证实(vol/ivol 秩相关 0.917 → Z2≈Z1, 增量仅来自低PB, 而低PB 自身回撤不及低波); A1 仍为唯一可用候选; 自校验双重通过(Z0=R50, A1=R51 逐位一致); 生产采纳须另行批准
- **归档日期**：2026-09-29
- **相关脚本**：factor_round52_p3_composite
- **plan 文档**：factor_round52_p3_composite_plan.md
- **结论输出**：（无）
- **复现命令**：`.venv/bin/python archive/experiments/round52_p3_composite/factor_round52_p3_composite.py   # cwd=仓库根`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `src/quant_trading_01/reversal_factor.py` / `src/quant_trading_01/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
