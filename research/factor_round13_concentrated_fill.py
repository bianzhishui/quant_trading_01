#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 13 60万 集中版·满仓补买: 前 N 只等权 + 预算在可买子集内迭代再分配.

预算迭代: budget = V / n_buyable(1手价≤budget 且可交易), 收敛后等权可买子集,
闲置现金全部补进可买股 → 使用率推到 90%+。N ∈ {100,120,150}, 60万, 全口径成本。

用法: python research/factor_round13_concentrated_fill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import PaperPortfolio, _load, _load_corp, metrics, r5_rebalances
from research.factor_round12_concentrated import r5_topN_rebalances
from research.reversal_factor import ew_nav


def rebalance_fill(pf: PaperPortfolio, target: set, prices: pd.Series, tradable: pd.Series):
    """等权 top-N, 预算在可买子集内迭代再分配(满仓补买)。"""
    V = pf.value(prices)
    n = len(target)
    if n == 0:
        return
    budget = V / n
    for _ in range(10):
        n_b = sum(1 for c in target
                  if pd.notna(prices.get(c, np.nan)) and tradable.get(c, False)
                  and prices[c] * 100 <= budget)
        if n_b == 0:
            break
        nb2 = V / n_b
        if abs(nb2 - budget) <= budget * 0.005:
            budget = nb2
            break
        budget = nb2
    # 卖出: 退出 + 超出目标(≥1手)
    for c in list(pf.shares.keys()):
        if c not in target:
            if tradable.get(c, False):
                pf._order(c, "sell", pf.shares[c], prices.get(c, np.nan))
        else:
            p = prices.get(c, np.nan)
            if pd.isna(p) or not tradable.get(c, False):
                continue
            tgt_sh = int(budget / p / 100) * 100
            if pf.shares[c] - tgt_sh >= 100:
                pf._order(c, "sell", pf.shares[c] - tgt_sh, p)
    # 买入: 先买贵的(避免现金被便宜股占满)
    for c in sorted(target, key=lambda x: prices.get(x, np.inf), reverse=True):
        p = prices.get(c, np.nan)
        if pd.isna(p) or not tradable.get(c, False):
            continue
        tgt_sh = int(budget / p / 100) * 100
        held = pf.shares.get(c, 0)
        if tgt_sh - held >= 100:
            need = (tgt_sh - held) * p + max((tgt_sh - held) * p * 1e-4, 5.0)
            if need <= pf.cash:
                pf._order(c, "buy", tgt_sh - held, p)


def run(aum, rebs, raw, F, trad, idx):
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
    last = rebs[-1]
    prices_l = raw.loc[last["exec"]]
    pf0 = PaperPortfolio(aum)
    rebalance_fill(pf0, last["target"], prices_l, trad.loc[last["exec"]])
    mv = sum(s * prices_l.get(c, np.nan) for c, s in pf0.shares.items() if pd.notna(prices_l.get(c, np.nan)))
    return {"持有": len(pf0.shares), "目标": len(last["target"]), "使用率": mv / aum,
            "年化": m["年化"], "夏普": m["夏普"], "回撤": m["最大回撤"],
            "净值": nav.iloc[-1], "费用": tot_fee / aum / years,
            "分红": pf.div_cash, "订单": len(pf.trades)}


def main():
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs0, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index

    print(f"== Round 13 60万 集中版·满仓补买 ==  同池等权基准年化 {ann_bench:.1%}")
    rows = []
    for N in (100, 120, 150):
        rebs = r5_topN_rebalances(close, amount, tst, isst, ind, N)
        rows.append((f"60万 前{N}只+补买", run(600_000, rebs, raw, F, trad, idx)))

    print(f"\n{'口径':<16}{'持/目':<8}{'使用率':<7}{'年化':<8}{'超额':<8}{'夏普':<6}"
          f"{'回撤':<8}{'费用/年':<8}{'净值':<6}{'订单'}")
    for name, r in rows:
        exc = r["年化"] - ann_bench
        print(f"{name:<16}{r['持有']}/{r['目标']:<5}{r['使用率']:.0%}  "
              f"{r['年化']:6.1%}  {exc:+6.2%}  {r['夏普']:5.2f}  {r['回撤']:7.1%}  "
              f"{r['费用']:6.2%}  {r['净值']:5.2f}x  {r['订单']}")
    print("\n对照(Round12归档): 前150(不补买) +3.20pp/2.01%费/73%用 | 300万满配 +4.43pp")
    print("\n判定:")
    for name, r in rows:
        exc = r["年化"] - ann_bench
        ok = r["使用率"] >= 0.90 and exc >= 0.03 and r["费用"] <= 0.02
        print(f"  {name}: 使用率{r['使用率']:.0%} 超额{exc:+.2%} 费用{r['费用']:.2%} "
              f"→ {'✅通过' if ok else '未达标'}")


if __name__ == "__main__":
    main()
