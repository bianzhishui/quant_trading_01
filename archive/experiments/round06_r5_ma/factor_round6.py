#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 6 收尾 —— 严格按 docs/factor_round6_r5_ma_plan.md v1.0 实施。

R5（行业内排名前20%） vs R5+4c（同持仓 + 沪深300<MA200 仓位缩放）。
判定看 R5+4c 的 P1~P4。
用法: uv run python research/factor_round6.py
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
from research.reversal_factor import ERAS, build_pool, ew_nav
from src.data_loader import load_index_daily

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
COST = 15e-4
COST_SWEEP = [35e-4]
MIN_N = 50
MIN_IND = 5
MA_WIN = 200
BAND = 0.02


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


def trend_breaker(idx_close: pd.Series) -> pd.Series:
    ma = idx_close.rolling(MA_WIN).mean()
    f = pd.Series(1.0, index=idx_close.index)
    state = 1.0
    for t in idx_close.index:
        c = idx_close.loc[t]
        if np.isnan(ma.loc[t]):
            f.loc[t] = state
            continue
        if state == 1.0 and c < ma.loc[t] * (1 - BAND):
            state = 0.5
        elif state == 0.5 and c > ma.loc[t] * (1 + BAND):
            state = 1.0
        f.loc[t] = state
    return f


def max_dd_episode(nav: pd.Series) -> tuple[str, str, float]:
    cummax = nav.cummax()
    dd = nav / cummax - 1
    trough_i = dd.idxmin()
    peak_i = nav[:trough_i].idxmax()
    return str(peak_i.date()), str(trough_i.date()), float(dd.min())


def main() -> None:
    print("== Round 6 收尾 (预注册 v1.0): R5 vs R5+4c 均线择时 ==")
    close, *_ = load_all()
    ret_qfq = close.pct_change()
    pool = build_pool(close, *load_all()[3:5])
    ind = pd.read_parquet(R2 / "industry.parquet").set_index("code")["industry"]

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
    sets_R5: dict = {}
    bench_sets: dict = {}
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        common = a.index.intersection(m.index)
        ind_s = ind.reindex(common)
        keep = ind_s.value_counts()[ind_s.value_counts() >= MIN_IND].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < MIN_N:
            continue
        if k + 1 < len(sig_days):
            bench_sets[exec_day] = set(codes)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = (pa + pm) / 2
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        sets_R5[exec_day] = set(codes[q == 4])

    W = build_weight_matrix(ret_qfq, sets_R5)
    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    navR5 = (
        1
        + (W.shift(1).fillna(0.0) * ret_qfq.fillna(0.0)).sum(axis=1)
        - W.diff().abs().fillna(0.0).sum(axis=1) * COST
    ).cumprod()

    hs300 = load_index_daily("000300", start="20130601", refresh=False)["close"]
    hs300 = hs300.reindex(close.index).ffill()
    f = trend_breaker(hs300)
    navR5_4c = scaled_nav(ret_qfq, W, f, COST)
    navR5_4c35 = scaled_nav(ret_qfq, W, f, COST_SWEEP[0])

    print(
        f"调仓期数 {len(bench_sets)}, 基准年化 {ann_bench:+.1%}; "
        f"均线信号: 满仓 {(f == 1.0).mean():.1%} 半仓 {(f == 0.5).mean():.1%}"
    )

    rows = {}
    for k, nav, tnav in [("R5", navR5, None), ("R5+4c", navR5_4c, navR5_4c35)]:
        pk, tr, mdd = max_dd_episode(nav)
        era_exc = {}
        for era, (s, e_) in ERAS.items():
            a, b = nav[s:e_], nav_bench[s:e_]
            era_exc[era] = (
                metrics(a / a.dropna().iloc[0])["年化"]
                - metrics(b / b.dropna().iloc[0])["年化"]
            )
        scaled = W.multiply(f if k == "R5+4c" else 1.0, axis=0)
        turn = float(scaled.diff().abs().sum(axis=1).sum() / 2 / (len(nav) / 244))
        rows[k] = {
            "臂": k,
            "超额15bp": round(metrics(nav)["年化"] - ann_bench, 4),
            "超额35bp": round(
                (metrics(tnav)["年化"] - ann_bench)
                if tnav is not None
                else (metrics(nav)["年化"] - ann_bench),
                4,
            ),
            "年换手": round(turn, 1),
            "夏普": round(metrics(nav)["夏普"], 2),
            "最大回撤": round(mdd, 3),
            "回撤区间": f"{pk}~{tr}",
            **{f"超额{era}": round(v, 4) for era, v in era_exc.items()},
        }
        print(
            f"\n■ {k}: 超额15bp {rows[k]['超额15bp']:+.1%} | 35bp {rows[k]['超额35bp']:+.1%} "
            f"| 换手 {turn:.1f} | 夏普 {rows[k]['夏普']:.2f} | 回撤 {mdd:.1%} ({pk}~{tr})"
        )
        print(
            "   分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items())
        )

    R5, R5c = rows["R5"], rows["R5+4c"]
    p1 = R5c["最大回撤"] >= -0.35
    p2 = R5c["超额15bp"] >= 0.03
    p3 = R5c["超额35bp"] > 0
    p4 = sum(R5c[f"超额{era}"] > 0 for era in ERAS) >= 2
    n_pass = sum([p1, p2, p3, p4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    print("\n== 判定 (R5+4c vs R5) ==")
    print(
        f"  P1 回撤≥-35%: R5 {R5['最大回撤']:.1%} → R5+4c {R5c['最大回撤']:.1%} → {p1}"
    )
    print(
        f"  P2 超额≥+3pp: R5 {R5['超额15bp']:+.1%} → R5+4c {R5c['超额15bp']:+.1%} → {p2}"
    )
    print(f"  P3 35bp 超额>0: {R5c['超额35bp']:+.1%} → {p3}")
    print(f"  P4 三段≥2 正: {sum(R5c[f'超额{era}'] > 0 for era in ERAS)}/3 → {p4}")
    print(f"  → R5+4c 判定: {verdict}({n_pass}/4)")

    pd.DataFrame(rows).T.to_csv(OUT / "factor_round6_summary.csv")
    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(navR5, lw=1.3, label="R5")
    ax.plot(navR5_4c, lw=1.5, label="R5+4c 均线择时")
    ax.plot(nav_bench, lw=1, alpha=0.6, color="gray", label="同池等权基准")
    ax2 = ax.twinx()
    ax2.fill_between(f.index, f.values, alpha=0.15, color="orange")
    ax2.set_ylabel("仓位 f")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)
    ax.set_title("Round 6: R5 vs R5+4c (对数净值, 15bp; 橙色=仓位)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round6.png", dpi=130)
    print("\nCSV: output/factor_round6_summary.csv | 图: output/factor_round6.png")


if __name__ == "__main__":
    main()
