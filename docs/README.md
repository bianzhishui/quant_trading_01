# docs — 项目文档目录

存放设计文档、研究方案、决策记录（与代码分离，research/ 只放可执行脚本）。

| 文档 | 类型 | 状态 |
|---|---|---|
| [etf_momentum_plan.md](etf_momentum_plan.md) | 策略研究方案（预注册） | 已实施，判定=未通过（§0 归档） |
| [fundamental_pipeline_plan.md](fundamental_pipeline_plan.md) | 基建方案 | 已实施（管线+高股息实验数据就绪） |
| [dividend_factor_plan.md](dividend_factor_plan.md) | 策略研究方案（预注册） | 已实施，判定=未通过（§0 归档，含归因读数） |
| [ew_base_plan.md](ew_base_plan.md) | 可行性评估（预注册） | 已实施，机械判定=成立，实用建议=中证500/1000 指数产品（§0 归档） |
| [ew_base_execution.md](ew_base_execution.md) | **核心层构造方案（执行版）** | **现行有效**——唯一通过验证的持仓方案 |

## 约定

- **命名**：`{主题}_{类型}.md`，如 `etf_momentum_plan.md`、`grid_findings.md`
- **研究方案类文档**遵循预注册原则：回测实施前写死假设/规则/判定标准，
  实施后修改必须升版本号并注明原因
- 研究结论若已成文，在主 README 的对应章节加一行链接指向这里
