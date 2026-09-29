# round51_p3_risk_value — 已归档探索

> 由 `scripts/archive_experiment.py` 于 2026-09-29 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🟡 部分通过
- **结论摘要**：A1 低波60 唯一通过且超 X0 集中度对照(回撤 -25.0%→-21.6%, 年化 18.2%→19.8%, 夏普 0.91→1.03, Calmar 0.73→0.92), 但增益集中 2022-26(2014-17 年化 -1.7pp, 2015 单年 -26pp); 其余 11 变体未达标: 低IVOL/半方差差 0.7-0.8pp, 低PB 边际(年化+1.9pp/夏普+0.099 双重差一丝), 低MAX 收益最好但回撤未改善, 低PE/低应计反向, 波动率倒数加权降回撤不足但零成本改善夏普, 波动率目标仓位(择时)第 6 次失败(仅 2014-17 降回撤 14pp); 判据②符号更正已披露且不改变任何判定; 生产采纳须另行批准
- **归档日期**：2026-09-29
- **相关脚本**：factor_round51_p3_risk_value
- **plan 文档**：factor_round51_p3_risk_value_plan.md
- **结论输出**：（无）
- **复现命令**：`.venv/bin/python archive/experiments/round51_p3_risk_value/factor_round51_p3_risk_value.py   # cwd=仓库根`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `src/quant_trading_01/reversal_factor.py` / `src/quant_trading_01/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
