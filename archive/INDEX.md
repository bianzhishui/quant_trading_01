# 探索归档索引

> 本索引由 `research/archive_experiment.py` 维护。归档纪律（AGENTS.md）：
> 探索结束 → 在 plan 文档写 §0 结论 → 跑 `archive_experiment.py <脚本或单元>` → 本表登记。
> 状态：`✅ 通过并入生产` · `❌ 已否决` · `🟡 部分通过` · `⏸ 搁置` · `🛠 工具/演示`
>
> 已归档探索的完整清单（代码 + plan + 结论输出）见各单元目录；共享基座
> `reversal_factor.py` / `dividend_factor.py` 因被生产链（`paper_live`/`paper_trade`）依赖而**脚本留位**，
> 其 plan 与结论输出照常归档，详见对应单元。

| 单元 | 方向 | 状态 | 结论摘要 | 位置 | 归档日期 |
|---|---|---|---|---|---|
| convertible_double_low | 可转债双低 | ⏸ 搁置 | 可转债双低轮动（独立方向，结论见 plan §0） | archive/experiments/convertible_double_low/ | 2026-09-09 |
| dividend_factor | 高股息 | ⏸ 搁置 | 高股息四组对照：按失败处置协议记录（结论见 plan §0） | archive/experiments/dividend_factor/ | 2026-09-09 |
| etf_exploration | ETF 轮动 | ⏸ 搁置 | ETF 动量/低波轮动与候选研究（独立方向，失败处置见 plan §0） | archive/experiments/etf_exploration/ | 2026-09-09 |
| ew_base | 等权底仓 | ⏸ 搁置 | 等权底仓可行性评估（轻量，结论见 plan §0） | archive/experiments/ew_base/ | 2026-09-09 |
| grid_demo | 网格演示 | 🛠 工具/演示 | 网格交易演示（无 plan 文档） | archive/experiments/grid_demo/ | 2026-09-09 |
| reversal_short_term | 短期反转 | ❌ 已否决 | 短期反转否决（IC 不足 + 15bp 成本致命） | archive/experiments/reversal_short_term/ | 2026-09-09 |
| round03_combination | Amihud×动量组合 | ✅ 通过并入 | Amihud+中期动量等权组合确立为策略主体（+9.8pp，夏普0.91） | archive/experiments/round03_combination/ | 2026-09-09 |
| round04_risk_breakers | 风控·熔断/择时 | 🟡 部分通过 | 风控系列：4b 回撤熔断/4c 均线择时正交互补（部分通过）；4d 双熔断否决（防守过度，股灾恢复期钳制踏空） | archive/experiments/round04_risk_breakers/ | 2026-09-09 |
| round05_industry_neutral | R5 行业中性 | ✅ 通过并入 | R5 行业中性化升级为策略主体（行业内 alpha 真实存在） | archive/experiments/round05_industry_neutral/ | 2026-09-09 |
| round06_r5_ma | R5+均线择时 | ❌ 已否决 | R5+4c 均线择时叠加否决（择时代价占比过高） | archive/experiments/round06_r5_ma/ | 2026-09-09 |
| round07_fullmarket | 全市场扩池 | ✅ 通过并入 | 全市场扩池 R5：幸存者偏差仅 1.1pp，泛化成立 | archive/experiments/round07_fullmarket/ | 2026-09-09 |
| round08_live_validation | 实盘化验证 | ✅ 通过并入 | 实盘化验证：全口径成本下超额 +2.56pp，可执行 | archive/experiments/round08_live_validation/ | 2026-09-09 |
| round09_holdings_count | 持仓数量敏感度 | ⏸ 搁置 | 持仓数量敏感度实验：575 并非必须，结论见 plan §0 表 | archive/experiments/round09_holdings_count/ | 2026-09-09 |
| round11_fullbuy | 全选满仓 | ❌ 已否决 | 全选满仓变体否决（换手 2.2 倍 + 规则脆弱） | archive/experiments/round11_fullbuy/ | 2026-09-09 |
| round12_15_concentrated | 小资金规模研究 | ⏸ 搁置 | 小资金规模研究收束：20万不建议（费用吃光）/ 60万可行下限(+3.4~3.6pp) / 300万最优起点(+4.43pp) / 600万效率饱和(+4.72pp) | archive/experiments/round12_15_concentrated/ | 2026-09-09 |
| round16_crowding_timing | 拥挤度择时 | ❌ 已否决 | 拥挤度极值择时否决（风控五轮收束：压不住回撤且牺牲超额） | archive/experiments/round16_crowding_timing/ | 2026-09-09 |
| screen01_factor_screen | 因子筛选·中期动量 | 🟡 部分通过 | Round 1 批量筛选：中期动量因子判定部分通过，入组合观察名单 | archive/experiments/screen01_factor_screen/ | 2026-09-09 |
| screen02_factor_screen | 因子筛选·Amihud | ✅ 通过并入 | Round 2 批量筛选：Amihud 非流动性首个全通过因子（+7.3pp） | archive/experiments/screen02_factor_screen/ | 2026-09-09 |
| weekday_effect | 周内效应 | ⏸ 搁置 | 周内效应检验（独立方向，无 plan 文档） | archive/experiments/weekday_effect/ | 2026-09-09 |
| yearly_breakdown | 年度分解工具 | 🛠 工具/演示 | 年度收益分解分析工具（无 plan 文档） | archive/experiments/yearly_breakdown/ | 2026-09-09 |
