#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 22 R5 + 价格水平组合验证（预注册）。

臂 A = 现有 R5 (rank(Amihud)+rank(动量))/2; 臂 B = (rank(Amihud)+rank(动量)+rank(价格水平))/3。
全市场池、行业内百分位、前 20% 等权、141 期、300万 share 级全口径。
判定 5 项(B vs A): 超额≥+1pp / 回撤≤+5pp / 换手≤1.5× / 三段全正 / 持仓Jaccard<0.75。

用法: python research/factor_round22_price_combo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days  # noqa: E402
from research.paper_trade import (  # noqa: E402
    MIN_IND,
    MIN_N,
    PaperPortfolio,
    _load,
    _load_corp,
    metrics,
)
from research.paper_trade import build_pool  # noqa: E402
from research.reversal_factor import ERAS, ew_nav  # noqa: E402

COST = 15e-4
AUM = 3_000_000


def r5_rebalances_v2(close, amount, tst, isst, ind, raw, use_price):
    """R5 打分：use_price=True → 三因子 (pa+pm+pp)/3；False → 现有 (pa+pm)/2。"""
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    amihud = ((ret.abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    mom = close.shift(21) / close.shift(250) - 1.0
    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    rebs, bench = [], {}
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        common = a.index.intersection(m.index).intersection(ind.index)
        ind_s = ind.reindex(common)
        keep = ind_s.value_counts()[ind_s.value_counts() >= MIN_IND].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < MIN_N:
            continue
        if k + 1 < len(sig_days):
            bench[exec_day] = set(codes)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        if use_price:
            pp = raw.loc[T].reindex(codes).groupby(ind_s[codes]).rank(pct=True)
            sc = (pa + pm + pp) / 3
        else:
            sc = (pa + pm) / 2
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        rebs.append({"T": T, "exec": exec_day, "target": set(codes[q == 4])})
    return rebs, bench, ret


def run_arm(rebs, raw, F, trad, idx):
    """share 级全口径回放（与 R5 归档同逻辑），返回指标 + 归一化净值序列。"""
    F_prev = F.shift(1).fillna(F.iloc[0])
    pf = PaperPortfolio(AUM)
    rebs_d = {r["exec"]: r for r in rebs}
    navs = []
    buy_total = sell_total = 0.0
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        fn, fp = F.loc[dt], F_prev.loc[dt]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
        rb = rebs_d.get(dt)
        if rb is not None:
            pf.rebalance(rb["target"], prices, trad.loc[dt])
            buy_total += sum(t["amount"] for t in pf.trades if t["side"] == "buy")
            sell_total += sum(t["amount"] for t in pf.trades if t["side"] == "sell")
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / AUM
    m = metrics(nav)
    years = len(nav) / 244
    tot_fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
    turnover = (buy_total + sell_total) / 2 / (nav.mean() * AUM) / years * 100
    return {
        "年化": m["年化"],
        "夏普": m["夏普"],
        "回撤": m["最大回撤"],
        "净值": nav.iloc[-1],
        "费用/年": tot_fee / AUM / years,
        "换手": turnover,
    }, nav


def jaccard_overlap(rebs_a, rebs_b) -> float:
    d = {r["exec"]: r["target"] for r in rebs_a}
    vals = []
    for r in rebs_b:
        if r["exec"] in d:
            A, B = d[r["exec"]], r["target"]
            vals.append(len(A & B) / len(A | B))
    return float(np.mean(vals)) if vals else np.nan


def era_exc(nav: pd.Series, bench_nav: pd.Series) -> dict:
    out = {}
    for era, (s, e_) in ERAS.items():
        a, b = nav[s:e_], bench_nav[s:e_]
        if len(a) < 10 or len(b) < 10:
            continue
        out[era] = (
            metrics(a / a.dropna().iloc[0])["年化"]
            - metrics(b / b.dropna().iloc[0])["年化"]
        )
    return out


def main() -> None:
    print("== Round 22 R5 + 价格水平组合验证 (预注册 v1.0) ==")
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index

    rebs_a, bench, ret = r5_rebalances_v2(
        close, amount, tst, isst, ind, raw, use_price=False
    )
    rebs_b, _, _ = r5_rebalances_v2(close, amount, tst, isst, ind, raw, use_price=True)
    nav_bench, _ = ew_nav(ret, bench, COST)
    ann_bench = metrics(nav_bench)["年化"]
    print(f"调仓期数 {len(bench)}, 同池等权基准年化 {ann_bench:+.1%}")

    ra, nav_a = run_arm(rebs_a, raw, F, trad, idx)
    rb, nav_b = run_arm(rebs_b, raw, F, trad, idx)
    jac = jaccard_overlap(rebs_a, rebs_b)

    print(
        f"\n{'臂':<14}{'超额15bp':<10}{'夏普':<7}{'回撤':<9}{'换手':<8}{'费用/年':<8}{'净值'}"
    )
    for name, r in (("A R5基线", ra), ("B 三因子", rb)):
        exc = r["年化"] - ann_bench
        print(
            f"{name:<14}{exc:+6.2%}   {r['夏普']:5.2f}  {r['回撤']:7.1%}  "
            f"{r['换手']:5.1f}  {r['费用/年']:6.2%}  {r['净值']:5.2f}x"
        )

    exc_a = ra["年化"] - ann_bench
    exc_b = rb["年化"] - ann_bench
    era_a, era_b = era_exc(nav_a, nav_bench), era_exc(nav_b, nav_bench)
    print(f"\n持仓月均 Jaccard 重叠 (B vs A): {jac:.2%}")

    checks = {
        "① 超额 B-A ≥ +1pp": exc_b - exc_a >= 0.01,
        "② 回撤 B-A ≤ +5pp": rb["回撤"] - ra["回撤"] <= 0.05,
        "③ 换手 B/A ≤ 1.5": rb["换手"] / ra["换手"] <= 1.5 if ra["换手"] else False,
        "④ 分段 B 全正": all(v > 0 for v in era_b.values()) if era_b else False,
        "⑤ Jaccard < 0.75": jac < 0.75,
    }
    print("\n判定 (B vs A):")
    for k, v in checks.items():
        print(f"  {'✅' if v else '❌'} {k}")
    n_pass = sum(checks.values())
    print(
        f"\n{n_pass}/5 → {'组合升级候选' if n_pass >= 4 else '维持 R5, 价格水平不并入'}"
    )
    print("\n分段超额 A: " + " ".join(f"{e}:{v:+.1%}" for e, v in era_a.items()))
    print("\n分段超额 B: " + " ".join(f"{e}:{v:+.1%}" for e, v in era_b.items()))
    print(
        f"\n对照 C(价格水平单因子, Round21): +3.0pp@15bp | A(现有R5): {exc_a:+.1%} | B(三因子): {exc_b:+.1%}"
    )


if __name__ == "__main__":
    main()
