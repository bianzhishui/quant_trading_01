#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 4b 风险加固·风控层 —— 严格按 docs/factor_round4b_drawdown_breaker_plan.md v1.0 实施。

C 基线持仓 + 回撤熔断状态机（满仓/半仓/空仓，含迟滞），风控层唯一改动。
触发信号 = C 基线净值峰值回撤；降仓/回补按 15bp 计成本；现金收益 0（保守）。
用法: uv run python research/factor_round4b.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import load_all, month_last_days, metrics
from research.reversal_factor import ERAS, build_pool

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
MIN_N = 50

# 熔断状态机阈值（预注册）
CUT_1, REST_1 = -0.20, -0.15  # 满仓<->半仓
CUT_2, REST_2 = -0.30, -0.20  # 半仓<->空仓


def _pct(vals: pd.Series) -> pd.Series:
    return vals.rank(pct=True)


def build_weight_matrix(ret: pd.DataFrame, sets: dict) -> pd.DataFrame:
    """sets → 日频权重矩阵（执行日生效，与 ew_nav 同口径）。"""
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
    """按 f 缩放权重后回测（含缩放本身引起的换手成本）。"""
    scaled = W.multiply(f, axis=0)
    turn = scaled.diff().abs().sum(axis=1).fillna(0.0)
    gross = (scaled.shift(1).fillna(0.0) * ret.fillna(0.0)).sum(axis=1)
    return (1 + gross - turn * cost).cumprod()


def breaker_factor(dd: pd.Series) -> pd.Series:
    """dd(峰值回撤序列) → f 状态机（含迟滞）。返回 (f, 触发记录)。"""
    f = pd.Series(1.0, index=dd.index)
    state = 1.0
    triggers = []
    for t in dd.index:
        d = dd.loc[t]
        if state == 1.0 and d < CUT_1:
            state = 0.5
            triggers.append((t, "1→0.5"))
        elif state == 0.5:
            if d < CUT_2:
                state = 0.0
                triggers.append((t, "0.5→0"))
            elif d > REST_1:
                state = 1.0
                triggers.append((t, "0.5→1"))
        elif state == 0.0 and d > REST_2:
            state = 0.5
            triggers.append((t, "0→0.5"))
        f.loc[t] = state
    return f, triggers


def max_dd_episode(nav: pd.Series) -> tuple[str, str, float]:
    cummax = nav.cummax()
    dd = nav / cummax - 1
    trough_i = dd.idxmin()
    peak_i = nav[:trough_i].idxmax()
    return str(peak_i.date()), str(trough_i.date()), float(dd.min())


def main() -> None:
    print("== Round 4b 回撤熔断 (预注册 v1.0): C 持仓 + 风控层状态机 ==")
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
    nav_bench, _ = _bench(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]

    # C 基线满仓净值（保护前，用于触发信号 + 对照）
    navC = (
        1
        + (W.shift(1).fillna(0.0) * ret_qfq.fillna(0.0)).sum(axis=1)
        - W.diff().abs().fillna(0.0).sum(axis=1) * COST
    ).cumprod()
    # 触发信号：C 净值峰值回撤
    dd_sig = navC / navC.cummax() - 1.0
    f, triggers = breaker_factor(dd_sig)

    navR4b = scaled_nav(ret_qfq, W, f, COST)
    # 35bp 压测：换手成本变，但 f/触发不变（触发只看 C 满仓净值）
    navR4b35 = scaled_nav(ret_qfq, W, f, COST_SWEEP[1])

    print(f"调仓期数 {len(bench_sets)}, 基准(公共池等权) 年化 {ann_bench:+.1%}")
    print(
        f"熔断触发次数: {len(triggers)} → {triggers if len(triggers) <= 8 else triggers[:4] + ['...']}"
    )
    print(
        f"熔断期间(净值日)占比: {(f < 1.0).mean():.1%} (满仓 {(f == 1.0).mean():.1%}, "
        f"半仓 {(f == 0.5).mean():.1%}, 空仓 {(f == 0.0).mean():.1%})"
    )

    rows, navs = {}, {}
    for k, nav in [("C", navC), ("R4b", navR4b)]:
        pk, tr, mdd = max_dd_episode(nav)
        era_exc = {}
        for era, (s, e_) in ERAS.items():
            a, b = nav[s:e_], nav_bench[s:e_]
            era_exc[era] = (
                metrics(a / a.dropna().iloc[0])["年化"]
                - metrics(b / b.dropna().iloc[0])["年化"]
            )
        # 换手（含熔断缩放）
        scaled = W.multiply(f if k == "R4b" else 1.0, axis=0)
        turn = float(scaled.diff().abs().sum(axis=1).sum() / 2 / (len(nav) / 244))
        # 35bp 超额（R4b 用 35bp 成本重算净值；C 用自身 15bp 净值近似——C 换手低，
        # 但为一致起见此处 C 也补算 35bp）
        nav35 = scaled_nav(ret_qfq, W, f if k == "R4b" else 1.0, COST_SWEEP[1])
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

    C, R = rows["C"], rows["R4b"]
    k1 = R["最大回撤"] >= -0.30
    k2 = R["超额15bp"] >= 0.05
    k3 = metrics(navR4b35)["年化"] - ann_bench > 0
    k4 = sum(R[f"超额{era}"] > 0 for era in ERAS) >= 2
    n_pass = sum([k1, k2, k3, k4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    print("\n== 判定 (R4b vs C) ==")
    print(f"  K1 最大回撤≥-30%: C {C['最大回撤']:.1%} → R4b {R['最大回撤']:.1%} → {k1}")
    print(f"  K2 超额≥+5pp: R4b {R['超额15bp']:+.1%} → {k2}")
    print(f"  K3 35bp 超额>0: R4b {metrics(navR4b35)['年化'] - ann_bench:+.1%} → {k3}")
    print(f"  K4 三段≥2 正: {sum(R[f'超额{era}'] > 0 for era in ERAS)}/3 → {k4}")
    print(f"  → R4b 判定: {verdict}({n_pass}/4)")

    pd.DataFrame(rows).T.to_csv(OUT / "factor_round4b_summary.csv")
    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(navs["C"], lw=1.3, label="C 满仓")
    ax.plot(navs["R4b"], lw=1.5, label="R4b C+熔断")
    ax.plot(nav_bench, lw=1, alpha=0.6, color="gray", label="同池等权基准")
    ax.plot(f.index, f * 0.0 + 0.98, lw=0)  # noop
    ax2 = ax.twinx()
    ax2.fill_between(f.index, f.values, alpha=0.15, color="orange")
    ax2.set_ylabel("仓位 f")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)
    ax.set_title("Round 4b 回撤熔断 (对数净值, 15bp; 橙色=仓位)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round4b.png", dpi=130)
    print("\nCSV: output/factor_round4b_summary.csv | 图: output/factor_round4b.png")


def _bench(ret: pd.DataFrame, sets: dict, cost: float):
    from research.reversal_factor import ew_nav

    return ew_nav(ret, sets, cost)


if __name__ == "__main__":
    main()
