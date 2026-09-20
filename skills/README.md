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
| `exploration-project/` | **探索型研究项目启动与纪律**：通用探索方法论（预注册/判定/防数据挖掘/归档/对账）+ Python 工程规范（uv/虚拟环境、配置化、代码风格、测试、临时脚本）+ git 仓库初始化 + **通用配置框架脚手架**（`bootstrap.py` + `templates/`，可快速初始化新探索项目） | 沉淀自 quant_trading_01（A 股量化：R5 等权575 + 四账户模拟盘），已泛化去领域绑定 |

## 历史

- `a-share-quant-research/`（A 股专属版，2026-09）已泛化为 `exploration-project/`
  （`git mv` 保留历史；A 股执行规则 T+1/涨跌停/费率已移出 skill，属领域专属，落各仓库 AGENTS.md）。
