#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 14 60万 集中版·行业中性化对照: 全局前N vs 行业内取顶再全局裁剪.

均用满仓补买分配(rebalance_fill)。新增行业集中度指标(建仓快照最大行业权重/前5行业)。
N ∈ {100,150}, 60万, 全口径成本。

用法: python research/factor_round14_concentrated_industry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import (
    PaperPortfolio,
    _load,
    _load_corp,
    build_pool,
    metrics,
    month_last_days,
    r5_rebalances,
)
from research.paper_trade import MIN_IND, MIN_N
from factor_round13_concentrated_fill import rebalance_fill
from research.reversal_factor import ew_nav


def _sc_panel(close, amount, tst, isst, ind, N, industry_neutral):
    """返回 rebs: 全局前N 或 行业中性前N。"""
    pool = build_pool(close, tst, isst)
    amihud = (
        ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    )
    mom = close.shift(21) / close.shift(250) - 1.0
    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    rebs = []
    for T in sig_days:
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
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = (pa + pm) / 2
        if not industry_neutral:
            target = set(sc.nlargest(min(N, len(sc))).index)
        else:
            n_ind = ind_s[codes].nunique()
            M = max(1, int(round(N / n_ind)))
            within = sc.groupby(ind_s[codes]).rank(ascending=False)
            cand = codes[within <= M]
            target = (
                set(sc.loc[cand].nlargest(min(N, len(cand))).index)
                if len(cand) >= N
                else set(sc.nlargest(N).index)
            )
        rebs.append({"T": T, "exec": exec_day, "target": target})
    return rebs


def run(aum, rebs, raw, F, trad, idx, ind):
    F_prev = F.shift(1).fillna(F.iloc[0])
    pf = PaperPortfolio(aum)
    rebs_d = {r["exec"]: r for r in rebs}
    navs = []
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        fn, fp = F.loc[dt], F_prev.loc[dt]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
        rb = rebs_d.get(dt)
        if rb is not None:
            rebalance_fill(pf, rb["target"], prices, trad.loc[dt])
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / aum
    m = metrics(nav)
    years = len(nav) / 244
    tot_fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
    # 建仓快照: 使用率 + 行业集中度
    last = rebs[-1]
    prices_l = raw.loc[last["exec"]]
    pf0 = PaperPortfolio(aum)
    rebalance_fill(pf0, last["target"], prices_l, trad.loc[last["exec"]])
    mvs = {
        c: s * prices_l.get(c, np.nan)
        for c, s in pf0.shares.items()
        if pd.notna(prices_l.get(c, np.nan))
    }
    mv_tot = sum(mvs.values())
    w = pd.Series(mvs) / mv_tot
    ind_w = w.groupby(ind.reindex(w.index)).sum().sort_values(ascending=False)
    return {
        "持有": len(pf0.shares),
        "目标": len(last["target"]),
        "使用率": mv_tot / aum,
        "年化": m["年化"],
        "夏普": m["夏普"],
        "回撤": m["最大回撤"],
        "净值": nav.iloc[-1],
        "费用": tot_fee / aum / years,
        "订单": len(pf.trades),
        "最大行业权重": ind_w.iloc[0] if len(ind_w) else np.nan,
        "前5行业权重": ind_w.head(5).sum() if len(ind_w) else np.nan,
    }


def main():
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs0, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index

    print(f"== Round 14 60万 集中版·行业中性化对照 ==  基准年化 {ann_bench:.1%}")
    rows = []
    for N in (100, 150):
        for label, neut in (("全局", False), ("行业中性", True)):
            rebs = _sc_panel(close, amount, tst, isst, ind, N, neut)
            rows.append((f"前{N}·{label}", run(600_000, rebs, raw, F, trad, idx, ind)))

    print(
        f"\n{'口径':<12}{'持/目':<8}{'使用率':<7}{'超额':<8}{'夏普':<6}{'回撤':<8}"
        f"{'费用':<7}{'净值':<6}{'最大行业':<8}{'前5行业'}"
    )
    for name, r in rows:
        exc = r["年化"] - ann_bench
        print(
            f"{name:<12}{r['持有']}/{r['目标']:<5}{r['使用率']:.0%}  {exc:+6.2%}  "
            f"{r['夏普']:5.2f}  {r['回撤']:7.1%}  {r['费用']:6.2%}  {r['净值']:5.2f}x  "
            f"{r['最大行业权重']:.0%}    {r['前5行业权重']:.0%}"
        )
    print("\n判定(行业中性版超额 ≥ 全局×80% 且 最大行业<20% 且 使用率≥85%):")
    for N in (100, 150):
        g = next(r for n, r in rows if n == f"前{N}·全局")
        i = next(r for n, r in rows if n == f"前{N}·行业中性")
        ge, ie = g["年化"] - ann_bench, i["年化"] - ann_bench
        ok = ie >= ge * 0.8 and i["最大行业权重"] < 0.20 and i["使用率"] >= 0.85
        print(
            f"  前{N}: 全局{ge:+.2%} vs 行业中性{ie:+.2%} (保持{ie / ge:.0%}) "
            f"最大行业{i['最大行业权重']:.0%} 使用率{i['使用率']:.0%} "
            f"→ {'✅稳健' if ok else '超额缩水/集中未降'}"
        )


if __name__ == "__main__":
    main()
