# docs — 项目文档目录

存放设计文档、研究方案、决策记录（与代码分离，research/ 只放可执行脚本）。
**历史实验的预注册方案已随实验单元归档**（索引见 [`archive/INDEX.md`](../archive/INDEX.md)），
docs/ 只保留**现行/权威文档**与已闭环的基建记录。

## 现行文档（docs/）

| 文档 | 类型 | 状态 |
|---|---|---|
| [strategy_operations_handbook.md](strategy_operations_handbook.md) | **运营手册（权威，⭐）** | 现行——R5 四账户运营全流程（每日/每月/对账/监控） |
| [strategy_final_spec.md](strategy_final_spec.md) | 最终策略规格（权威） | 定稿 2026-09-04——全市场 R5 完整可执行规格 |
| [strategy_investment_plan.md](strategy_investment_plan.md) | 实盘投资方案（参考） | 定稿 2026-09-04——本金/建仓/费率权威（现行运营为模拟盘） |
| [factor_round35_execution_cost_plan.md](factor_round35_execution_cost_plan.md) | 执行成本模型评估（预注册） | **待批准**——固定15bp vs 流动性依赖 vs VWAP可行性 |
| [factor_candidates.md](factor_candidates.md) | 因子候选池索引 | 现行——三梯队候选 + 检验顺序 + 避坑 |
| [factor_top10.md](factor_top10.md) | 因子精选清单 | 现行——10 个可用因子 + 数据补全 |
| [data_sources_integrity.md](data_sources_integrity.md) | 数据完整性档案 | 现行——R5 数据源/窗口/完整性口径 |
| [strategy_artifacts.md](strategy_artifacts.md) | 程序产物说明 | 现行（09-08 版）——脚本/输出/图清单 |
| [archive_design_plan.md](archive_design_plan.md) | 归档机制设计 | 已实施——探索归档工具的依据 |
| [retail_investor_structure.md](retail_investor_structure.md) | 背景研究笔记 | 参考——散户结构（时效 2025 年中） |

## 已归档实验

已实施/已结束的探索与**基建/系统方案**（含配置系统 Round 34、因子监控 Round 18、
模拟盘程序 Round 10、数据管线）的预注册方案、脚本与结论输出，随单元归档至
`archive/experiments/`，完整索引见 [`archive/INDEX.md`](../archive/INDEX.md)。
现行系统的操作知识以 AGENTS.md §2.5/§3 + 运营手册为准。

## 约定

- **命名**：`{主题}_{类型}.md`
- **研究方案类文档**遵循预注册原则：回测实施前写死假设/规则/判定标准；
- 实施结果写回同一文档的 **§0 实施结果归档**（含失败）再提交 commit；
- 实验结束后 plan 随单元归档（`archive/experiments/`），docs/ 不留已完成探索的 plan。
