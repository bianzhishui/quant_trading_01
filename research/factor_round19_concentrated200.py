#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 19 60万 集中版 · 前 200 只 + 满仓补买（预注册）。

闭合 Round 12/13 集中度补买曲线（100/120/150/200）：
- 选股: r5_topN_rebalances(N=200)（Round 12 同函数, 行业内百分位综合分前200）
- 执行: rebalance_fill（Round 13 同函数, 预算迭代再分配满仓补买）
- 账户: 60万, share 级全口径成本, 基准=同池等权（Round 12/13 同基准）
- 对照: Round12 前200等权 +2.99pp / Round13 前100/120/150+补买 +3.59/+3.36/+3.41pp

用法: python research/factor_round19_concentrated200.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import (  # noqa: E402
    MIN_IND,
    MIN_N,
    PaperPortfolio,
    _load,
    _load_corp,
    metrics,
    r5_rebalances,
)
from research.paper_trade import build_pool, month_last_days  # noqa: E402
from research.reversal_factor import ew_nav  # noqa: E402


def r5_topN_rebalances(close, amount, tst, isst, ind, N):
    """R5 因子同池, 但目标 = 综合分全局前 N 只(等权)。口径同 Round 12。"""
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
        top = sc.nlargest(min(N, len(sc))).index
        rebs.append({"T": T, "exec": exec_day, "target": set(top)})
    return rebs


def rebalance_fill(
    pf: PaperPortfolio, target: set, prices: pd.Series, tradable: pd.Series
):
    """等权 top-N, 预算在可买子集内迭代再分配(满仓补买)。口径同 Round 13。"""
    V = pf.value(prices)
    n = len(target)
    if n == 0:
        return
    budget = V / n
    for _ in range(10):
        n_b = sum(
            1
            for c in target
            if pd.notna(prices.get(c, np.nan))
            and tradable.get(c, False)
            and prices[c] * 100 <= budget
        )
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
    """share 级全口径回放 (与 Round 13 同逻辑), 返回指标 dict。"""
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
    mv = sum(
        s * prices_l.get(c, np.nan)
        for c, s in pf0.shares.items()
        if pd.notna(prices_l.get(c, np.nan))
    )
    return {
        "持有": len(pf0.shares),
        "目标": len(last["target"]),
        "使用率": mv / aum,
        "年化": m["年化"],
        "夏普": m["夏普"],
        "回撤": m["最大回撤"],
        "净值": nav.iloc[-1],
        "费用": tot_fee / aum / years,
        "分红": pf.div_cash,
        "订单": len(pf.trades),
    }


def main():
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs0, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index

    print(f"== Round 19 60万 前200只+满仓补买 ==  同池等权基准年化 {ann_bench:.1%}")
    N = 200
    rebs = r5_topN_rebalances(close, amount, tst, isst, ind, N)
    r = run(600_000, rebs, raw, F, trad, idx)
    exc = r["年化"] - ann_bench
    ok = r["使用率"] >= 0.90 and exc >= 0.03 and r["费用"] <= 0.02

    print(
        f"\n{'口径':<18}{'持/目':<8}{'使用率':<7}{'年化':<8}{'超额':<8}{'夏普':<6}"
        f"{'回撤':<8}{'费用/年':<8}{'净值':<6}{'订单'}"
    )
    print(
        f"{'60万 前200+补买':<18}{r['持有']}/{r['目标']:<5}{r['使用率']:.0%}  "
        f"{r['年化']:6.1%}  {exc:+6.2%}  {r['夏普']:5.2f}  {r['回撤']:7.1%}  "
        f"{r['费用']:6.2%}  {r['净值']:5.2f}x  {r['订单']}"
    )
    print(
        f"\n判定: 使用率{r['使用率']:.0%} 超额{exc:+.2%} 费用{r['费用']:.2%} "
        f"→ {'✅通过' if ok else '未达标'}"
    )
    print(
        "\n对照: 前200等权(不补买) +2.99pp/2.31%费/70%用 | "
        "前150+补买 +3.41pp/2.03%费/85%用 | 前120+补买 +3.36pp | "
        "前100+补买 +3.59pp/1.65%费/~90%用 | 300万满配 +4.43pp"
    )


if __name__ == "__main__":
    main()
