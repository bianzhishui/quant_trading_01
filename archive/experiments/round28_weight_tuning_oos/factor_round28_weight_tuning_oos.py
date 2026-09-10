#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 28 权重扩展扫描 + 样本外验证（预注册）。

扩展 w∈{0.80~1.00} 看顶点; 样本外: 训练段(2014-2021)选 w_train* → 验证段(2022-2026)检验。
判定: ①顶点可见 ②样本外≥+1pp ③全区间不劣化 ④高原稳健(双侧) → 推荐 w_train*(需用户批准)。

用法: python research/factor_round28_weight_tuning_oos.py
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
SCAN_W = [0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 1.00]
TRAIN_END = "2021-12-31"  # 训练段 2014~2021; 验证段 2022~2026


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
    """share 级全口径回放（阻塞引擎, 生产口径）。返回 (指标, 归一化净值)。"""
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
    return (
        {
            "年化": m["年化"],
            "夏普": m["夏普"],
            "回撤": m["最大回撤"],
            "净值": nav.iloc[-1],
            "换手": turnover,
            "费用/年": tot_fee / AUM / years,
        },
        nav,
    )


def seg_exc(nav: pd.Series, bench_nav: pd.Series, s: str, e: str) -> float:
    a, b = nav[s:e], bench_nav[s:e]
    if len(a) < 10 or len(b) < 10:
        return np.nan
    return (
        metrics(a / a.dropna().iloc[0])["年化"]
        - metrics(b / b.dropna().iloc[0])["年化"]
    )


def main() -> None:
    print("== Round 28 权重扩展扫描 + 样本外验证 (预注册 v1.0) ==")
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    ret = close.pct_change()

    rows = []
    navs = {}
    for w in SCAN_W:
        rebs, bench, _ = r5_rebalances_w(close, amount, tst, isst, ind, w)
        nav_bench, _ = ew_nav(ret, bench, COST)
        r, nav = run_arm(rebs, raw, F, trad, idx, ret)
        ann_bench = metrics(nav_bench)["年化"]
        rows.append(
            {
                "w": w,
                "超额全区间": r["年化"] - ann_bench,
                "超额训练(14-21)": seg_exc(nav, nav_bench, "2014-01-01", TRAIN_END),
                "超额验证(22-26)": seg_exc(nav, nav_bench, "2022-01-01", "2026-12-31"),
                "回撤": r["回撤"],
                "换手": r["换手"],
            }
        )
        navs[w] = nav
        d = rows[-1]
        print(
            f"  w={w:.2f}: 全 {d['超额全区间']:+.2%} | 训练 {d['超额训练(14-21)']:+.2%} | "
            f"验证 {d['超额验证(22-26)']:+.2%} | 回撤 {d['回撤']:.1%} | 换手 {d['换手']:.1f}",
            flush=True,
        )

    print("\n== 顶点判断 ==")
    ex_all = {r["w"]: r["超额全区间"] for r in rows}
    print(
        f"  最高超额权重: w={max(ex_all, key=ex_all.get):.2f} ({max(ex_all.values()):+.2%})"
    )
    if ex_all[1.00] == max(ex_all.values()):
        print("  ⚠️ w=1.00 仍最高 → 未到顶点, 趋势指向纯 Amihud 单因子(去掉动量)")
    elif ex_all[1.00] < ex_all[0.95]:
        print("  ✅ w<1.00 出现回落 → 顶点可见")

    # 样本外: 训练段选 w_train*, 验证段检验
    train_ex = {
        r["w"]: r["超额训练(14-21)"] for r in rows if not np.isnan(r["超额训练(14-21)"])
    }
    w_train_star = max(train_ex, key=train_ex.get)
    ver_star = next(r["超额验证(22-26)"] for r in rows if r["w"] == w_train_star)
    ver_base = next(r["超额验证(22-26)"] for r in rows if r["w"] == 0.5)
    print("\n== 样本外验证 ==")
    print(
        f"  训练段(2014-21)最高权重 w_train*={w_train_star:.2f} "
        f"(训练超额 {train_ex[w_train_star]:+.2%})"
    )
    print(
        f"  验证段(2022-26): w_train* {ver_star:+.2%} vs 0.5 {ver_base:+.2%} "
        f"→ 差 {ver_star - ver_base:+.2%}"
    )

    # ① 顶点可见: 存在 w<1.00 超额 > 1.00 超额(回落), 或 1.00 与 0.95 接近(平顶)
    peak_below = max(ex_all[w] for w in SCAN_W if w < 1.00)
    c1 = ex_all[1.00] < peak_below or abs(ex_all[1.00] - ex_all[0.95]) <= 0.005
    # ② 样本外: w_train* 验证段 − 0.5 验证段 ≥ +1pp
    c2 = ver_star - ver_base >= 0.01
    # ③ 全区间不劣化: w_train* 全区间 ≥ 0.5 全区间
    c3 = ex_all[w_train_star] >= ex_all[0.5]
    # ④ 高原(双侧邻域, 用全区间超额); 端点(单侧)不可判 → False
    lo_w, hi_w = w_train_star - 0.05, w_train_star + 0.05
    side_lo = any(abs(x - lo_w) <= 1e-9 for x in SCAN_W)
    side_hi = any(abs(x - hi_w) <= 1e-9 for x in SCAN_W)
    c4 = False
    if side_lo and side_hi:
        nbs = [
            x
            for x in SCAN_W
            if abs(x - w_train_star) <= 0.05 + 1e-9 and x != w_train_star
        ]
        c4 = (max(ex_all[x] for x in nbs) - min(ex_all[x] for x in nbs)) < 0.005
    print(
        f"\n判定: ①顶点 {'✅' if c1 else '❌'} ②样本外 {'✅' if c2 else '❌'} "
        f"③全区间不劣化 {'✅' if c3 else '❌'} ④高原 {'✅' if c4 else '❌'}"
    )
    if all([c1, c2, c3, c4]):
        print(
            f"\n推荐 w_train*={w_train_star:.2f} (样本外成立 + 高原稳健) "
            f"→ 改生产需用户批准"
        )
    elif not c2:
        print(
            "\n② 样本外不成立 → 训练段最优在验证段失灵 → 过拟合证据, 维持 0.5 (诚实)"
        )
    else:
        print("\n判据未全过 → 诚实结论: 维持 0.5 或需用户决策")


if __name__ == "__main__":
    main()
