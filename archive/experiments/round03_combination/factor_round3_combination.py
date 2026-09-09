#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 3 组合研究 —— 严格按 docs/factor_round3_combination_plan.md v1.0 实施。

Amihud + 中期动量 等权打分组合（主假设 C） vs 单因子基线（A/B）+ 反转三臂（D）。
四臂共用同一池子 ∩ 因子非 NaN；月度完全等权；15/25/35bp 成本；分年代。
用法: uv run python research/factor_round3_combination.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sps

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import load_all, month_last_days, metrics
from research.reversal_factor import ERAS, N_Q, build_pool, ew_nav

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
MIN_N = 50


# 因子: (计算函数, 方向)。值高→看好 = +1; 值低→看好 = -1
def _amihud(close, ext_amount):
    return (close.pct_change().abs() / ext_amount) * 1e6


def _mom(close, *_):
    return close.shift(21) / close.shift(250) - 1.0


def _rev(close, *_):
    return close / close.shift(21) - 1.0


FACTORS = {"Amihud": (_amihud, +1), "中期动量": (_mom, +1), "反转": (_rev, -1)}


def _pct(vals: pd.Series, direction: int) -> pd.Series:
    """截面百分位 [0,1]，方向调整：+1 保持，-1 用 1-p。"""
    p = vals.rank(pct=True)
    return p if direction == +1 else 1.0 - p


def main() -> None:
    print("== Round 3 组合研究 (预注册 v1.0): Amihud + 中期动量 等权打分 ==")
    close, real, pb, tst, isst, names, div_mat = load_all()
    ret_qfq = close.pct_change()
    pool = build_pool(close, tst, isst)

    # Amihud 需要成交额宽表（round2）
    amt = pd.read_parquet(R2 / "daily_ext.parquet")
    amt["date"] = pd.to_datetime(amt["date"])
    amount = amt.pivot(index="date", columns="code", values="amount").sort_index()
    amount = amount.reindex(index=close.index, columns=close.columns).ffill()

    fv = {
        name: fn(close, amount).rolling(21, min_periods=15).mean()
        if name == "Amihud"
        else fn(close, amount)
        for name, (fn, _) in FACTORS.items()
    }
    fv["Amihud"] = fv["Amihud"]  # 已含 rolling

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]

    # 各臂: {执行日: 成员集合}
    arms = {k: {} for k in ["A", "B", "C", "D"]}
    bench_sets: dict = {}
    ics: dict[str, dict] = {k: {} for k in ["A", "B", "C", "D"]}

    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        # 各因子池内值
        vals = {name: fv[name].loc[T][e].dropna() for name in FACTORS}
        # 公共池（组合用 = 两/三因子非 NaN 交集）
        common2 = vals["Amihud"].index.intersection(vals["中期动量"].index)
        common3 = common2.intersection(vals["反转"].index)
        fwd = (
            close.loc[sig_days[k + 1]] / close.loc[T] - 1.0
            if k + 1 < len(sig_days)
            else None
        )

        # 基准 = 组合公共池等权
        if len(common2) >= MIN_N:
            bench_sets[exec_day] = set(common2)

        def _long_group(score: pd.Series) -> set:
            if len(score) < MIN_N:
                return set()
            q = pd.qcut(score.rank(method="first"), N_Q, labels=False)
            return set(score.index[q == N_Q - 1])

        if len(vals["Amihud"]) >= MIN_N:
            arms["A"][exec_day] = _long_group(vals["Amihud"])
            arms["B"][exec_day] = _long_group(vals["中期动量"])
            if fwd is not None:
                m = vals["Amihud"].index.intersection(fwd.dropna().index)
                if len(m) >= MIN_N:
                    ics["A"][T] = sps.spearmanr(vals["Amihud"][m], fwd[m])[0]
                    ics["B"][T] = sps.spearmanr(vals["中期动量"][m], fwd[m])[0]
        if len(common2) >= MIN_N:
            scoreC = (
                _pct(vals["Amihud"].reindex(common2), +1)
                + _pct(vals["中期动量"].reindex(common2), +1)
            ) / 2
            arms["C"][exec_day] = _long_group(scoreC)
            if fwd is not None:
                m = common2.intersection(fwd.dropna().index)
                if len(m) >= MIN_N:
                    ics["C"][T] = sps.spearmanr(scoreC[m], fwd[m])[0]
        if len(common3) >= MIN_N:
            scoreD = (
                _pct(vals["Amihud"].reindex(common3), +1)
                + _pct(vals["中期动量"].reindex(common3), +1)
                + _pct(vals["反转"].reindex(common3), -1)
            ) / 3
            arms["D"][exec_day] = _long_group(scoreD)
            if fwd is not None:
                m = common3.intersection(fwd.dropna().index)
                if len(m) >= MIN_N:
                    ics["D"][T] = sps.spearmanr(scoreD[m], fwd[m])[0]

    # ---- 回测 ----
    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    names_arm = {
        "A": "Amihud 单因子",
        "B": "中期动量 单因子",
        "C": "Amihud+动量",
        "D": "Amihud+动量+反转",
    }
    print(f"调仓期数 {len(bench_sets)}, 基准(公共池等权) 年化 {ann_bench:+.1%}\n")

    rows, navs = {}, {}
    for k in ["A", "B", "C", "D"]:
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
        ic = pd.Series(ics[k]).dropna()
        ic_mean = ic.mean() if len(ic) else np.nan
        rows[k] = {
            "组合": names_arm[k],
            "年化15bp": round(metrics(long_nav)["年化"], 4),
            "超额15bp": round(metrics(long_nav)["年化"] - ann_bench, 4),
            "超额25bp": round(metrics(long25)["年化"] - ann_bench, 4),
            "超额35bp": round(metrics(long35)["年化"] - ann_bench, 4),
            "年换手": round(turn, 1),
            "夏普": round(metrics(long_nav)["夏普"], 2),
            "回撤": round(metrics(long_nav)["最大回撤"], 3),
            "合成分IC": round(ic_mean, 4) if not np.isnan(ic_mean) else np.nan,
            **{f"超额{era}": round(v, 4) for era, v in era_exc.items()},
        }
        print(
            f"■ {names_arm[k]}: 超额15bp {rows[k]['超额15bp']:+.1%} "
            f"| 25bp {rows[k]['超额25bp']:+.1%} | 35bp {rows[k]['超额35bp']:+.1%} "
            f"| 换手 {turn:.1f} | 夏普 {rows[k]['夏普']:.2f} | 回撤 {rows[k]['回撤']:.1%} "
            f"| IC {ic_mean:+.4f}"
        )
        print(
            "   分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items())
        )

    # 主判定（C 臂）
    A_exc = rows["A"]["超额15bp"]
    C = rows["C"]
    g1 = C["超额15bp"] >= A_exc
    g2 = C["超额35bp"] > 0
    g3 = sum(C[f"超额{era}"] > 0 for era in ERAS) >= 2
    g4 = C["年换手"] <= 6
    n_pass = sum([g1, g2, g3, g4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    gain = C["超额15bp"] - A_exc
    print("\n== 主判定 (C 臂) ==")
    print(
        f"  G1 组合不劣于最优单因子: C{A_exc:+.1%} vs A{A_exc:+.1%} → {g1} "
        f"(增益 {gain:+.1%}{' = 明显增益' if gain >= 0.01 else ''})"
    )
    print(f"  G2 35bp 超额>0: {C['超额35bp']:+.1%} → {g2}")
    print(f"  G3 三段≥2 正: {sum(C[f'超额{era}'] > 0 for era in ERAS)}/3 → {g3}")
    print(f"  G4 年换手≤6: {C['年换手']:.1f} → {g4}")
    print(f"  → C 臂判定: {verdict}({n_pass}/4)")
    # D 臂独立结论
    D_exc, D_turn = rows["D"]["超额15bp"], rows["D"]["年换手"]
    d_verdict = (
        "反转在组合中被救活"
        if D_exc > A_exc and D_turn <= 6
        else "反转仍是负资产/不改善"
    )
    print("\n== D 臂独立结论 ==")
    print(f"  超额 {D_exc:+.1%} (A 基线 {A_exc:+.1%}), 换手 {D_turn:.1f} → {d_verdict}")

    # IC 序列相关（Amihud × 动量）
    ic_a = pd.Series(ics["A"])
    ic_b = pd.Series(ics["B"])
    c_ab = ic_a.corr(ic_b)
    print(f"\nIC 序列相关 Amihud×动量: {c_ab:+.2f} (Round2 读数 −0.42)")

    pd.DataFrame(rows).T.to_csv(OUT / "factor_round3_summary.csv")
    print("\nCSV: output/factor_round3_summary.csv")

    # 图：四臂 + 基准 净值
    fig, ax = plt.subplots(figsize=(11.5, 6))
    for k, lbl in names_arm.items():
        ax.plot(navs[k], lw=1.4, label=lbl)
    ax.plot(nav_bench, lw=1, alpha=0.6, color="gray", label="同池等权基准")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_title("Round 3 组合对照 (对数净值, 15bp)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round3.png", dpi=130)
    print("图: output/factor_round3.png")


if __name__ == "__main__":
    main()
