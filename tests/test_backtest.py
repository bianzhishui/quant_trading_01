# -*- coding: utf-8 -*-
"""回测引擎正确性单元测试。运行: uv run pytest"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import run_backtest
from src.data_loader import make_synthetic_daily


def _make_df() -> pd.DataFrame:
    return make_synthetic_daily(120)


def test_signal_executed_next_open_with_slippage():
    """T 日收盘的信号必须延后到 T+1 开盘价*(1+滑点) 撮合。"""
    df = _make_df()
    w = pd.Series(0.0, index=df.index)
    w.iloc[30:] = 1.0                       # 第30根K线收盘给出满仓信号

    res = run_backtest(df, w)
    t = res.trades
    assert len(t) == 1 and t.iloc[0]["side"] == "BUY", t
    assert t.iloc[0]["date"] == df.index[31], \
        f"应T+1成交: {t.iloc[0]['date']} vs {df.index[31]}"
    expected_px = df["open"].iloc[31] * 1.001   # 0.1% 滑点
    assert abs(t.iloc[0]["price"] / expected_px - 1) < 1e-9


def test_full_exit_no_double_counting():
    """清仓测试：卖出股数 == 累计买入股数，且严格执行于信号次日开盘。"""
    df = _make_df()
    w = pd.Series(0.0, index=df.index)
    w.iloc[30:70] = 1.0                     # 持有40天后清仓

    res = run_backtest(df, w)
    t = res.trades
    bought = int(t[t.side == "BUY"].shares.sum())
    sold = int(t[t.side == "SELL"].shares.sum())
    assert bought == sold, f"买卖数量不一致，可能存在持仓重复计数: buy={bought} sell={sold}"

    sells = t[t.side == "SELL"]
    assert len(sells) >= 1
    final_sell_day = pd.Timestamp(sells.iloc[-1]["date"])
    last_zero_idx = df.index[70]            # 权重归零的那一天（收盘时点）
    assert final_sell_day > last_zero_idx, "清仓应发生在权重归零之后"


def test_nan_weights_safe():
    """全 NaN 权重应视为空仓，资产不发生任何变化。"""
    df = _make_df()
    w = pd.Series(np.nan, index=df.index)
    res = run_backtest(df, w)
    assert abs(res.stats["total_return"]) < 1e-12
    assert len(res.trades) == 0


def test_limit_up_blocks_buy():
    """涨停开盘无法买入：构造 T+1 开盘触及 +10% 的行情。"""
    df = _make_df().copy()
    i = 31                                   # 信号在 idx30 收盘给出，idx31 开盘应被拦
    # 令 idx30 收盘=100，idx31 开盘=110（正好触及涨停价）
    scale = 100.0 / df["close"].iloc[30]
    for col in ("open", "high", "low", "close"):
        df[col] = df[col] * scale
    df.iat[31, df.columns.get_loc("open")] = 110.0
    df.iat[31, df.columns.get_loc("high")] = 112.0

    w = pd.Series(0.0, index=df.index)
    w.iloc[30:] = 1.0
    res = run_backtest(df, w)
    buys_on_limit = res.trades[pd.to_datetime(res.trades["date"]) == df.index[31]]
    assert len(buys_on_limit) == 0, "涨停开盘不应成交买入"
