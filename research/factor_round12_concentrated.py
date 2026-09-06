#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 12 小资金集中版: 60万 综合分全局前 N 只等权 (N∈{150,200,300}).

同一套 R5 池/因子/行业内百分位, 仅把"前20%(~575只)"改为"综合分全局前 N 只";
share 级全口径成本与 paper_trade.replay 完全一致。输出与 60万现状/300万满配 对比。

用法: python research/factor_round12_concentrated.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import (PaperPortfolio, _load, _load_corp, build_pool, metrics,
                                  month_last_days, r5_rebalances)
from research.paper_trade import MIN_IND, MIN_N
from research.reversal_factor import ew_nav


def r5_topN_rebalances(close, amount, tst, isst, ind, N):
    """R5 因子同池, 但目标 = 综合分全局前 N 只(等权)。"""
    pool = build_pool(close, tst, isst)
    amihud = ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    mom = close.shift(21) / close.shift(250) - 1.0
    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    rebs = []
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
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = (pa + pm) / 2
        top = sc.nlargest(min(N, len(sc))).index
        rebs.append({"T": T, "exec": exec_day, "target": set(top)})
    return rebs


def run(aum, rebs, raw, F, trad, idx):
    """share 级全口径回放 (与 paper_trade.replay 同逻辑), 返回指标 dict。"""
    F_prev = F.shift(1).fillna(F.iloc[0])
    pf = PaperPortfolio(aum)
    rebs_d = {r["exec"]: r for r in rebs}
    navs, orders = [], 0
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        fn, fp = F.loc[dt], F_prev.loc[dt]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
        rb = rebs_d.get(dt)
        if rb is not None:
            pf.rebalance(rb["target"], prices, trad.loc[dt])
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / aum
    m = metrics(nav)
    years = len(nav) / 244
    tot_fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
    # 建仓持仓数与资金使用率(最新信号执行日)
    last = rebs[-1]
    prices_l = raw.loc[last["exec"]]
    pf0 = PaperPortfolio(aum)
    pf0.rebalance(last["target"], prices_l, trad.loc[last["exec"]])
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
    years = len(idx) / 244

    print(f"== Round 12 60万 集中版(全局前N等权) ==  同池等权基准年化 {ann_bench:.1%}")
    rows = []
    # 60万 现状基线 (R5 等权575 退化版)
    rows.append(("60万 现状(575等权)", run(600_000, rebs0, raw, F, trad, idx)))
    # 集中版
    for N in (150, 200, 300):
        rebs = r5_topN_rebalances(close, amount, tst, isst, ind, N)
        rows.append((f"60万 前{N}只", run(600_000, rebs, raw, F, trad, idx)))

    print(f"\n{'口径':<16}{'持/目':<8}{'使用率':<7}{'年化':<8}{'超额':<8}{'夏普':<6}"
          f"{'回撤':<8}{'费用/年':<8}{'净值':<6}{'订单'}")
    for name, r in rows:
        exc = r["年化"] - ann_bench
        print(f"{name:<16}{r['持有']}/{r['目标']:<5}{r['使用率']:.0%}  "
              f"{r['年化']:6.1%}  {exc:+6.2%}  {r['夏普']:5.2f}  {r['回撤']:7.1%}  "
              f"{r['费用']:6.2%}  {r['净值']:5.2f}x  {r['订单']}")
    print(f"\n参考: 300万满配 = 超额 +4.43pp | 60万现状 = +1.23pp (回测已归档)")
    # 判定
    print("\n判定:")
    for name, r in rows[1:]:
        exc = r["年化"] - ann_bench
        ok = exc >= 0.03 and r["费用"] <= 0.015 and r["使用率"] >= 0.90
        print(f"  {name}: 超额{exc:+.2%} 费用{r['费用']:.2%} 使用率{r['使用率']:.0%} "
              f"→ {'✅通过' if ok else '未达标'}")


if __name__ == "__main__":
    main()
