# Round 10 模拟盘程序（paper_trade / paper_live）

**状态**：✅ 通过并入（真实可执行）→ **已生产化**（四账户模拟盘运营中）。

预注册方案：`factor_round10_paper_sim_plan.md`（含 §0 实施结果归档）。

## 结论

- share 级全口径回放（真实价 / 1手 / 现金拖累 / 分红 / 费率税全含）：
  300万超额 +4.37pp / 600万 +4.87pp；
- 交付 `research/paper_trade.py`（引擎+回放+信号）与 `research/paper_live.py`（四账户模拟盘），
  现为**生产链**——**脚本留位 research/，勿归档勿删**（AGENTS.md §5.7）。

## 复现

```bash
uv run python research/paper_trade.py replay_w --aum 3000000   # 权重口径回放
uv run python research/paper_live.py report                     # 账本报告
```
