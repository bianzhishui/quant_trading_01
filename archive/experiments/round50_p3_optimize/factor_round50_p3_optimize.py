#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 50 P3 优化空间验证 —— 按 docs/factor_round50_p3_optimize_plan.md。

变体(固定):
  P0  基准 = P3 现口径(3.0-4.0 + 3年扣非 + 负债<70% + 流动性≥500万 + 分红 + 非ST + 等权月频)
  E1a 质量 + 近3年年报 ocf_ps 均为正
  E1b 质量 + 近3年年报 ocf_ps 之和 > 0
  E2  月频 → 每 10 个交易日调仓(≈双周)
  E3  不改策略: 同引擎"含阻塞 vs 无阻塞"对照(仅量化口径影响)

主判: 验证段 2021-2026; 回测口径与 R41-47 一致(ew_nav, 15bp 基准/45bp 压测/60bp 极端, 退市归零)。
用法: uv run python scripts/factor_round50_p3_optimize.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from quant_trading_01.config import load_config  # noqa: E402
from quant_trading_01.dividend_factor import metrics  # noqa: E402
from scripts.factor_round41_low_price import (  # noqa: E402
    build_sets,
    ew_nav,
    load_data,
    ret_matrix,
)

VAL = ("2021-01-01", "2026-12-31")
P3KW = dict(sub_price=(3.0, 4.0), n_years=3)
C15, C45, C60 = 0.0015, 0.0045, 0.0060


def sig_10d(idx: pd.DatetimeIndex) -> list:
    """每 10 个交易日收盘(≈双周)作为信号日(R50 E2)。"""
    return [t for i, t in enumerate(idx) if i % 10 == 0]


def val_m(nav: pd.Series) -> dict:
    """验证段指标(归一化到段首)。"""
    seg = nav[VAL[0] : VAL[1]].dropna()
    if len(seg) < 50:
        return {"年化": np.nan, "夏普": np.nan, "最大回撤": np.nan}
    return metrics(seg / seg.iloc[0])


def yearly_ret(nav: pd.Series) -> dict:
    out = {}
    for y, seg in nav.groupby(nav.index.year):
        seg = seg.dropna()
        if len(seg) >= 2:
            out[y] = seg.iloc[-1] / seg.iloc[0] - 1
    return out


def run_variant(data: dict, ret: pd.DataFrame, kw: dict, label: str) -> dict:
    A, B, C, _, _ = build_sets(data, None, **kw)
    navs = {c: ew_nav(ret, B, c) for c in (C15, C45, C60)}
    m = {c: val_m(v) for c, v in navs.items()}
    n_hold = [len(s) for s in B.values() if s]
    n_hold22 = [len(s) for d, s in B.items() if s and d.year >= 2022]
    return {
        "label": label,
        "年化": m[C15]["年化"],
        "夏普": m[C15]["夏普"],
        "回撤": m[C15]["最大回撤"],
        "45bp": m[C45]["年化"],
        "60bp": m[C60]["年化"],
        "全样本年化": metrics(navs[C15])["年化"],
        "全样本回撤": metrics(navs[C15])["最大回撤"],
        "月均持仓": float(np.mean(n_hold)) if n_hold else 0.0,
        "近年持仓": float(np.mean(n_hold22)) if n_hold22 else 0.0,
        "yr": yearly_ret(navs[C15]),
        "n_reb": len(n_hold),
    }


def fmt_pct(x: float) -> str:
    return "n/a" if x != x else f"{x:+.1%}"


def main() -> None:
    cfg = load_config(None)
    t0 = time.time()
    print(
        f"== Round 50 P3 优化空间验证 == 数据加载({time.time() - t0:.0f}s)", flush=True
    )
    data = load_data()
    ret = ret_matrix(data["close"], data["out_date"], "zero")
    idx = data["close"].index
    print(
        f"数据就绪 {time.time() - t0:.0f}s | {idx[0].date()} → {idx[-1].date()}",
        flush=True,
    )

    # 全市场等权基准(验证段, 15bp / 45bp 双口径)
    A, B, C, _, _ = build_sets(data, None)
    navC15, navC45 = ew_nav(ret, C, C15), ew_nav(ret, C, C45)
    mC15, mC45 = val_m(navC15), val_m(navC45)
    print(
        f"全市场等权基准(验证段): 15bp {fmt_pct(mC15['年化'])} | 45bp {fmt_pct(mC45['年化'])}",
        flush=True,
    )

    variants = [
        ("P0 基准", dict(P3KW)),
        ("E1a 现金流全正", dict(P3KW, ocf_mode="all")),
        ("E1b 现金流和为", dict(P3KW, ocf_mode="sum")),
        ("E2 双周频", dict(P3KW, sig_days=sig_10d(idx))),
    ]
    res = {}
    for label, kw in variants:
        print(f"跑 {label}... ({time.time() - t0:.0f}s)", flush=True)
        res[label] = run_variant(data, ret, kw, label)

    p0 = res["P0 基准"]
    print("\n=== 验证段 2021-2026（15bp 基准口径） ===")
    for label, r in res.items():
        print(
            f"  {label:16s} 年化 {fmt_pct(r['年化'])} | 夏普 {r['夏普']:.2f} | "
            f"回撤 {r['回撤']:.1%} | 45bp {fmt_pct(r['45bp'])} | 60bp {fmt_pct(r['60bp'])} | "
            f"持仓 月均{r['月均持仓']:.0f}/近年{r['近年持仓']:.0f} | 全样本 {fmt_pct(r['全样本年化'])}"
        )

    # ---- E1 判定 ----
    print("\n=== E1 判定（vs P0，预注册判据 ①-⑤） ===")
    for label in ("E1a 现金流全正", "E1b 现金流和为"):
        r = res[label]
        c1 = (r["年化"] >= p0["年化"] + 0.02) or (r["夏普"] >= p0["夏普"] + 0.10)
        c2 = r["回撤"] <= p0["回撤"] + 0.03
        c3 = r["近年持仓"] >= 30
        c4 = r["45bp"] - mC45["年化"] >= 0.01
        wins = sum(1 for y in r["yr"] if y in p0["yr"] and r["yr"][y] > p0["yr"][y])
        c5 = wins >= len(r["yr"]) / 2
        ok = all([c1, c2, c3, c4, c5])
        print(
            f"  {label}: ①年化{r['年化'] - p0['年化']:+.1%}/夏普{r['夏普'] - p0['夏普']:+.2f}({c1}) "
            f"②回撤{r['回撤'] - p0['回撤']:+.1%}({c2}) ③近年持仓{r['近年持仓']:.0f}({c3}) "
            f"④45bp超C{r['45bp'] - mC45['年化']:+.1%}({c4}) ⑤年胜{wins}/{len(r['yr'])}({c5}) "
            f"=> {'通过' if ok else '未达标'}"
        )

    # ---- E2 判定 ----
    print("\n=== E2 判定（双周频，净额判据） ===")
    e2 = res["E2 双周频"]
    k1 = e2["45bp"] >= p0["45bp"] + 0.01
    k2 = e2["回撤"] <= p0["回撤"] + 0.03
    k3 = e2["60bp"] >= p0["60bp"]
    ok2 = all([k1, k2, k3])
    print(
        f"  45bp: E2 {fmt_pct(e2['45bp'])} vs P0 {fmt_pct(p0['45bp'])} "
        f"(差 {e2['45bp'] - p0['45bp']:+.2%}, {k1}) | "
        f"回撤差 {e2['回撤'] - p0['回撤']:+.1%}({k2}) | "
        f"60bp E2 {fmt_pct(e2['60bp'])} vs P0 {fmt_pct(p0['60bp'])} ({k3}) "
        f"=> {'通过' if ok2 else '未达标'}"
    )
    print(f"  (15bp 口径参考: E2 {fmt_pct(e2['年化'])} vs P0 {fmt_pct(p0['年化'])})")
    print(f"  调仓次数: E2 {e2['n_reb']} vs P0 {p0['n_reb']}")

    # ---- E3 阻塞口径 ----
    print(
        f"\n=== E3 阻塞口径对照（同引擎, 600万, {time.time() - t0:.0f}s） ===",
        flush=True,
    )
    from scripts.p3.scenario_ytd_p3 import run_scenario_p3

    nav_b = run_scenario_p3("2014-01-01", None, None, False, [6000000], True)["aum600w"]
    nav_i = run_scenario_p3("2014-01-01", None, None, False, [6000000], False)[
        "aum600w"
    ]
    mb, mi = val_m(nav_b), val_m(nav_i)
    # 场景 NAV 以 aum 起(非 1.0) → 全样本必须先归一化再算年化
    fb = metrics(nav_b / nav_b.dropna().iloc[0])
    fi = metrics(nav_i / nav_i.dropna().iloc[0])
    print(
        f"  验证段: 含阻塞 {fmt_pct(mb['年化'])} / 无阻塞 {fmt_pct(mi['年化'])} "
        f"= 高估 {mi['年化'] - mb['年化']:+.2%}/年"
    )
    print(
        f"  全样本: 含阻塞 {fmt_pct(fb['年化'])} / 无阻塞 {fmt_pct(fi['年化'])} "
        f"= 高估 {fi['年化'] - fb['年化']:+.2%}/年"
    )
    for name, (s, e) in cfg.r5.eras.to_dict().items():
        sb, si = nav_b[s:e], nav_i[s:e]
        if len(sb.dropna()) > 50:
            eb = metrics(sb / sb.dropna().iloc[0])["年化"]
            ei = metrics(si / si.dropna().iloc[0])["年化"]
            print(
                f"    {name}: 含阻塞 {fmt_pct(eb)} / 无阻塞 {fmt_pct(ei)} = {ei - eb:+.2%}"
            )
    diff = mi["年化"] - mb["年化"]
    print(
        f"\n  => 无阻塞口径高估 {diff:+.2%}（{'≤1pp, R41-47 结论稳健' if diff <= 0.01 else '>1pp, 须在手册标注高估幅度'}）"
    )
    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
