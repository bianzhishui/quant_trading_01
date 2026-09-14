# 基本面数据管线（已迁移 → research/fetch_stock_basic.py）

**状态**：✅ 已实施（管线建成）→ 能力已迁移 `research/fetch_stock_basic.py`。

预注册方案：`fundamental_pipeline_plan.md`（含 §0 实施结果归档）。

## 结论

- P1 数据层 `src/fundamental.py` 建成（stock_basic/universe 刷新），Round 34 收尾
  迁移为 `research/fetch_stock_basic.py`（生产宇宙清单刷新脚本，脚本留位 research/，勿删）；
- P3/P4 高股息 A/B/C/D 实验判定**未通过**，已归档于 `dividend_factor` 单元；
- 现行数据管线以 `research/data_io.py` + `research/fetch_*` 为准（Round 17 起）。

## 复现

```bash
uv run python research/fetch_stock_basic.py    # 宇宙清单刷新(季度/半年低频, 勿 baostock 抖动期重试)
```
