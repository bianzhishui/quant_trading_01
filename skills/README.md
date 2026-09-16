# skills/ — 项目技能沉淀（保留用，不自动加载）

本目录存放从本项目提炼的**可移植方法论 skill**，供查阅与复用。

**不注册到任何加载位置**：本目录不是 harness 的 skill 根（`.dsh/skills/`、`.agents/skills/` 等），
不会自动被 agent 发现/加载——仅作**方法沉淀与版本保留**（随仓库 git 提交）。

**若要启用为可加载 skill**：把 `skills/<name>/` 整目录复制到任一 skill 根即可
（如 `<projectRoot>/.dsh/skills/<name>/` 或用户级 `<dshHome>/skills/<name>/`），
复制后即被 `skill` 工具发现。

## 现有 skill

| skill | 内容 | 来源 |
|---|---|---|
| `a-share-quant-research/` | A 股量化研究通用纪律与工作流（预注册/判定/回测验证/归档/用数据说话/A股执行规则） | quant_trading_01 项目（R5 等权575 + 四账户模拟盘长期运营） |
