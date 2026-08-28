#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""网格交易可行性验证（针对聚宽《q-M-T网格交易策略》帖）。

不复制作者代码(有未来函数嫌疑), 只验证网格交易这个"工具"本身的性质:

    网格规则: 在[下界,上界]画N格, 价格每跌破一格买入一份预算,
              涨回该格上方卖出该份(赚一格价差)。
    验证命题: 网格在震荡市赚钱、单边市吃亏 —— 它是执行工具, 不是预测信号。

对照: 同一参数分别跑在
    ① 512880 证券ETF 全历史(著名震荡标的)
    ② 510300 沪深300 牛市段 2019-2021 (趋势向上 -> 网格应跑输持有)
    ③ 510300 沪深300 熊市段 2022-2024 (趋势向下 -> 网格应少亏但仍亏)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data_loader import _fetch_fund_sina

COST = 1e-3  # 单边0.1%(含滑点)


def grid_backtest(close: pd.Series, n_grids: int = 10,
                  lookback: int = 500) -> dict:
    """区间取过去lookback日的最低/最高价(固定后不重画), 模拟逐日穿越。"""
    c = close.dropna()
    lo, hi = c.iloc[-lookback:].min(), c.iloc[-lookback:].max()
    levels = np.linspace(lo, hi, n_grids + 1)[1:-1]      # 内部格子线
    budget = 1.0                                          # 总预算归一化
    unit = budget / n_grids                               # 每格买入金额

    cash, units = budget, {}                              # units: {格线: 买入价}
    nav = []
    for dt, px in c.items():
        # 先卖: 价格站上格线上方 -> 卖出该格持仓
        for lv in list(units):
            if px >= lv * (1 + 1e-9):
                cash += unit * (1 + (px / units[lv] - 1)) - unit * COST
                del units[lv]
        # 后买: 价格跌破格线 -> 买入一份(该格无持仓时)
        for lv in levels:
            if px <= lv and lv not in units and cash >= unit:
                cash -= unit * (1 + COST)
                units[lv] = px
        nav.append(cash + sum(unit * px / p0 for p0 in units.values()))

    nav = pd.Series(nav, index=c.index)
    bh = c / c.iloc[0]
    return {"网格总收益": nav.iloc[-1] - 1, "买入持有": bh.iloc[-1] - 1,
            "网格回撤": float((nav / nav.cummax() - 1).min()),
            "持有回撤": float((bh / bh.cummax() - 1).min()),
            "成交次数": int((n_grids - len(units)) * 2),  # 近似: 已平仓的格
            "剩余套牢格数": len(units), "nav": nav, "bh": bh}


def report(name: str, r: dict) -> None:
    print(f"\n■ {name}")
    print(f"  网格策略: 收益 {r['网格总收益']:+.1%}  回撤 {r['网格回撤']:.1%}")
    print(f"  买入持有: 收益 {r['买入持有']:+.1%}  回撤 {r['持有回撤']:.1%}")
    print(f"  网格 vs 持有 超额: {r['网格总收益'] - r['买入持有']:+.1%}"
          f"   套牢未平格: {r['剩余套牢格数']}")


def main() -> None:
    print("拉取数据...")
    etf = _fetch_fund_sina("512880", "20160101", "20260831")["close"]
    hs = _fetch_fund_sina("510300", "20160101", "20260831")["close"]

    print(f"512880 震荡性检验: 全历史区间 {etf.min():.2f}~{etf.max():.2f},"
          f" 首尾 {etf.iloc[0]:.2f}→{etf.iloc[-1]:.2f}")
    report("① 证券ETF 512880 全历史 (震荡市假设)", grid_backtest(etf))

    print(f"\n510300 分段验证(同一套网格参数):")
    report("② 牛市段 2019-01 ~ 2021-12", grid_backtest(hs["2019-01-01":"2021-12-31"]))
    report("③ 熊市段 2022-01 ~ 2024-09", grid_backtest(hs["2022-01-01":"2024-09-30"]))

    print("\n" + "=" * 60)
    print("命题检验: 网格在震荡市(①)应跑赢持有; 单边市(②③)应跑输/仍亏损")


if __name__ == "__main__":
    main()
