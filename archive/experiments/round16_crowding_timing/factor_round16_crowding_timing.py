#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 16 拥挤度极值择时: R5 等权575 × 拥挤度信号(池成交占比+池60日动量, 90/60分位迟滞).

触发: crowd≥90分位 → 仓位70%; crowd≤60分位 → 100%。仓位只在月度调仓执行日调整。
300万 全口径, 与 R5 基线同代码路径对比。

用法: python research/factor_round16_crowding_timing.py
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
    metrics,
    r5_rebalances,
)
from research.reversal_factor import build_pool, ew_nav


def crowding_series(close, amount, tst, isst):
    """拥挤度 = max(池成交占比分位, 池60日动量分位), 各对过去756日滚动求分位。"""
    pool = build_pool(close, tst, isst)
    amt = amount.fillna(0.0)
    share = (amt * pool).sum(axis=1) / amt.sum(axis=1).replace(0, np.nan)
    ret = close.pct_change()
    pool_ret = (ret * pool).sum(axis=1) / pool.sum(axis=1).replace(0, np.nan)
    mom60 = pool_ret.rolling(60).sum()

    def rolling_pct(s: pd.Series, win=756):
        return s.rolling(win, min_periods=200).apply(
            lambda x: float((x[-1] >= x).mean()), raw=True
        )

    p_s = rolling_pct(share)
    p_m = rolling_pct(mom60)
    return pd.concat([p_s, p_m], axis=1).max(axis=1)


def rebalance_scaled(pf: PaperPortfolio, target, prices, tradable, scale: float):
    """与 PaperPortfolio.rebalance 相同, 仅目标等权 × scale。"""
    V = pf.value(prices)
    n = len(target)
    if n == 0:
        return
    tgt_val = V * scale / n
    for c in list(pf.shares.keys()):
        if c not in target:
            if tradable.get(c, False):
                pf._order(c, "sell", pf.shares[c], prices.get(c, np.nan))
        else:
            p = prices.get(c, np.nan)
            if pd.isna(p) or not tradable.get(c, False):
                continue
            held = pf.shares[c]
            tgt_sh = int(tgt_val / p / 100) * 100
            if held - tgt_sh >= 100:
                pf._order(c, "sell", held - tgt_sh, p)
    for c in target:
        p = prices.get(c, np.nan)
        if pd.isna(p) or not tradable.get(c, False):
            continue
        held = pf.shares.get(c, 0)
        tgt_sh = int(tgt_val / p / 100) * 100
        if tgt_sh - held >= 100:
            pf._order(c, "buy", tgt_sh - held, p)


def run(aum, rebs, raw, F, trad, idx, use_timing):
    F_prev = F.shift(1).fillna(F.iloc[0])
    pf = PaperPortfolio(aum)
    rebs_d = {r["exec"]: r for r in rebs}
    scale = 1.0
    scale_dates = {"trim": [], "restore": []}
    scale_hist = []
    navs = []
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        fn, fp = F.loc[dt], F_prev.loc[dt]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
        rb = rebs_d.get(dt)
        if rb is not None:
            if use_timing:
                c = rb.get("crowd", np.nan)
                if pd.notna(c):
                    if c >= 0.90 and scale > 0.70:
                        scale = 0.70
                        scale_dates["trim"].append(dt)
                    elif c <= 0.60 and scale < 1.0:
                        scale = 1.0
                        scale_dates["restore"].append(dt)
            rebalance_scaled(pf, rb["target"], prices, trad.loc[dt], scale)
            scale_hist.append((dt, scale))
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / aum
    m = metrics(nav)
    years = len(nav) / 244
    tot_fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
    return {
        "nav": nav,
        "m": m,
        "费用": tot_fee / aum / years,
        "净值": nav.iloc[-1],
        "分红": pf.div_cash,
        "订单": len(pf.trades),
        "scale_dates": scale_dates,
        "avg_scale": float(np.mean([s for _, s in scale_hist])) if scale_hist else 1.0,
    }


def main():
    AUM = 3_000_000
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs0, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index

    print("== Round 16 拥挤度极值择时 ==")
    print("计算拥挤度信号(池成交占比+池60日动量 滚动分位)...")
    crowd = crowding_series(close, amount, tst, isst)
    for rb in rebs0:
        rb["crowd"] = crowd.get(rb["T"], np.nan)

    print(f"回放基线...  基准年化 {ann_bench:.1%}")
    base = run(AUM, rebs0, raw, F, trad, idx, use_timing=False)
    print("回放择时版...")
    tm = run(AUM, rebs0, raw, F, trad, idx, use_timing=True)

    def line(name, r):
        exc = r["m"]["年化"] - ann_bench
        return (
            f"{name:<10}年化 {r['m']['年化']:6.1%}  超额 {exc:+6.2%}  "
            f"夏普 {r['m']['夏普']:.2f}  回撤 {r['m']['最大回撤']:7.1%}  "
            f"费 {r['费用']:5.2%}  净值 {r['净值']:5.2f}x"
        )

    print("\n" + line("R5 基线", base))
    print(line("拥挤择时", tm))
    t_d, r_d = tm["scale_dates"]["trim"], tm["scale_dates"]["restore"]
    print(f"\n触发: 减仓 {len(t_d)} 次 @ {[str(d.date()) for d in t_d]}")
    print(f"      回补 {len(r_d)} 次 @ {[str(d.date()) for d in r_d]}")
    print(
        f"平均仓位 {tm['avg_scale']:.0%} | 择时版订单 {tm['订单']} (基线 {base['订单']})"
    )

    # 年度对比
    y = pd.DataFrame({"base": base["nav"], "timing": tm["nav"]}).resample("YE").last()
    y_base = y["base"].pct_change().fillna(y["base"].iloc[0] - 1)
    y_tm = y["timing"].pct_change().fillna(y["timing"].iloc[0] - 1)
    print("\n年度收益: 基线 vs 择时")
    for yr in y.index:
        print(f"  {yr.year}: {y_base.loc[yr]:+7.1%}  {y_tm.loc[yr]:+7.1%}")

    exc_b = base["m"]["年化"] - ann_bench
    exc_t = tm["m"]["年化"] - ann_bench
    print("\n判定(超额≥+3.5pp 且 回撤≤42% 且 触发≥3次):")
    ok = exc_t >= 0.035 and tm["m"]["最大回撤"] <= 0.42 and len(t_d) >= 3
    print(
        f"  超额 {exc_t:+.2%} (基线 {exc_b:+.2%}) | 回撤 {tm['m']['最大回撤']:.1%} "
        f"(基线 {base['m']['最大回撤']:.1%}) | 减仓 {len(t_d)} 次 → {'✅通过' if ok else '未达标'}"
    )


if __name__ == "__main__":
    main()
