# round53_p3_a1_share_level — 已归档探索

> 由 `scripts/archive_experiment.py` 于 2026-09-29 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🟡 部分通过
- **结论摘要**：A1 低波60 份额级八账户验证(主窗口 2021-2026): 八账户全部不劣于现冻结 P3——10万-600万 年化 +0.63~+1.86pp(随规模递减)、回撤改善 +2.45~+3.13pp、夏普 +0.06~+0.10, 买不起1手 0.0%; 3万账户是执行失败而非策略表现(66.5 目标仅持 35.0只=52.6%、47.3% 目标买不起1手、现金 49.1%、累计费用 35%、年化 -3.99%), A1 修复到 +8.09%(持仓率 99.7%)→ 该 +12.08pp 是'从不可执行到可执行'而非 alpha; 600万 份额级仅 +0.63pp(等权口径 +1.6pp)说明 1手取整/阻塞/现金拖累吃掉约 1pp; 主窗口可信性已验证(600万 S0 -24.96% vs 等权 -25.0%); 全样本窗口作废(口径缺陷): 份额级回撤 -95% vs 等权 -45.54%、累计费用 117-165%, 根因 scenario_ytd_p3 未接入 R48 的 eval_prices(raw.ffill()) 估值口径(已量化证据, 修正须另轮预注册); 生产采纳/3万账户处置须另行批准
- **归档日期**：2026-09-29
- **相关脚本**：factor_round53_p3_a1_share_level
- **plan 文档**：factor_round53_p3_a1_share_level_plan.md
- **结论输出**：（无）
- **复现命令**：`.venv/bin/python archive/experiments/round53_p3_a1_share_level/factor_round53_p3_a1_share_level.py   # cwd=仓库根`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `src/quant_trading_01/reversal_factor.py` / `src/quant_trading_01/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
