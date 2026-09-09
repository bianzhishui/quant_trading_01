#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 4 风险加固 —— 严格按 docs/factor_round4_plan.md v1.0 实施。

单一改动：多头组从合成分百分位 (0.80, 1.0] 收窄到 (0.80, 0.95]。
对照 C 基线（Round 3 复现），其余口径完全一致。判定看 R4a 的 H1~H4。
用法: uv run python research/factor_round4.py
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


def _pct(vals: pd.Series) -> pd.Series:
    return vals.rank(pct=True)


def max_dd_episode(nav: pd.Series) -> tuple[str, str, float]:
    """返回 (回撤起始, 回撤触底) 日期与最大回撤幅度。"""
    cummax = nav.cummax()
    dd = nav / cummax - 1
    trough_i = dd.idxmin()
    peak_i = nav[:trough_i].idxmax()
    return str(peak_i.date()), str(trough_i.date()), float(dd.min())


def main() -> None:
    print("== Round 4 风险加固 (预注册 v1.0): Amihud 极端档剔除 ==")
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

    arms = {"C": {}, "R4a": {}}
    bench_sets: dict = {}
    sizes = {"C": [], "R4a": []}

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
        p_am, p_mom = _pct(a.reindex(common)), _pct(m.reindex(common))
        score = (p_am + p_mom) / 2

        q_c = pd.qcut(score.rank(method="first"), 5, labels=False)
        arms["C"][exec_day] = set(score.index[q_c == 4])
        sizes["C"].append(int((q_c == 4).sum()))

        pctv = score.rank(pct=True)
        arms["R4a"][exec_day] = set(score.index[(pctv > 0.80) & (pctv <= 0.95)])
        sizes["R4a"].append(int(((pctv > 0.80) & (pctv <= 0.95)).sum()))

    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    print(f"调仓期数 {len(bench_sets)}, 基准(公共池等权) 年化 {ann_bench:+.1%}")
    for k in ["C", "R4a"]:
        print(
            f"  平均持股数 {k}: {np.mean(sizes[k]):.0f} 只 (中位 {int(np.median(sizes[k]))})"
        )

    rows, navs = {}, {}
    for k in ["C", "R4a"]:
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
        pk, tr, mdd = max_dd_episode(long_nav)
        rows[k] = {
            "臂": k,
            "超额15bp": round(metrics(long_nav)["年化"] - ann_bench, 4),
            "超额25bp": round(metrics(long25)["年化"] - ann_bench, 4),
            "超额35bp": round(metrics(long35)["年化"] - ann_bench, 4),
            "年换手": round(turn, 1),
            "夏普": round(metrics(long_nav)["夏普"], 2),
            "最大回撤": round(mdd, 3),
            "回撤区间": f"{pk}~{tr}",
            "平均持股": round(np.mean(sizes[k]), 0),
            **{f"超额{era}": round(v, 4) for era, v in era_exc.items()},
        }
        print(
            f"\n■ {k}: 超额15bp {rows[k]['超额15bp']:+.1%} | 35bp {rows[k]['超额35bp']:+.1%} "
            f"| 换手 {turn:.1f} | 夏普 {rows[k]['夏普']:.2f} "
            f"| 最大回撤 {mdd:.1%} ({pk}~{tr}) | 持股 {rows[k]['平均持股']:.0f}"
        )
        print(
            "   分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items())
        )

    C, R = rows["C"], rows["R4a"]
    h1 = R["最大回撤"] < C["最大回撤"] - 0.03
    h2 = R["超额15bp"] >= C["超额15bp"] - 0.015
    h3 = R["超额35bp"] > 0
    h4 = sum(R[f"超额{era}"] > 0 for era in ERAS) >= 2
    n_pass = sum([h1, h2, h3, h4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    print("\n== 判定 (R4a vs C) ==")
    print(
        f"  H1 回撤改善≥3pp: C {C['最大回撤']:.1%} → R4a {R['最大回撤']:.1%} "
        f"(改善 {C['最大回撤'] - R['最大回撤']:+.1%}) → {h1}"
    )
    print(
        f"  H2 超额损失≤1.5pp: C {C['超额15bp']:+.1%} → R4a {R['超额15bp']:+.1%} "
        f"(Δ {R['超额15bp'] - C['超额15bp']:+.1%}) → {h2}"
    )
    print(f"  H3 35bp 超额>0: {R['超额35bp']:+.1%} → {h3}")
    print(f"  H4 三段≥2 正: {sum(R[f'超额{era}'] > 0 for era in ERAS)}/3 → {h4}")
    print(f"  → R4a 判定: {verdict}({n_pass}/4)")
    if h1:
        print("  结论: 极端档是回撤来源，剔除有效 → R4a 采纳为策略主体")
    else:
        print(
            "  结论: 回撤主要是市场/风格级，尾部剔除无效 → 下一步 Round 4b 转向回撤熔断/仓位管理"
        )

    pd.DataFrame(rows).T.to_csv(OUT / "factor_round4_summary.csv")
    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(navs["C"], lw=1.4, label="C 基线 (前20%)")
    ax.plot(navs["R4a"], lw=1.4, label="R4a (剔除最极端5%)")
    ax.plot(nav_bench, lw=1, alpha=0.6, color="gray", label="同池等权基准")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_title("Round 4 风险加固: Amihud 极端档剔除 (对数净值, 15bp)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round4.png", dpi=130)
    print("\nCSV: output/factor_round4_summary.csv | 图: output/factor_round4.png")


if __name__ == "__main__":
    main()
