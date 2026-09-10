#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 27 R5 打分权重调整探索（预注册，防过拟合设计）。

细扫 w∈{0.55~0.80}，每权重全区间超额 + ERAS 三段 + 回撤 + 换手。
判定: ①改善≥+1pp ②三段全部不劣化 ③回撤≤+5pp ④高原波动<0.5pp → 推荐最高w*(高原内)。
改生产需用户最终批准。

用法: python research/factor_round27_weight_tuning.py
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
WEIGHTS = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


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
    print("== Round 27 R5 权重调整探索 (预注册 v1.0, 防过拟合) ==")
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    ret = close.pct_change()

    results = {}
    for w in WEIGHTS:
        rebs, bench, _ = r5_rebalances_w(close, amount, tst, isst, ind, w)
        nav_bench, _ = ew_nav(ret, bench, COST)
        ann_bench = metrics(nav_bench)["年化"]
        r, nav = run_arm(rebs, raw, F, trad, idx, ret)
        results[w] = {
            "超额": r["年化"] - ann_bench,
            "回撤": r["回撤"],
            "换手": r["换手"],
            "三段": era_exc(nav, nav_bench),
        }
        seg = " ".join(f"{e}:{v:+.1%}" for e, v in results[w]["三段"].items())
        print(
            f"  w={w:.2f}: 超额 {results[w]['超额']:+.2%} | 回撤 {r['回撤']:.1%} | "
            f"换手 {r['换手']:.1f} | 三段 {seg}",
            flush=True,
        )

    # 0.5 基线从 Round 26 已知: +4.18% | 三段待补 → 直接重算 0.5 做基准
    rebs5, bench5, _ = r5_rebalances_w(close, amount, tst, isst, ind, 0.5)
    nav_bench5, _ = ew_nav(ret, bench5, COST)
    ann5 = metrics(nav_bench5)["年化"]
    r5, nav5 = run_arm(rebs5, raw, F, trad, idx, ret)
    base_exc = r5["年化"] - ann5
    base_dd = r5["回撤"]
    base_seg = era_exc(nav5, nav_bench5)
    print(
        f"\n基线 w=0.50: 超额 {base_exc:+.2%} | 回撤 {base_dd:.1%} | "
        f"三段 {' '.join(f'{e}:{v:+.1%}' for e, v in base_seg.items())}"
    )

    print("\n== 判定 ==")
    candidates = []
    for w in WEIGHTS:
        r = results[w]
        c1 = r["超额"] - base_exc >= 0.01
        c2 = all(r["三段"][e] >= base_seg.get(e, -9.9) for e in ERAS)
        c3 = r["回撤"] - base_dd <= 0.05
        # ④ 高原: 需 w±0.05 双侧邻域都在扫描内才可判; 端点(单侧)高原不可判 → 不推荐
        side_lo = any(abs(x - (w - 0.05)) <= 1e-9 for x in WEIGHTS)
        side_hi = any(abs(x - (w + 0.05)) <= 1e-9 for x in WEIGHTS)
        if side_lo and side_hi:
            nbs = [x for x in WEIGHTS if abs(x - w) <= 0.05 + 1e-9 and x != w]
            c4 = (
                max(results[x]["超额"] for x in nbs)
                - min(results[x]["超额"] for x in nbs)
            ) < 0.005
        else:
            c4 = False  # 端点: 无法确认是否针尖, 诚实不推荐
        print(
            f"  w={w:.2f}: ①改善{'✅' if c1 else '❌'} ②三段{'✅' if c2 else '❌'} "
            f"③回撤{'✅' if c3 else '❌'} ④高原{'✅' if c4 else '❌'}"
        )
        if all([c1, c2, c3, c4]):
            candidates.append(w)
    if candidates:
        w_star = max(candidates)
        print(f"\n推荐权重: w*={w_star:.2f} (满足全部判据的最高 w, 高原内)")
        print(
            f"  w* 超额 {results[w_star]['超额']:+.2%} vs 基线 {base_exc:+.2%} (改善 {results[w_star]['超额'] - base_exc:+.2%})"
        )
        print("  → 改生产需用户最终批准 (另开执行变更流程, 账本重建另行决策)")
    else:
        print("\n无权重满足全部判据 → 维持 0.5 (调整不可靠, 诚实结论)")


if __name__ == "__main__":
    main()
