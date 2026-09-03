#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""候选 ETF 数据体检 + 份额折算修正 + 指标计算。

新浪源为不复权价格, 宽基 ETF 历史上做过份额拆分/合并(份额折算),
折算日价格跳变会污染整条序列 → 检测 |日收益|>30% 的日期,
推断折算比例(份额倍数 k), 对折算日之前的价格乘 1/k 粘合修正。

用法: uv run python research/etf_candidates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data_loader import load_index_daily, load_stock_daily

POOL = {
    "510500": "中证500ETF(南方)",
    "512100": "中证1000ETF(南方)",
    "159845": "中证1000ETF(华夏)",
    "510300": "沪深300ETF(华泰柏瑞, 对照)",
}
K_SNAP = np.array([0.2, 0.25, 1/3, 0.5, 2, 3, 4, 5, 8, 10])
THRESH = 0.30

ERAS = {"2014-2017": ("2014-01-01", "2017-12-31"),
        "2018-2021": ("2018-01-01", "2021-12-31"),
        "2022-2026": ("2022-01-01", None)}


def glue_splits(px: pd.Series, name: str) -> pd.Series:
    """检测份额折算并粘合: 折算日前价格 × (1/k)。"""
    ret = px.pct_change()
    jumps = ret[ret.abs() > THRESH]
    if jumps.empty:
        print(f"[{name}] 无折算跳变, 序列干净")
        return px
    adj = px.copy()
    for d, r in jumps.items():
        raw_k = px.loc[px.index[px.index.get_loc(d) - 1]] / px.loc[d]
        k = float(K_SNAP[np.argmin(np.abs(np.log(K_SNAP) - np.log(raw_k)))])
        err = abs(raw_k - k) / k
        print(f"[{name}] {d.date()}: {px.loc[px.index[px.index.get_loc(d)-1]]:.3f} → "
              f"{px.loc[d]:.3f} (raw k={raw_k:.4f} → 推断份额倍数 k={k:g}, 偏差{err:.1%})")
        adj[adj.index < d] *= (1 / k)
    return adj


def metrics(px: pd.Series) -> dict:
    px = px.dropna()
    r = px.pct_change().dropna()
    yrs = len(px) / 244
    return {"年化": (px.iloc[-1] / px.iloc[0]) ** (1 / yrs) - 1,
            "波动": r.std() * np.sqrt(244),
            "夏普": r.mean() / r.std() * np.sqrt(244),
            "回撤": float((px / px.cummax() - 1).min())}


def main() -> None:
    print("== ETF 候选体检与修正 ==")
    fixed = {}
    for code, name in POOL.items():
        px = load_stock_daily(code, start="20140101", refresh=False)["close"]
        g = glue_splits(px, code)
        fixed[code] = g
        m = metrics(g)
        print(f"  {code} {name}: 起点 {g.index[0].date()}, 年化 {m['年化']:+.1%}, "
              f"波动 {m['波动']:.1%}, 夏普 {m['夏普']:.2f}, 回撤 {m['回撤']:.1%}, "
              f"最新价 {g.iloc[-1]:.3f} (1手≈{g.iloc[-1]*100:,.0f}元)\n")

    # 交叉验证: 修正后 ETF vs 真实指数(价格口径, ETF≈指数+分红-费率)
    print("== 交叉验证(修正后ETF年化 vs 真实指数年化, 差值应≈分红-费率≈+1pp) ==")
    for code, idx_code in [("510500", "000905"), ("512100", "000852"), ("510300", "000300")]:
        etf = fixed[code]
        idx = load_index_daily(idx_code, start="20140101", refresh=False)["close"]
        idx = idx.reindex(etf.index).ffill()
        i0 = idx.dropna().index[0]
        e, i = etf[i0:], idx[i0:]
        yrs = len(e) / 244
        me = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
        mi = (i.iloc[-1] / i.iloc[0]) ** (1 / yrs) - 1
        print(f"  {code} vs {idx_code}: {me:+.2%} vs {mi:+.2%} → 差 {me-mi:+.2%}/年")

    print("\n== 分年代年化(修正后) ==")
    rows = []
    for code, name in POOL.items():
        px = fixed[code]
        row = {"代码": code, "名称": name}
        for era, (s, t) in ERAS.items():
            seg = px[s:t] if t else px[s:]
            row[era] = (seg.iloc[-1] / seg.iloc[0]) ** (244 / len(seg)) - 1 if len(seg) > 100 else np.nan
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:+.1%}"))


if __name__ == "__main__":
    main()
