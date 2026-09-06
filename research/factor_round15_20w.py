#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 15 20万 极限小资金: 现状(575等权) vs 前N+满仓补买 (N∈{100,150,200}).

share 级全口径成本, 基准同池等权 15bp。诚实报告绝对收益规模。
用法: python research/factor_round15_20w.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import PaperPortfolio, _load, _load_corp, metrics, r5_rebalances
from research.factor_round12_concentrated import r5_topN_rebalances
from research.factor_round13_concentrated_fill import rebalance_fill
from research.reversal_factor import ew_nav


def run(aum, rebs, raw, F, trad, idx, fill=True):
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
            if fill:
                rebalance_fill(pf, rb["target"], prices, trad.loc[dt])
            else:
                pf.rebalance(rb["target"], prices, trad.loc[dt])
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / aum
    m = metrics(nav)
    years = len(nav) / 244
    tot_fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
    last = rebs[-1]
    prices_l = raw.loc[last["exec"]]
    pf0 = PaperPortfolio(aum)
    if fill:
        rebalance_fill(pf0, last["target"], prices_l, trad.loc[last["exec"]])
    else:
        pf0.rebalance(last["target"], prices_l, trad.loc[last["exec"]])
    mv = sum(s * prices_l.get(c, np.nan) for c, s in pf0.shares.items() if pd.notna(prices_l.get(c, np.nan)))
    return {"持有": len(pf0.shares), "目标": len(last["target"]), "使用率": mv / aum,
            "年化": m["年化"], "夏普": m["夏普"], "回撤": m["最大回撤"],
            "净值": nav.iloc[-1], "费用": tot_fee / aum / years,
            "分红": pf.div_cash, "订单": len(pf.trades)}


def main():
    AUM = 200_000
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs0, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    years = len(idx) / 244

    print(f"== Round 15 20万 极限小资金 ==  基准年化 {ann_bench:.1%}")
    rows = [("20万 现状(575等权)", run(AUM, rebs0, raw, F, trad, idx, fill=False))]
    for N in (100, 150, 200):
        rebs = r5_topN_rebalances(close, amount, tst, isst, ind, N)
        rows.append((f"20万 前{N}+补买", run(AUM, rebs, raw, F, trad, idx, fill=True)))

    print(f"\n{'口径':<16}{'持/目':<8}{'使用率':<7}{'年化':<8}{'超额':<8}{'夏普':<6}"
          f"{'回撤':<8}{'费用/年':<8}{'净值':<6}{'订单'}")
    for name, r in rows:
        exc = r["年化"] - ann_bench
        print(f"{name:<16}{r['持有']}/{r['目标']:<5}{r['使用率']:.0%}  "
              f"{r['年化']:6.1%}  {exc:+6.2%}  {r['夏普']:5.2f}  {r['回撤']:7.1%}  "
              f"{r['费用']:6.2%}  {r['净值']:5.2f}x  {r['订单']}")
    print("\n对照(60万定稿): 前100+补买 +3.59pp/1.65%费/90%用 | 300万满配 +4.43pp")
    print("\n判定(超额≥+2.5pp 且 使用率≥80% 且 费用≤3.0%):")
    for name, r in rows[1:]:
        exc = r["年化"] - ann_bench
        ok = exc >= 0.025 and r["使用率"] >= 0.80 and r["费用"] <= 0.03
        # 绝对收益规模
        profit_yr = (r["净值"] ** (1 / years) - 1) * AUM
        print(f"  {name}: 超额{exc:+.2%} 使用率{r['使用率']:.0%} 费用{r['费用']:.2%} "
              f"→ {'✅通过' if ok else '未达标'} | 年化绝对利润 ~{profit_yr/1e4:.1f}万/年")
    print(f"\n参考: 20万本金 {years:.1f}年, 即使最优档, 绝对利润量级={rows[1][1]['净值']**(1/years)*0}\n")


if __name__ == "__main__":
    main()
