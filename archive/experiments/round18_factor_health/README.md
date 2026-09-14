# Round 18 因子失效监控（factor_health.py）

**状态**：✅ 通过并入 → **现行**（R5 因子监控仪表盘，只读不操作）。

预注册方案：`factor_round18_factor_health_plan.md`（含 §0 实施结果归档）。

## 结论

- 逐月末 RankIC（Amihud / 动量 / 合成分，全池 + 行业内）对比历史基准出状态灯（🔴/🟡/🟢）；
- 监控现行运行：`research/factor_health.py`——**脚本留位 research/，勿归档勿删**。

## 复现

```bash
uv run python research/factor_health.py           # 全量: 历史基准 + 运营期状态灯
uv run python research/factor_health.py --chart   # 额外画 μ±2σ 带
```
