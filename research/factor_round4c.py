#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 4c 风险加固·风控层 —— 严格按 docs/factor_round4c_trend_breaker_plan.md v1.0 实施。

C 持仓 + 均线择时熔断（沪深300 vs MA200，两态 1.0/0.5，2% 迟滞带）。
触发信号 = 市场趋势（唯一改动，与 4b 的自身回撤信号对照）。
用法: uv run python research/factor_round4c.py
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
from research.dividend_factor import load_all, month_last_days, metrics
from research.reversal_factor import ERAS, build_pool
from src.data_loader import load_index_daily

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
MIN_N = 50
MA_WIN = 200
BAND = 0.02  # 迟滞带 ±2%


def _pct(vals: pd.Series) -> pd.Series:
    return vals.rank(pct=True)


def build_weight_matrix(ret: pd.DataFrame, sets: dict) -> pd.DataFrame:
    cols = ret.columns
    W = pd.DataFrame(0.0, index=ret.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    for dt in ret.index:
        if dt in sets:
            S = sets[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                w[list(S)] = 1.0 / len(S)
        W.loc[dt] = w
    return W


def scaled_nav(
    ret: pd.DataFrame, W: pd.DataFrame, f: pd.Series, cost: float
) -> pd.Series:
    scaled = W.multiply(f, axis=0)
    turn = scaled.diff().abs().sum(axis=1).fillna(0.0)
    gross = (scaled.shift(1).fillna(0.0) * ret.fillna(0.0)).sum(axis=1)
    return (1 + gross - turn * cost).cumprod()


def trend_factor(idx_close: pd.Series) -> tuple[pd.Series, list]:
    """沪深300 vs MA200 → f ∈ {1.0, 0.5}，2% 迟滞带。返回 (f, 触发记录)。"""
    ma = idx_close.rolling(MA_WIN).mean()
    f = pd.Series(1.0, index=idx_close.index)
    state = 1.0
    triggers = []
    for t in idx_close.index:
        c = idx_close.loc[t]
        if np.isnan(ma.loc[t]):
            f.loc[t] = state
            continue
        up = ma.loc[t] * (1 + BAND)
        dn = ma.loc[t] * (1 - BAND)
        if state == 1.0 and c < dn:
            state = 0.5
            triggers.append((t, "1→0.5(跌破MA200)"))
        elif state == 0.5 and c > up:
            state = 1.0
            triggers.append((t, "0.5→1(上穿MA200)"))
        f.loc[t] = state
    return f, triggers


def max_dd_episode(nav: pd.Series) -> tuple[str, str, float]:
    cummax = nav.cummax()
    dd = nav / cummax - 1
    trough_i = dd.idxmin()
    peak_i = nav[:trough_i].idxmax()
    return str(peak_i.date()), str(trough_i.date()), float(dd.min())


def main() -> None:
    print("== Round 4c 均线择时熔断 (预注册 v1.0): C 持仓 + 市场趋势 ==")
    close, *_ = load_all()
    ret_qfq = close.pct_change()
    pool = build_pool(close, *load_all()[3:5])

    amt = pd.read_parquet(R2 / "daily_ext.parquet")
    amt["date"] = pd.to_datetime(amt["date"])
    amount = amt.pivot(index="date", columns="code", values="amount").sort_index()
    amount = amount.reindex(index=close.index, columns=close.columns).ffill()

    amihud = (
        ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    )
    mom = close.shift(21) / close.shift(250) - 1.0

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    sets_C: dict = {}
    bench_sets: dict = {}
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        common = a.index.intersection(m.index)
        if len(common) < MIN_N:
            continue
        if k + 1 < len(sig_days):
            bench_sets[exec_day] = set(common)
        score = (_pct(a.reindex(common)) + _pct(m.reindex(common))) / 2
        q = pd.qcut(score.rank(method="first"), 5, labels=False)
        sets_C[exec_day] = set(score.index[q == 4])

    W = build_weight_matrix(ret_qfq, sets_C)
    from research.reversal_factor import ew_nav

    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]

    navC = (
        1
        + (W.shift(1).fillna(0.0) * ret_qfq.fillna(0.0)).sum(axis=1)
        - W.diff().abs().fillna(0.0).sum(axis=1) * COST
    ).cumprod()

    # 沪深300 收盘（趋势信号）
    hs300 = load_index_daily("000300", start="20130601", refresh=False)["close"]
    hs300 = hs300.reindex(close.index).ffill()
    f, triggers = trend_factor(hs300)

    navR4c = scaled_nav(ret_qfq, W, f, COST)

    print(f"调仓期数 {len(bench_sets)}, 基准(公共池等权) 年化 {ann_bench:+.1%}")
    print(
        f"均线信号触发 {len(triggers)} 次 → {triggers[:3] + (['...'] if len(triggers) > 3 else [])}"
    )
    print(f"净值日分布: 满仓 {(f == 1.0).mean():.1%}, 半仓 {(f == 0.5).mean():.1%}")

    rows, navs = {}, {}
    for k, nav in [("C", navC), ("R4c", navR4c)]:
        pk, tr, mdd = max_dd_episode(nav)
        era_exc = {}
        for era, (s, e_) in ERAS.items():
            a, b = nav[s:e_], nav_bench[s:e_]
            era_exc[era] = (
                metrics(a / a.dropna().iloc[0])["年化"]
                - metrics(b / b.dropna().iloc[0])["年化"]
            )
        scaled = W.multiply(f if k == "R4c" else 1.0, axis=0)
        turn = float(scaled.diff().abs().sum(axis=1).sum() / 2 / (len(nav) / 244))
        nav35 = scaled_nav(ret_qfq, W, f if k == "R4c" else 1.0, COST_SWEEP[1])
        rows[k] = {
            "臂": k,
            "超额15bp": round(metrics(nav)["年化"] - ann_bench, 4),
            "超额35bp": round(metrics(nav35)["年化"] - ann_bench, 4),
            "年换手": round(turn, 1),
            "夏普": round(metrics(nav)["夏普"], 2),
            "最大回撤": round(mdd, 3),
            "回撤区间": f"{pk}~{tr}",
            **{f"超额{era}": round(v, 4) for era, v in era_exc.items()},
        }
        navs[k] = nav
        print(
            f"\n■ {k}: 超额15bp {rows[k]['超额15bp']:+.1%} | 35bp {rows[k]['超额35bp']:+.1%} "
            f"| 年换手 {turn:.1f} | 夏普 {rows[k]['夏普']:.2f} "
            f"| 最大回撤 {mdd:.1%} ({pk}~{tr})"
        )
        print(
            "   分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items())
        )

    # 逐年最大回撤（对比 2018 是否被补上）
    ddC = navC / navC.cummax() - 1
    ddR = navR4c / navR4c.cummax() - 1
    print("\n逐年最大回撤 (C / R4c):")
    for y in range(2015, 2027):
        sC, sR = ddC[f"{y}-01-01" : f"{y}-12-31"], ddR[f"{y}-01-01" : f"{y}-12-31"]
        if len(sC) and len(sR):
            print(f"  {y}: C {sC.min():.1%} | R4c {sR.min():.1%}")

    C, R = rows["C"], rows["R4c"]
    j1 = R["最大回撤"] >= -0.30
    j2 = R["超额15bp"] >= 0.05
    j3 = R["超额35bp"] > 0
    j4 = sum(R[f"超额{era}"] > 0 for era in ERAS) >= 2
    n_pass = sum([j1, j2, j3, j4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    print("\n== 判定 (R4c vs C) ==")
    print(f"  J1 最大回撤≥-30%: C {C['最大回撤']:.1%} → R4c {R['最大回撤']:.1%} → {j1}")
    print(f"  J2 超额≥+5pp: R4c {R['超额15bp']:+.1%} → {j2}")
    print(f"  J3 35bp 超额>0: R4c {R['超额35bp']:+.1%} → {j3}")
    print(f"  J4 三段≥2 正: {sum(R[f'超额{era}'] > 0 for era in ERAS)}/3 → {j4}")
    print(f"  → R4c 判定: {verdict}({n_pass}/4)")

    pd.DataFrame(rows).T.to_csv(OUT / "factor_round4c_summary.csv")
    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(navs["C"], lw=1.3, label="C 满仓")
    ax.plot(navs["R4c"], lw=1.5, label="R4c C+均线择时")
    ax.plot(nav_bench, lw=1, alpha=0.6, color="gray", label="同池等权基准")
    ax2 = ax.twinx()
    ax2.fill_between(f.index, f.values, alpha=0.15, color="orange")
    ax2.set_ylabel("仓位 f")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)
    ax.set_title("Round 4c 均线择时熔断 (对数净值, 15bp; 橙色=仓位)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round4c.png", dpi=130)
    print("\nCSV: output/factor_round4c_summary.csv | 图: output/factor_round4c.png")


if __name__ == "__main__":
    main()
