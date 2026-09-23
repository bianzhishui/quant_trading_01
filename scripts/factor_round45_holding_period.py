#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 45 持有期敏感性 —— 按 docs/factor_round45_holding_period_plan.md v1.0。

同规则(R44 V1: 2.3-3.2元+3年扣非+质量+等权) 对比: 月频/年频/3年/5年持有;
滚动买入持有(每月末起点, 1/3/5年) 胜率/年化分布。判定 ①-⑤。
用法: uv run python scripts/factor_round45_holding_period.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config, load_config
from quant_trading_01.dividend_factor import metrics
from scripts.factor_round41_low_price import (
    build_sets,
    ew_nav,
    load_data,
    ret_matrix,
)

PRICE = (2.3, 3.2)
N_YEARS = 3
VAL = ("2021-01-01", "2026-12-31")
VARIANTS = [("M月频", 1), ("Y年频", 12), ("H3三年", 36), ("H5五年", 60)]


def rolling_hold(ret: pd.DataFrame, sets: dict, horizon_months: int) -> pd.DataFrame:
    """每月末起点买入持有 horizon 个月: 等权日收益(无再平衡), 退市归零在 ret 内。"""
    idx = ret.index
    out = []
    entries = sorted(sets.keys())
    for e in entries:
        S = sets[e]
        if not S:
            continue
        end = e + pd.DateOffset(months=horizon_months)
        mask = (idx > e) & (idx <= end)
        seg = ret.loc[mask, list(S)]
        if len(seg) < 60:
            continue
        total = (1 + seg.mean(axis=1).fillna(0)).prod() - 1
        yrs = len(seg) / 244
        ann = (1 + total) ** (1 / yrs) - 1 if total > -1 else -1.0
        out.append({"entry": e, "total": total, "ann": ann})
    return pd.DataFrame(out)


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("加载数据...", flush=True)
    data = load_data()
    ret = ret_matrix(data["close"], data["out_date"], "zero")
    print(f"数据就绪 {time.time() - t0:.0f}s", flush=True)

    print("\n=== 各频率验证段(2021-2026) ===")
    res = {}
    for label, freq in VARIANTS:
        A, B, C, _, _ = build_sets(
            data, None, sub_price=PRICE, n_years=N_YEARS, freq=freq
        )
        nav = ew_nav(ret, B, get_config().costs.cost_base)
        nav45 = ew_nav(ret, B, get_config().costs.cost_high)
        m = metrics(nav[VAL[0] : VAL[1]] / nav[VAL[0] : VAL[1]].dropna().iloc[0])
        m45 = metrics(nav45[VAL[0] : VAL[1]] / nav45[VAL[0] : VAL[1]].dropna().iloc[0])
        res[label] = {
            "年化": m["年化"],
            "夏普": m["夏普"],
            "回撤": m["最大回撤"],
            "45bp": m45["年化"],
            "nav": nav,
        }
        print(
            f"  {label}: 年化 {m['年化']:+.1%} 夏普 {m['夏普']:.2f} 回撤 {m['最大回撤']:.1%} | 45bp {m45['年化']:+.1%}"
        )
    M = res["M月频"]
    # 全市场(月频 C)
    A, B, C, _, _ = build_sets(data, None, sub_price=PRICE, n_years=N_YEARS, freq=1)
    navC = ew_nav(ret, C, get_config().costs.cost_base)
    mC = metrics(navC[VAL[0] : VAL[1]] / navC[VAL[0] : VAL[1]].dropna().iloc[0])
    print(f"  全市场: 年化 {mC['年化']:+.1%} 回撤 {mC['最大回撤']:.1%}")

    print("\n=== 滚动买入持有(全样本每月末起点) ===")
    A, B, C, _, _ = build_sets(data, None, sub_price=PRICE, n_years=N_YEARS, freq=1)
    for h in [12, 36, 60]:
        rh = rolling_hold(ret, B, h)
        if not len(rh):
            print(f"  {h // 12}年: 无样本")
            continue
        win = (rh["ann"] > 0).mean()
        print(
            f"  {h // 12}年持有({len(rh)} 个起点): 胜率 {win:.0%} | 年化 中位 {rh['ann'].median():+.1%} "
            f"最差 {rh['ann'].min():+.1%} 最好 {rh['ann'].max():+.1%}"
        )
        if h == 36:
            rh36 = rh
    # 判定 ③: 3年滚动胜率
    win3 = (rh36["ann"] > 0).mean() if "rh36" in dir() else 0

    print("\n=== 判定 (①-⑤全过=通过) ===")
    for h_label, freq in [("H3三年", 36), ("H5五年", 60)]:
        r = res[h_label]
        c1 = r["年化"] >= M["年化"] - 0.02
        c2 = r["回撤"] <= M["回撤"] + 0.05
        c3 = win3 >= 0.60 if h_label == "H3三年" else True
        c4 = r["年化"] > mC["年化"]
        c5 = r["45bp"] > mC["年化"]
        print(
            f"  {h_label}: ①vs月频 {r['年化'] - M['年化']:+.1%}(≥-2pp:{c1}) "
            f"②回撤 {r['回撤']:.1%}(≤月频+5pp:{c2}) ③3年胜率{win3:.0%}(≥60%:{c3}) "
            f"④vs全市场 {r['年化'] - mC['年化']:+.1%}({c4}) ⑤45bp {r['45bp'] - mC['年化']:+.1%}({c5})"
        )
        print(f"    ==> {'通过' if all([c1, c2, c3, c4, c5]) else '未达标'}")

    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
