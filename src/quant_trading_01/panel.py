# -*- coding: utf-8 -*-
"""价格/因子面板构造的公共基座（Round 58）。

`forward_factor_series` 是复权因子对齐到交易日网格的**唯一正确写法**：

    s.reindex(index.union(s.index)).ffill().reindex(index).bfill()

**不要**写成 `s.reindex(index).ffill()` —— `reindex` 会先把索引外的行丢掉，之后
`ffill` 已无源可填，再叠加 `.fillna(1.0)` 就变成"因子回落为 1.0 → real=close(前复权价)"，
即 Round 41~56 的静默数据 bug（R57 修复；其签名由 `tests/test_data_panel.py` 看守）。
"""

from __future__ import annotations

import pandas as pd


def forward_factor_series(s: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """复权因子序列 → 对齐到 `index`（**保留 `index` 起点之前的记录**）。

    s: 以日期为索引的 `foreAdjustFactor`（同一 code，可含重复日期）。
    index: 目标交易日网格（如 close.index）。
    返回: 与 index 等长的因子序列；起点之前的日期用最近的历史记录（ffill），
          若整表无更早记录则用最早可得记录（bfill）；完全无记录时为 1.0。
    """
    if len(s) == 0:
        return pd.Series(1.0, index=index)
    s = s[~s.index.duplicated()].sort_index()
    return s.reindex(index.union(s.index)).ffill().reindex(index).bfill().fillna(1.0)
