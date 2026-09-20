#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 39 "同向但异法"候选因子单因子月频筛选 —— 严格按
docs/factor_round39_candidates_plan.md v1.0 实施（P1）。

候选: C1低换手21 / C2换手波动21std / C3市值代理(对照) / C4短动量5-21(方向对照)
P1 判定(R36框架 4项): ①IC|t|≥2 ②五组单调 ③Q1超额15bp≥3pp ④三段≥2段正
P2 组合验证: 通过者以10%权重并入 w* 打分, share级 R37协议5项。

用法: uv run python research/factor_round39_candidates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.config import get_config  # noqa: E402
from research.data_io import load_full_daily  # noqa: E402
from research.dividend_factor import metrics, month_last_days  # noqa: E402
from research.reversal_factor import build_pool, ew_nav  # noqa: E402

COST = 15e-4


def _cfg():
    return get_config()


def load_panels():
    cfg = _cfg()
    close, amount, tst, isst, ind = (None,) * 5  # 占位, 用 paper_trade._load
    from research.paper_trade import _load

    close, amount, tst, isst, ind = _load()
    d = load_full_daily()
    d["date"] = pd.to_datetime(d["date"])

    def piv(col):
        return (
            d.pivot(index="date", columns="code", values=col)
            .sort_index()
            .loc[cfg.strategy.start :]
        )

    turn = piv("turn")
    return close, amount, tst, isst, ind, turn


def factor_panels(close, amount, turn):
    return {
        "C1低换手21": turn.rolling(21).mean(),
        "C2换手波动21std": turn.rolling(21).std(),
        "C3市值代理": (amount / turn).replace([np.inf, -np.inf], np.nan),
        "C4短动量5/21": close.shift(5) / close.shift(21) - 1.0,
    }


def wstar_rebs(close, amount, tst, isst, ind, sig_days, idx):
    """生产 w* 组合(0.40A+0.10M+0.50F4) 的 {exec: target}。"""
    cfg = _cfg()
    r5 = cfg.strategy.r5
    min_ind, min_n = cfg.strategy.min_ind, cfg.strategy.min_n
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    amihud = ((ret.abs() / amount) * r5.amihud_scale).rolling(21, min_periods=15).mean()
    mom = close.shift(21) / close.shift(250) - 1.0
    f4 = amount.rolling(5).mean()
    q1 = {}
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        f = f4.loc[T][e].dropna()
        common = (
            a.index.intersection(m.index).intersection(f.index).intersection(ind.index)
        )
        ind_s = ind.reindex(common)
        keep = ind_s.value_counts()[ind_s.value_counts() >= min_ind].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < min_n:
            continue
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pf4 = -f.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = 0.40 * pa + 0.10 * pm + 0.50 * pf4
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        q1[exec_day] = set(codes[q == 4])
    return q1


def jacc(a, b):
    vals = []
    for k in a:
        if k in b:
            A, B = a[k], b[k]
            if A or B:
                vals.append(len(A & B) / len(A | B))
    return float(np.mean(vals)) if vals else np.nan


def screen_factor(fac, direction, close, amount, tst, isst, ind, sig_days, idx, ret):
    """单因子月频筛选。返回指标 dict。"""
    cfg = _cfg()
    n_q = cfg.strategy.n_q
    cost_sweep = cfg.costs.cost_sweep
    eras = cfg.strategy.eras.to_dict()
    pool = build_pool(close, tst, isst)
    q_sets = [dict() for _ in range(n_q)]
    bench, ics = {}, {}
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        f = fac.loc[T][e].dropna()
        if len(f) < 50:
            continue
        exec_day = idx[idx.get_loc(T) + 1]
        rk = f.rank(method="first")
        if direction == "high":
            rk = -rk  # 方向端归一: 高→买 取最高组为 Q1
        q = pd.qcut(rk, n_q, labels=False)
        for g in range(n_q):
            q_sets[g][exec_day] = set(f.index[q == g])
        bench[exec_day] = set(f.index)
        T2 = sig_days[k + 1] if k + 1 < len(sig_days) else None
        if T2 is not None:
            fwd = close.loc[T2] / close.loc[T] - 1.0
            m2 = f.index.intersection(fwd.dropna().index)
            if len(m2) >= 50:
                ics[T] = sps.spearmanr(f[m2], fwd[m2])[0]
    ic = pd.Series(ics)
    ic_mean = ic.mean()
    ic_t = ic_mean / ic.std(ddof=0) * np.sqrt(len(ic)) if ic.std() > 0 else np.nan

    navs, turns = {}, {}
    for g in range(n_q):
        navs[f"Q{g + 1}"], turns[f"Q{g + 1}"] = ew_nav(ret, q_sets[g], COST)
    navs["基准"], _ = ew_nav(ret, bench, COST)
    anns = {k: metrics(v)["年化"] for k, v in navs.items()}
    q1_35, _ = ew_nav(ret, q_sets[0], cost_sweep[1])
    excess15 = anns["Q1"] - anns["基准"]
    excess35 = metrics(q1_35)["年化"] - anns["基准"]
    group_ann = [anns[f"Q{g + 1}"] for g in range(n_q)]
    mono = sps.spearmanr(range(1, n_q + 1), group_ann)[0]
    era = {}
    for name, (s, e) in eras.items():
        a = navs["Q1"][s:e]
        b = navs["基准"][s:e]
        if len(a) < 10 or len(b) < 10:
            continue
        era[name] = (
            metrics(a / a.dropna().iloc[0])["年化"]
            - metrics(b / b.dropna().iloc[0])["年化"]
        )
    # Jaccard vs w*
    wstar = wstar_rebs(close, amount, tst, isst, ind, sig_days, idx)
    jac = jacc(q_sets[0], wstar)
    return {
        "IC均值": ic_mean,
        "t": ic_t,
        "Q1超额15": excess15,
        "Q1超额35": excess35,
        "组序ρ": mono,
        "三段": era,
        "Jaccard_vs_w*": jac,
        "换手": turns["Q1"],
        "Q1年化": anns["Q1"],
        "基准年化": anns["基准"],
    }


def main() -> None:
    print("== Round 39 同向但异法候选因子 P1 单因子月频筛 (预注册 v1.0) ==")
    close, amount, tst, isst, ind, turn = load_panels()
    ret = close.pct_change()
    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    print(
        f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, 信号日 {len(sig_days)} 期"
    )

    factors = factor_panels(close, amount, turn)
    directions = {
        "C1低换手21": "low",
        "C2换手波动21std": "low",
        "C3市值代理": "low",
        "C4短动量5/21": "high",
    }
    rows = []
    for name, fac in factors.items():
        r = screen_factor(
            fac, directions[name], close, amount, tst, isst, ind, sig_days, idx, ret
        )
        c1 = abs(r["t"]) >= 2.0
        c2 = (r["Q1年化"] == max([r["Q1年化"]])) or True  # 单调由组序ρ判
        c2 = abs(r["组序ρ"]) >= 0.7
        c3 = r["Q1超额15"] >= 0.03
        c4 = sum(v > 0 for v in r["三段"].values()) >= 2
        n_pass = sum([c1, c2, c3, c4])
        verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
        rows.append({**{"因子": name, "判定": verdict, "n_pass": n_pass}, **r})
        print(
            f"\n[{name}] ({directions[name]}) IC={r['IC均值']:+.4f} t={r['t']:+.2f} | "
            f"Q1 {r['Q1年化']:+.1%} / 基准 {r['基准年化']:+.1%} | 超额15 {r['Q1超额15']:+.1%} "
            f"35 {r['Q1超额35']:+.1%} | 换手 {r['换手']:.1f} | 组序ρ {r['组序ρ']:+.2f} | "
            f"Jaccard {r['Jaccard_vs_w*']:.1%} | 三段 {[f'{v:+.1%}' for v in r['三段'].values()]}"
            f" | {verdict}({n_pass}/4)"
        )
    out = Path(_cfg().paths.output)
    out.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "round39_candidates_summary.csv", index=False)
    print(f"\nCSV: {out}/round39_candidates_summary.csv")


if __name__ == "__main__":
    main()
