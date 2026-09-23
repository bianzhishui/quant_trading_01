#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 46 收益更大化扩散探索 —— 按 docs/factor_round46_maximize_plan.md v1.0。

9 变体(固定): V1基准/Q1 5年扣非/Q2 ROE>5%/Q3 股息率>=2%/Q4 动量过滤/
P1 2.5-3.5/P2 2.0-4.0/P3 3.0-4.0/C1 固定30只/C3 质量加权。
判定: 验证段 ①年化>V1 ②回撤<=V1+3pp ③夏普>=V1 ④45bp超全市场>=3pp ⑤分段全正。
用法: uv run python scripts/factor_round46_maximize.py
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


def quality_weighted_nav(
    ret: pd.DataFrame, data: dict, sets: dict, cost: float
) -> pd.Series:
    """C3: 权重 ∝ 最新ROE × 近3年股息率(调仓日), 全0等权兜底。"""
    cols = ret.columns
    W = pd.DataFrame(0.0, index=ret.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    dv, real, roe = data["dv"], data["real"], data["roe"]
    for dt in ret.index:
        if dt in sets:
            S = sets[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                vis = roe.index[roe.index + pd.Timedelta(days=120) <= dt]
                q = {}
                for c in S:
                    rv = roe.loc[vis[-1], c] if len(vis) else np.nan
                    sub = dv[
                        (dv["code"] == c)
                        & (dv["date"] <= dt)
                        & (dv["date"] >= dt - pd.Timedelta(days=365 * 3))
                    ]
                    px = real.loc[dt, c] if c in real.columns else np.nan
                    dy = sub["cashBeforeTax"].sum() / px if px and px > 0 else 0.0
                    q[c] = (rv if rv == rv else 0.0) * dy
                s = pd.Series(q).clip(lower=0)
                if s.sum() > 0:
                    w[s.index] = s / s.sum()
                else:
                    w[list(S)] = 1.0 / len(S)
        W.iloc[W.index.get_loc(dt)] = w
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
    return (1 + gross - turn * cost).cumprod()


def eval_var(
    data: dict, ret: pd.DataFrame, kw: dict, label: str, weighted: bool = False
) -> dict:
    A, B, C, _, _ = build_sets(data, None, **kw)
    nav = (
        quality_weighted_nav(ret, data, B, COST_BASE)
        if weighted
        else ew_nav(ret, B, COST_BASE)
    )
    nav45 = (
        quality_weighted_nav(ret, data, B, COST_HIGH)
        if weighted
        else ew_nav(ret, B, COST_HIGH)
    )
    m = metrics(nav[VAL[0] : VAL[1]] / nav[VAL[0] : VAL[1]].dropna().iloc[0])
    m45 = metrics(nav45[VAL[0] : VAL[1]] / nav45[VAL[0] : VAL[1]].dropna().iloc[0])
    mfull = metrics(nav)
    n_hold = [len(s) for s in B.values() if s]
    eras = {}
    for name, (s, e) in load_config(None).strategy.eras.to_dict().items():
        eras[name] = metrics(nav[s:e] / nav[s:e].dropna().iloc[0])["年化"]
    return {
        "label": label,
        "年化": m["年化"],
        "夏普": m["夏普"],
        "回撤": m["最大回撤"],
        "45bp": m45["年化"],
        "全样本年化": mfull["年化"],
        "全样本回撤": mfull["最大回撤"],
        "月均持仓": np.mean(n_hold) if n_hold else 0,
        "eras": eras,
    }


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("加载数据...", flush=True)
    data = load_data()
    ret = ret_matrix(data["close"], data["out_date"], "zero")
    print(f"数据就绪 {time.time() - t0:.0f}s", flush=True)

    # C 全市场基准(验证段)
    A, B, C, _, _ = build_sets(data, None)
    navC = ew_nav(ret, C, COST_BASE)
    mC = metrics(navC[VAL[0] : VAL[1]] / navC[VAL[0] : VAL[1]].dropna().iloc[0])

    variants = [
        ("V1基准", dict(sub_price=(2.3, 3.2), n_years=3), False),
        ("Q1 5年扣非", dict(sub_price=(2.3, 3.2), n_years=5), False),
        ("Q2 ROE>5%", dict(sub_price=(2.3, 3.2), n_years=3, roe_min=5.0), False),
        ("Q3 股息率>=2%", dict(sub_price=(2.3, 3.2), n_years=3, dy_min=0.02), False),
        ("Q4 动量过滤", dict(sub_price=(2.3, 3.2), n_years=3, mom_drop=0.4), False),
        ("P1 2.5-3.5", dict(sub_price=(2.5, 3.5), n_years=3), False),
        ("P2 2.0-4.0", dict(sub_price=(2.0, 4.0), n_years=3), False),
        ("C1 P3+ROE", dict(sub_price=(3.0, 4.0), n_years=3, roe_min=0.05), False),
        ("C2 +5年扣非", dict(sub_price=(3.0, 4.0), n_years=5, roe_min=0.05), False),
        (
            "C3 +股息率2%",
            dict(sub_price=(3.0, 4.0), n_years=3, roe_min=0.05, dy_min=0.02),
            False,
        ),
        ("C4 2.6-3.6+ROE", dict(sub_price=(2.6, 3.6), n_years=3, roe_min=0.05), False),
        ("B1 4-5+ROE", dict(sub_price=(4.0, 5.0), n_years=3, roe_min=0.05), False),
        ("B2 4-5", dict(sub_price=(4.0, 5.0), n_years=3), False),
        (
            "C5 +动量",
            dict(sub_price=(3.0, 4.0), n_years=3, roe_min=0.05, mom_drop=0.4),
            False,
        ),
        ("C1 固定30只", dict(sub_price=(2.3, 3.2), n_years=3, top_n=30), False),
        ("C3 质量加权", dict(sub_price=(2.3, 3.2), n_years=3), True),
    ]
    res = {}
    for label, kw, w in variants:
        print(f"跑 {label}...", flush=True)
        res[label] = eval_var(data, ret, kw, label, weighted=w)

    print("\n=== 验证段(2021-2026) ===")
    for label, r in res.items():
        print(
            f"  {label}: 年化 {r['年化']:+.1%} 夏普 {r['夏普']:.2f} 回撤 {r['回撤']:.1%} | "
            f"45bp {r['45bp']:+.1%} | 持仓 {r['月均持仓']:.0f} | 全样本 {r['全样本年化']:+.1%}/{r['全样本回撤']:.0%}"
        )
    v1 = res["V1基准"]
    print("\n=== 判定 (vs V1, 验证段 ①-⑤全过) ===")
    passed = []
    for label, r in res.items():
        if label == "V1基准":
            continue
        c1 = r["年化"] > v1["年化"]
        c2 = r["回撤"] <= v1["回撤"] + 0.03
        c3 = r["夏普"] >= v1["夏普"]
        c4 = r["45bp"] - mC["年化"] >= 0.03
        c5 = all(v > 0 for v in r["eras"].values())
        ok = all([c1, c2, c3, c4, c5])
        if ok:
            passed.append(label)
        print(
            f"  {label}: 年化{r['年化'] - v1['年化']:+.1%}({c1}) 回撤{r['回撤'] - v1['回撤']:+.1%}({c2}) "
            f"夏普{r['夏普'] - v1['夏普']:+.2f}({c3}) 45bp超C{r['45bp'] - mC['年化']:+.1%}({c4}) 分段{'✓' if c5 else '✗'} "
            f"=> {'通过' if ok else '未达标'}"
        )
    print(f"\n通过变体: {passed or '无'}")
    if passed:
        best = max(passed, key=lambda x: res[x]["年化"])
        print(f"最优通过者: {best} (验证段年化 {res[best]['年化']:+.1%})")
    else:
        print("结论: V1 已接近局部最优, 收益更大化空间有限(预注册收尾)")
    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
