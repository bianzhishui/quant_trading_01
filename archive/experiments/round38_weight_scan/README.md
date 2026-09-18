# round38_weight_scan — 已归档探索

> 由 `research/archive_experiment.py` 于 2026-09-18 归档。
> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。

- **状态**：🟡 部分通过
- **结论摘要**：三因子权重最优配比扫描(35点ew_nav+share级复核+样本外R28协议): 样本外四项判据全过(w_train*=A0.40/M0.10/F40.50: 训练+9.80%→验证+12.62% vs A+10.32% 差+2.30pp, 网格内部, 全区间+10.40%≥A, 双侧高原0.49pp<0.5pp); 候选区间 [Amihud0.40~0.50×动量0.05~0.10×F4 0.40~0.50], share级最优点W1(0.50/0.05/0.45)超额+9.27%(三段全正/高原0.15pp最稳); F4增量三重独立证据确认(R36正交IC→R37解释验证→R38样本外); 本质=调整Amihud测量窗口(21日→5日)非新信息源, 代价=动量缓冲15%→5~10%风格年更脆弱; R5生产未动, 呈用户决策
- **归档日期**：2026-09-18
- **相关脚本**：factor_round38_weight_scan
- **plan 文档**：factor_round38_weight_scan_plan.md
- **结论输出**：round38_weight_scan_summary.csv
- **复现命令**：`（脚本留位 research/，无需复现命令）`
- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。
