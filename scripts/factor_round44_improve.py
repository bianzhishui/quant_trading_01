#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 44 低价策略改进 —— 按 docs/factor_round44_improve_plan.md v1.0。

变体: V0(2-3,3年扣非,等权) V1(2.3-3.2,3年,等权) V2(2.3-3.2,2年,等权) V3(2.3-3.2,2年,股息加权)
主判: 验证段 2021-2026; 判定 ①-⑤ (vs V0); 附 Round42 口径(n=1)复核。
用法: uv run python scripts/factor_round44_improve.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import load_config
from quant_trading_01.dividend_factor import metrics
from scripts.factor_round41_low_price import (
    build_sets,
    ew_nav,
    load_data,
    ret_matrix,
    COST_BASE,
    COST_HIGH,
)

VAL = ("2021-01-01", "2026-12-31")


def weighted_nav(ret: pd.DataFrame, data: dict, sets: dict, cost: float) -> pd.Series:
    """股息率加权: 权重 = 近3年每股分红/真实价(调仓日), 全0等权兜底。"""
    cols = ret.columns
    W = pd.DataFrame(0.0, index=ret.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    dv, real = data["dv"], data["real"]
    for dt in ret.index:
        if dt in sets:
            S = sets[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                tot_dy = {}
                for c in S:
                    sub = dv[
                        (dv["code"] == c)
                        & (dv["date"] <= dt)
                        & (dv["date"] >= dt - pd.Timedelta(days=365 * 3))
                    ]
                    px = real.loc[dt, c] if c in real.columns else np.nan
                    tot_dy[c] = (
                        sub["cashBeforeTax"].sum() / px if px and px > 0 else 0.0
                    )
                s = pd.Series(tot_dy).clip(lower=0)
                if s.sum() > 0:
                    w[s.index] = s / s.sum()
                else:
                    w[list(S)] = 1.0 / len(S)
        W.iloc[W.index.get_loc(dt)] = w
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
    return (1 + gross - turn * cost).cumprod()


def eval_var(
    data: dict,
    ret: pd.DataFrame,
    price: tuple,
    n_years: int,
    weighted: bool,
    label: str,
) -> dict:
    A, B, C, _, _ = build_sets(data, None, sub_price=price, n_years=n_years)
    nav = (
        weighted_nav(ret, data, B, COST_BASE) if weighted else ew_nav(ret, B, COST_BASE)
    )
    nav45 = (
        weighted_nav(ret, data, B, COST_HIGH) if weighted else ew_nav(ret, B, COST_HIGH)
    )
    navC = ew_nav(ret, C, COST_BASE)
    m = metrics(nav[VAL[0] : VAL[1]] / nav[VAL[0] : VAL[1]].dropna().iloc[0])
    m45 = metrics(nav45[VAL[0] : VAL[1]] / nav45[VAL[0] : VAL[1]].dropna().iloc[0])
    mC = metrics(navC[VAL[0] : VAL[1]] / navC[VAL[0] : VAL[1]].dropna().iloc[0])
    n_hold = [len(s) for s in B.values() if s]
    # 分年度跑赢 vs V0(由主流程比较)
    years = {}
    for y in range(2021, 2027):
        s, e = f"{y}-01-01", f"{y}-12-31"
        by = metrics(nav[s:e] / nav[s:e].dropna().iloc[0])
        cy = metrics(navC[s:e] / navC[s:e].dropna().iloc[0])
        years[y] = by["年化"] - cy["年化"]
    return {
        "label": label,
        "年化": m["年化"],
        "夏普": m["夏普"],
        "回撤": m["最大回撤"],
        "45bp": m45["年化"],
        "C年化": mC["年化"],
        "C回撤": mC["最大回撤"],
        "月均持仓": np.mean(n_hold) if n_hold else 0,
        "years": years,
        "navB": nav,
        "navC": navC,
    }


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("加载数据...", flush=True)
    data = load_data()
    ret_zero = ret_matrix(data["close"], data["out_date"], "zero")
    print(f"数据就绪 {time.time() - t0:.0f}s", flush=True)

    variants = [
        ("V0 基准(2-3,3年)", (2.0, 3.0), 3, False),
        ("V1 2.3-3.2,3年", (2.3, 3.2), 3, False),
        ("V2 2.3-3.2,2年", (2.3, 3.2), 2, False),
        ("V3 2.3-3.2,2年,股息加权", (2.3, 3.2), 2, True),
    ]
    res = {}
    for label, price, ny, w in variants:
        print(f"跑 {label}...", flush=True)
        res[label] = eval_var(data, ret_zero, price, ny, w, label)

    print("\n=== 验证段(2021-2026) 各变体 ===")
    for label, r in res.items():
        print(
            f"  {label}: 年化 {r['年化']:+.1%} 夏普 {r['夏普']:.2f} 回撤 {r['回撤']:.1%} | "
            f"45bp {r['45bp']:+.1%} | 月均持仓 {r['月均持仓']:.0f} | C年化 {r['C年化']:+.1%}"
        )

    v0 = res["V0 基准(2-3,3年)"]
    print("\n=== 判定 (vs V0, ①-⑤全过) ===")
    for label, r in res.items():
        if label == "V0 基准(2-3,3年)":
            continue
        c1 = r["年化"] - v0["年化"] >= 0.02
        c2 = r["回撤"] > v0["回撤"]  # 负数回撤: 更大=更浅
        c3 = r["月均持仓"] >= v0["月均持仓"] and r["月均持仓"] >= 30
        c4 = r["45bp"] - r["C年化"] >= 0.01
        win = sum(1 for y in range(2021, 2027) if r["years"][y] > v0["years"][y])
        c5 = win >= 3
        print(
            f"  {label}: 超额{v0}→{r['年化']:+.1%}({r['年化'] - v0['年化']:+.1%},{c1}) "
            f"回撤{v0['回撤']:.0%}→{r['回撤']:.0%}({c2}) 持仓{v0['月均持仓']:.0f}→{r['月均持仓']:.0f}({c3}) "
            f"45bp超C{r['45bp'] - r['C年化']:+.1%}({c4}) 分年跑赢V0 {win}/6({c5})"
        )
        print(f"    ==> {'通过' if all([c1, c2, c3, c4, c5]) else '未达标'}")

    # Round42 口径复核(n=1)
    print("\n=== 复核: Round42 口径(2-3, n=1 等权) vs V0(3年) ===")
    r42 = eval_var(data, ret_zero, (2.0, 3.0), 1, False, "R42口径")
    print(
        f"  R42(1年): 年化 {r42['年化']:+.1%} 回撤 {r42['回撤']:.1%} 持仓 {r42['月均持仓']:.0f}"
    )
    print(
        f"  V0(3年):  年化 {v0['年化']:+.1%} 回撤 {v0['回撤']:.1%} 持仓 {v0['月均持仓']:.0f}"
    )
    print(
        f"  → 严格3年口径 {v0['年化'] - r42['年化']:+.1%}pp (R41/42/43归档为1年口径, 结果偏乐观方向需注意)"
    )

    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
