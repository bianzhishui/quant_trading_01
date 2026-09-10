#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 26 R5 打分权重敏感性（预注册，敏感性分析非优化）。

sc = w×rank行业内(Amihud) + (1-w)×rank行业内(动量), w∈{0.3,0.4,0.5,0.6,0.7}。
固定: 全市场池/前20%等权/15bp/月频/阻塞引擎(生产口径)。300万, 141期。
判定: ① w∈{0.4,0.5,0.6} 超额波动 < 0.5pp → 稳健。

用法: python research/factor_round26_weight_sensitivity.py
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
from research.reversal_factor import ew_nav  # noqa: E402

COST = 15e-4
AUM = 3_000_000
WEIGHTS = [0.3, 0.4, 0.5, 0.6, 0.7]


def r5_rebalances_w(close, amount, tst, isst, ind, w):
    """R5 打分带权重 w(Amihud 权重): sc = w*pa + (1-w)*pm, 前 20% 等权。"""
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
        sc = w * pa + (1 - w) * pm
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        rebs.append({"T": T, "exec": exec_day, "target": set(codes[q == 4])})
    return rebs, bench, ret


def run_arm(rebs, raw, F, trad, idx, ret):
    """share 级全口径回放（阻塞引擎, 生产 Round 24 口径）。"""
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
            pf.rebalance(rb["target"], prices, trad.loc[dt], ret.loc[dt])
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
        "换手": turnover,
        "费用/年": tot_fee / AUM / years,
    }


def main() -> None:
    print("== Round 26 R5 打分权重敏感性 (预注册 v1.0, 敏感性非优化) ==")
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    ret = close.pct_change()

    rows = []
    for w in WEIGHTS:
        rebs, bench, _ = r5_rebalances_w(close, amount, tst, isst, ind, w)
        nav_bench, _ = ew_nav(ret, bench, COST)
        ann_bench = metrics(nav_bench)["年化"]
        r = run_arm(rebs, raw, F, trad, idx, ret)
        rows.append((w, r, r["年化"] - ann_bench))
        print(
            f"  w={w:.1f}: 超额 {r['年化'] - ann_bench:+.2%} | 夏普 {r['夏普']:.2f} | "
            f"回撤 {r['回撤']:.1%} | 换手 {r['换手']:.1f} | 净值 {r['净值']:.2f}x",
            flush=True,
        )

    print("\n== 权重-超额表 ==")
    print(
        f"{'Amihud权重':<12}{'超额15bp':<10}{'夏普':<7}{'回撤':<9}{'换手':<8}{'净值'}"
    )
    for w, r, exc in rows:
        print(
            f"w={w:.1f}     {exc:+6.2%}   {r['夏普']:5.2f}  {r['回撤']:7.1%}  "
            f"{r['换手']:5.1f}  {r['净值']:5.2f}x"
        )
    ex = {w: exc for w, _, exc in rows}
    near = max(ex[w] for w in (0.4, 0.5, 0.6)) - min(ex[w] for w in (0.4, 0.5, 0.6))
    span = max(ex.values()) - min(ex.values())
    w_opt = max(ex, key=ex.get)
    print(
        f"\n① 邻域波动(0.4~0.6): {near:+.2%} → {'✅ 稳健(<0.5pp)' if near < 0.005 else '❌ 脆弱'}"
    )
    print(f"② 全区间跨度(0.3~0.7): {span:+.2%}")
    print(
        f"③ 超额最高权重: w={w_opt:.1f} (0.5 居中 {'✅' if w_opt == 0.5 else '⚠️ 偏离'})"
    )
    verdict = (
        "✅ 50:50 处于平稳高原, R5 打分结构稳健"
        if near < 0.005
        else "❌ 权重敏感, 暴露过拟合风险(生产不动)"
    )
    print(f"\n结论: {verdict}")


if __name__ == "__main__":
    main()
