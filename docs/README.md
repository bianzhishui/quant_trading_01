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
| [factor_round34_config_plan.md](factor_round34_config_plan.md) | 基建方案（预注册+归档） | 已实施——全量配置化（YAML + 惰性读取 + 冻结校验），§0 含复检记录 |
| [factor_round18_factor_health_plan.md](factor_round18_factor_health_plan.md) | 监控方案（预注册+归档） | 已实施——R5 因子失效监控（factor_health.py 仪表盘） |
| [factor_candidates.md](factor_candidates.md) | 因子候选池索引 | 现行——三梯队候选 + 检验顺序 + 避坑 |
| [factor_top10.md](factor_top10.md) | 因子精选清单 | 现行——10 个可用因子 + 数据补全 |
| [data_sources_integrity.md](data_sources_integrity.md) | 数据完整性档案 | 现行——R5 数据源/窗口/完整性口径 |
| [strategy_artifacts.md](strategy_artifacts.md) | 程序产物说明 | 现行（09-08 版）——脚本/输出/图清单 |
| [archive_design_plan.md](archive_design_plan.md) | 归档机制设计 | 已实施——探索归档工具的依据 |
| [fundamental_pipeline_plan.md](fundamental_pipeline_plan.md) | 基建方案 | 已实施（§0 闭环）——基本面管线（src/fundamental.py，已迁移 research/fetch_stock_basic.py）；高股息实验已归档 |
| [factor_round10_paper_sim_plan.md](factor_round10_paper_sim_plan.md) | 模拟盘程序（预注册+归档） | 已实施并生产化——paper_trade/paper_live（四账户运营中） |
| [retail_investor_structure.md](retail_investor_structure.md) | 背景研究笔记 | 参考——散户结构（时效 2025 年中） |

## 已归档实验

Round 1-9 / 短期反转 / 高股息 / 等权基 / ETF / 可转债 等探索的预注册方案、脚本与结论输出，
随实验单元归档至 `archive/experiments/`，完整索引见 [`archive/INDEX.md`](../archive/INDEX.md)。

## 约定

- **命名**：`{主题}_{类型}.md`
- **研究方案类文档**遵循预注册原则：回测实施前写死假设/规则/判定标准；
- 实施结果写回同一文档的 **§0 实施结果归档**（含失败）再提交 commit；
- 实验结束后 plan 随单元归档（`archive/experiments/`），docs/ 不留已完成探索的 plan。
