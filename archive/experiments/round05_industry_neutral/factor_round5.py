#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 5 行业中性化 —— 严格按 docs/factor_round5_industry_neutral_plan.md v1.0 实施。

C_base（全局排名） vs R5（行业内排名），同一中性化池/基准/成本，仅"排名基准"不同。
判定看 R5 的 N1~N4。
用法: uv run python research/factor_round5.py
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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
MIN_N = 50
MIN_IND = 5  # 行业内至少 5 只有效才保留该行业


def _pct(vals: pd.Series) -> pd.Series:
    return vals.rank(pct=True)


def main() -> None:
    print("== Round 5 行业中性化 (预注册 v1.0): C_base(全局) vs R5(行业内) ==")
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
    arms = {"C_base": {}, "R5": {}}
    bench_sets: dict = {}
    coverage = []

    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        common = a.index.intersection(m.index)
        # 行业过滤: 行业 ≥ MIN_IND 只有效
        ind_series = ind.reindex(common)
        ind_cnt = ind_series.value_counts()
        keep_ind = ind_cnt[ind_cnt >= MIN_IND].index
        codes = common[ind_series.isin(keep_ind)]
        if len(codes) < MIN_N:
            continue
        if k + 1 < len(sig_days):
            bench_sets[exec_day] = set(codes)
        coverage.append(len(codes))
        ind_codes = ind_series[codes]

        # C_base: 全局百分位
        sc_base = (_pct(a.reindex(codes)) + _pct(m.reindex(codes))) / 2
        q = pd.qcut(sc_base.rank(method="first"), 5, labels=False)
        arms["C_base"][exec_day] = set(codes[q == 4])

        # R5: 行业内百分位
        pa = a.reindex(codes).groupby(ind_codes).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_codes).rank(pct=True)
        sc_r5 = (pa + pm) / 2
        q5 = pd.qcut(sc_r5.rank(method="first"), 5, labels=False)
        arms["R5"][exec_day] = set(codes[q5 == 4])

    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    print(
        f"调仓期数 {len(bench_sets)}, 中性化池月均 {np.mean(coverage):.0f} 只, "
        f"基准年化 {ann_bench:+.1%}"
    )

    rows, navs = {}, {}
    for k in ["C_base", "R5"]:
        long_nav, turn = ew_nav(ret_qfq, arms[k], COST)
        navs[k] = long_nav
        long25, _ = ew_nav(ret_qfq, arms[k], COST_SWEEP[0])
        long35, _ = ew_nav(ret_qfq, arms[k], COST_SWEEP[1])
        era_exc = {}
        for era, (s, e_) in ERAS.items():
            a, b = long_nav[s:e_], nav_bench[s:e_]
            era_exc[era] = (
                metrics(a / a.dropna().iloc[0])["年化"]
                - metrics(b / b.dropna().iloc[0])["年化"]
            )
        rows[k] = {
            "臂": k,
            "超额15bp": round(metrics(long_nav)["年化"] - ann_bench, 4),
            "超额25bp": round(metrics(long25)["年化"] - ann_bench, 4),
            "超额35bp": round(metrics(long35)["年化"] - ann_bench, 4),
            "年换手": round(turn, 1),
            "夏普": round(metrics(long_nav)["夏普"], 2),
            "最大回撤": round(metrics(long_nav)["最大回撤"], 3),
            **{f"超额{era}": round(v, 4) for era, v in era_exc.items()},
        }
        print(
            f"\n■ {k}: 超额15bp {rows[k]['超额15bp']:+.1%} | 35bp {rows[k]['超额35bp']:+.1%} "
            f"| 换手 {turn:.1f} | 夏普 {rows[k]['夏普']:.2f} | 回撤 {rows[k]['最大回撤']:.1%}"
        )
        print(
            "   分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items())
        )

    Cb, R = rows["C_base"], rows["R5"]
    ind_beta = Cb["超额15bp"] - R["超额15bp"]
    n1 = R["超额15bp"] >= 0.04
    n2 = R["超额35bp"] > 0
    n3 = sum(R[f"超额{era}"] > 0 for era in ERAS) >= 2
    n4 = ind_beta < 0.04
    n_pass = sum([n1, n2, n3, n4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    print("\n== 判定 (R5 vs C_base) ==")
    print(
        f"  N1 超额≥+4pp: C_base {Cb['超额15bp']:+.1%} → R5 {R['超额15bp']:+.1%} → {n1}"
    )
    print(f"  N2 35bp 超额>0: {R['超额35bp']:+.1%} → {n2}")
    print(f"  N3 三段≥2 正: {sum(R[f'超额{era}'] > 0 for era in ERAS)}/3 → {n3}")
    print(f"  N4 行业beta贡献<4pp: {ind_beta:+.1%} → {n4}")
    print(f"  → R5 判定: {verdict}({n_pass}/4)")
    if n4 and not n1:
        print(
            "  结论: 行业内 alpha 弱 → Amihud 流动性溢价主要是'跨行业'的，"
            "中性化后的诚实 alpha 很弱"
        )
    elif n1 and n4:
        print("  结论: 行业内 alpha 真实存在 → 中性化是免费去风险升级，采纳 R5")

    pd.DataFrame(rows).T.to_csv(OUT / "factor_round5_summary.csv")
    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(navs["C_base"], lw=1.3, label="C_base (全局排名)")
    ax.plot(navs["R5"], lw=1.5, label="R5 (行业内排名)")
    ax.plot(nav_bench, lw=1, alpha=0.6, color="gray", label="中性化池等权基准")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_title("Round 5 行业中性化 (对数净值, 15bp)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round5.png", dpi=130)
    print("\nCSV: output/factor_round5_summary.csv | 图: output/factor_round5.png")


if __name__ == "__main__":
    main()
