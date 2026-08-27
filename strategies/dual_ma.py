# -*- coding: utf-8 -*-
"""经典入门策略：双均线择时（Golden Cross / Death Cross）。

规则：
- 收盘价上穿 MA_N_short 且短均线在长均线上方 -> 目标仓位 100%
- 收盘价下破或短均线落到长均线下方   -> 清仓观望

注意 signal 在 T 日收盘计算，由引擎延到 T+1 开盘执行。
"""
from __future__ import annotations

import pandas as pd


def dual_moving_average(close: pd.Series, short: int = 20, long_: int = 60) -> pd.Series:
    """返回与 close 对齐的目标权重序列（1.0 持有，0.0 空仓）。"""
    ma_s = close.rolling(short).mean()
    ma_l = close.rolling(long_).mean()
    weight = pd.Series(0.0, index=close.index)
    weight[(ma_s > ma_l) & (close > ma_s)] = 1.0
    return weight
