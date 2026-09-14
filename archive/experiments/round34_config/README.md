# Round 34 全量配置化（YAML 配置系统）

**状态**：✅ 通过并入（判定 6/6 + 复检全过）→ **现行**（配置系统，`config/default.yaml` 权威）。

预注册方案：`factor_round34_config_plan.md`（含 §0 实施结果归档、§0.5 复检、§0.6 src/ 迁移）。

## 结论

- **全量配置化**：paths / strategy（含 r5 冻结窗口）/ costs（冻结）/ accounts / fetch / monitor
  全入 YAML；函数内惰性 `get_config()` 读取（全仓无模块级读取）+ 冻结偏离警告 +
  `--config` / `QUANT_CONFIG` 覆盖；
- **后续扩展（§0.3-§0.6）**：fetch 波、惰性读取全覆盖、R5 公式窗口配置化、src/ 能力迁移删除；
- 配置系统现行：`research/config.py` + `config/default.yaml`——**脚本留位 research/，勿归档勿删**。

## 复现

```bash
uv run python research/config.py          # 配置加载自检
uv run python research/paper_trade.py replay_w --aum 3000000 --config config/custom.yaml.example
```
