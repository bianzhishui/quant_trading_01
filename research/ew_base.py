#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""等权底仓可行性评估 —— 按 docs/ew_base_plan.md v1.0 实施（持仓模拟版）。

三变体(持仓模拟, 权重随价格漂移, 边界日再平衡):
  EW-月频 / EW-年频(实盘候选) / EW-单次(零成本下限)
  + 日频再平衡(理论上限参考)
新上市股票: 首个有数据日期后才可买入; 停牌日收益视为0(价格延续)。
基准: 沪深300/中证500/中证1000/上证红利 真实指数(无幸存者偏差)。

用法: uv run python research/ew_base.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data_loader import load_index_daily
from research.dividend_factor import load_all, metrics

COST = 15e-4
ERAS = {"2014-2017": ("2014-01-01", "2017-12-31"),
        "2018-2021": ("2018-01-01", "2021-12-31"),
        "2022-2026": ("2022-01-01", None)}


def ew_holdings_sim(ret: pd.DataFrame, freq: str, cost: float) -> pd.Series:
    """等权持仓模拟: 逐日演化, 边界日卖出全部再等权买入当日可交易股票。

    freq: 月频/年频/单次/日频
    ret: 前复权日收益, NaN=当日不可交易(未上市或停牌, 视为价格不变)
    """
    r = ret.fillna(0.0)
    avail = ret.notna()
    vals: dict[str, float] = {}
    cash = 1.0
    nav = []
    prev = ret.index[0]
    first_rebalance_done = False
    for dt in ret.index:
        for c in vals:
            vals[c] *= (1 + r.at[dt, c])
        rebalance = False
        if freq == "月频" and dt.month != prev.month:
            rebalance = True
        elif freq == "年频" and dt.year != prev.year:
            rebalance = True
        elif freq == "单次" and not first_rebalance_done and avail.loc[dt].any():
            rebalance = True                            # 首个可交易日建仓, 之后永不
        if rebalance:
            if freq == "单次":
                first_rebalance_done = True
            sold_total = sum(vals.values())
            cash = cash + sold_total * (1 - cost)       # 卖出全部
            tradable = [c for c in ret.columns if avail.at[dt, c]]
            if tradable:
                per = cash / len(tradable) * (1 - cost)  # 买入也付成本
                vals = {c: per for c in tradable}
                cash = 0.0
            else:
                vals = {}
        nav.append(cash + sum(vals.values()))
        prev = dt
    return pd.Series(nav, index=ret.index)


def main() -> None:
    print("== 等权底仓可行性评估 (预注册 v1.0, 持仓模拟) ==")
    close, real, *_ = load_all()
    ret = close.pct_change()
    print(f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
          f"{close.index[0].date()} ~ {close.index[-1].date()}\n")

    variants = {"EW-月频": "月频",
                "EW-年频(实盘候选)": "年频",
                "EW-单次(不再平衡)": "单次"}
    navs = {}
    for label, freq in variants.items():
        nav = ew_holdings_sim(ret, freq, COST)
        navs[label] = nav
        m = metrics(nav)
        print(f"■ {label}: 年化 {m['年化']:+.1%} 夏普 {m['夏普']:.2f} "
              f"回撤 {m['最大回撤']:.1%}")
    ew_daily = (1 + ret.mean(axis=1)).cumprod()      # 日频再平衡=零成本理论上限
    navs["EW-日频(零成本理论上限)"] = ew_daily
    m = metrics(ew_daily)
    print(f"■ EW-日频(零成本理论上限): 年化 {m['年化']:+.1%} 夏普 {m['夏普']:.2f} "
          f"回撤 {m['最大回撤']:.1%}")

    print()
    bench = {}
    for code, name in [("000300", "沪深300"), ("000905", "中证500"),
                       ("000852", "中证1000"), ("000015", "上证红利")]:
        try:
            s = load_index_daily(code, start="20140101", refresh=False)["close"]
            s = s.reindex(close.index).ffill()
            s = s / s.dropna().iloc[0]
            bench[name] = s
            m = metrics(s)
            print(f"■ {name}(真实指数): 年化 {m['年化']:+.1%} 夏普 {m['夏普']:.2f} "
                  f"回撤 {m['最大回撤']:.1%}")
        except Exception as e:
            print(f"■ {name}: 获取失败({e})")

    ew_a = navs["EW-年频(实盘候选)"]
    mA = metrics(ew_a)
    m5 = metrics(bench.get("中证500"))
    gap = mA["年化"] - m5["年化"]

    print("\n== 关键读数 ==")
    print(f"EW-年频 vs 真实中证500: {mA['年化']:+.1%} vs {m5['年化']:+.1%} "
          f"→ 差值 {gap:+.1%}/年 (幸存者偏差+等权溢价混合估计)")
    for name in ("沪深300", "中证1000", "上证红利"):
        if name in bench:
            mb = metrics(bench[name])
            print(f"EW-年频 vs {name}: 超额 {mA['年化'] - mb['年化']:+.1%}/年")

    stable, total = 0, 0
    for name, (s, e) in ERAS.items():
        a = ew_a[s:e] / ew_a[s:e].dropna().iloc[0]
        ma = metrics(a)
        b = bench["中证500"][s:e] / bench["中证500"][s:e].dropna().iloc[0]
        mb = metrics(b)
        win = ma["年化"] > mb["年化"]
        stable += int(win)
        total += 1
        print(f"  {name}: EW-年频 {ma['年化']:+.1%} vs 中证500 {mb['年化']:+.1%} "
              f"→ {'跑赢' if win else '跑输'}")

    verdict = gap >= 0.03 and stable >= 2
    print(f"\n预注册机械判定: {'成立' if verdict else '不成立'} "
          f"(差值 {gap:+.1%} ≥3pp 且 跑赢段 {stable}/{total})")
    print("⚠ 判定解释: 本实验池=当前成分, 差值中含幸存者偏差, 不可全额外推;"
          "\n  可实盘 harvest 的部分≈中证500/1000 等权指数产品提供的等权溢价")

    fig, ax = plt.subplots(figsize=(11.5, 6))
    for label, nav in navs.items():
        ax.plot(nav, lw=1.2, label=label)
    for name, s in bench.items():
        ax.plot(s, lw=1, alpha=0.7, label=f"{name}(真实)")
    ax.set_yscale("log"); ax.legend(fontsize=9); ax.grid(alpha=0.3)
    ax.set_title("等权底仓三变体(持仓模拟) vs 真实指数 (对数净值)")
    out = Path(__file__).resolve().parent.parent / "output" / "ew_base.png"
    fig.tight_layout(); fig.savefig(out, dpi=130)
    print(f"\n图已保存: {out}")


if __name__ == "__main__":
    main()
