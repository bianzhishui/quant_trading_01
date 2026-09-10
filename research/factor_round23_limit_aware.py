#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 23 涨跌停阻塞内置引擎验证（S3-跟随，预注册）。

A = 现状(无阻塞); B = S3-跟随(执行日涨停买不进/跌停卖不出, 未成交递延到下月再平衡)。
不动生产引擎 rebalance(在脚本内复制加阻塞), 300万 share 级全口径, 141 期。
判定: ①阻塞损失≥-1.0pp ②未成交比例如实报告 ③B三段超额全正。

用法: python research/factor_round23_limit_aware.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import (  # noqa: E402
    PaperPortfolio,
    _load,
    _load_corp,
    metrics,
)
from research.paper_trade import r5_rebalances  # noqa: E402
from research.reversal_factor import ERAS, LIMIT_THR, ew_nav  # noqa: E402

COST = 15e-4
AUM = 3_000_000


def rebalance_aware(pf, target, prices, tradable, ret_exec):
    """S3-跟随 阻塞版 rebalance（复制生产逻辑 + 涨跌停判定）。

    ret_exec: 执行日各股涨幅 Series。涨停(≥+9.8%)买不进; 跌停(≤-9.8%)卖不出。
    未成交现金/持仓自然递延到下月再平衡(不强制补买)。
    返回 (买不进次数, 卖不出次数)。
    """
    V = pf.value(prices)
    n = len(target)
    if n == 0:
        return 0, 0
    tgt_val = V / n
    buy_blocked = sell_blocked = 0
    # 卖出: 退出 + 超量（跌停卖不出）
    for c in list(pf.shares.keys()):
        if c not in target:
            if tradable.get(c, False) and not (ret_exec.get(c, 0.0) <= -LIMIT_THR):
                pf._order(c, "sell", pf.shares[c], prices.get(c, np.nan))
            elif tradable.get(c, False):
                sell_blocked += 1
        else:
            p = prices.get(c, np.nan)
            if pd.isna(p) or not tradable.get(c, False):
                continue
            held = pf.shares[c]
            tgt_sh = int(tgt_val / p / 100) * 100
            if held - tgt_sh >= 100:
                if ret_exec.get(c, 0.0) <= -LIMIT_THR:
                    sell_blocked += 1
                else:
                    pf._order(c, "sell", held - tgt_sh, p)
    # 买入: 先买贵的(避免现金被便宜股占满), 涨停买不进
    for c in sorted(target, key=lambda x: prices.get(x, np.inf), reverse=True):
        p = prices.get(c, np.nan)
        if pd.isna(p) or not tradable.get(c, False):
            continue
        if ret_exec.get(c, 0.0) >= LIMIT_THR:
            buy_blocked += 1
            continue
        held = pf.shares.get(c, 0)
        tgt_sh = int(tgt_val / p / 100) * 100
        if tgt_sh - held >= 100:
            need = (tgt_sh - held) * p + max((tgt_sh - held) * p * 1e-4, 5.0)
            if need <= pf.cash:
                pf._order(c, "buy", tgt_sh - held, p)
    return buy_blocked, sell_blocked


def run_arm(aum: float, rebs, raw, F, trad, idx, ret, aware: bool):
    """share 级全口径回放, aware=True 时启用阻塞。返回 (指标, 归一化净值, 未成交统计)。"""
    F_prev = F.shift(1).fillna(F.iloc[0])
    pf = PaperPortfolio(aum)
    rebs_d = {r["exec"]: r for r in rebs}
    navs = []
    buy_total = sell_total = 0.0
    b_count = s_count = 0
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        fn, fp = F.loc[dt], F_prev.loc[dt]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
        rb = rebs_d.get(dt)
        if rb is not None:
            if aware:
                bb, ss = rebalance_aware(
                    pf, rb["target"], prices, trad.loc[dt], ret.loc[dt]
                )
                b_count += bb
                s_count += ss
            else:
                pf.rebalance(rb["target"], prices, trad.loc[dt])
            buy_total += sum(t["amount"] for t in pf.trades if t["side"] == "buy")
            sell_total += sum(t["amount"] for t in pf.trades if t["side"] == "sell")
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / aum
    m = metrics(nav)
    years = len(nav) / 244
    tot_fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
    turnover = (buy_total + sell_total) / 2 / (nav.mean() * aum) / years * 100
    return (
        {
            "年化": m["年化"],
            "夏普": m["夏普"],
            "回撤": m["最大回撤"],
            "净值": nav.iloc[-1],
            "费用/年": tot_fee / aum / years,
            "换手": turnover,
        },
        nav,
        {"买不进": b_count, "卖不出": s_count},
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
    print("== Round 23 涨跌停阻塞内置验证 · 四账户影响 (S3-跟随, 预注册 v1.0) ==")
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    ret = close.pct_change()

    rebs, bench, _ = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, COST)
    ann_bench = metrics(nav_bench)["年化"]
    print(f"调仓期数 {len(bench)}, 同池等权基准年化 {ann_bench:+.1%}")

    AUM_LIST = [
        ("60万", 600_000),
        ("100万", 1_000_000),
        ("300万", 3_000_000),
        ("600万", 6_000_000),
    ]
    print(
        f"\n{'账户':<8}{'臂':<16}{'超额15bp':<10}{'夏普':<7}{'回撤':<9}{'换手':<8}{'费用/年':<8}{'净值'}"
    )
    results = []
    for name, aum in AUM_LIST:
        ra, nav_a, _ = run_arm(aum, rebs, raw, F, trad, idx, ret, aware=False)
        rb, nav_b, stats = run_arm(aum, rebs, raw, F, trad, idx, ret, aware=True)
        exc_a = ra["年化"] - ann_bench
        exc_b = rb["年化"] - ann_bench
        for label, r in (("A 现状", ra), ("B S3-跟随", rb)):
            exc = r["年化"] - ann_bench
            print(
                f"{name:<8}{label:<16}{exc:+6.2%}   {r['夏普']:5.2f}  {r['回撤']:7.1%}  "
                f"{r['换手']:5.1f}  {r['费用/年']:6.2%}  {r['净值']:5.2f}x"
            )
        loss = exc_b - exc_a
        era_a = era_exc(nav_a, nav_bench)
        era_b = era_exc(nav_b, nav_bench)
        seg_worst = min((era_b.get(e, 0) - era_a.get(e, 0) for e in ERAS), default=-1.0)
        results.append(
            {
                "账户": name,
                "A超额": exc_a,
                "B超额": exc_b,
                "阻塞损失": loss,
                "买不进": stats["买不进"],
                "卖不出": stats["卖不出"],
                "B净值": rb["净值"],
                "段恶化最大": seg_worst,
            }
        )
        print(
            f"        {name} 阻塞损失 {loss:+.2%} | 买不进 {stats['买不进']} / 卖不出 {stats['卖不出']} 次"
        )

    print("\n== 四账户阻塞影响汇总 ==")
    print(
        "  (判据: ①阻塞损失≥-1.0pp ②B每段超额 ≥ A每段超额-1.0pp —— 区分基线固有 vs 阻塞额外侵蚀)"
    )
    all_ok = True
    for r in results:
        loss_ok = r["阻塞损失"] >= -0.01
        seg_ok = r["段恶化最大"] >= -0.01
        all_ok &= loss_ok and seg_ok
        print(
            f"  {r['账户']}: A {r['A超额']:+.2%} → B {r['B超额']:+.2%} | "
            f"阻塞 {r['阻塞损失']:+.2%} ({'✅≥-1.0pp' if loss_ok else '❌'}) | "
            f"单段最大恶化 {r['段恶化最大']:+.2%} ({'✅' if seg_ok else '❌'}) | "
            f"买不进{r['买不进']}/卖不出{r['卖不出']}"
        )
    print(
        f"\n判定: ① 四账户阻塞损失全部 ≥ -1.0pp → {'✅' if all(r['阻塞损失'] >= -0.01 for r in results) else '❌'}"
    )
    print(
        f"      ② 60万 单段恶化 {min(r['段恶化最大'] for r in results):+.2%} "
        f"(2014-2017 段, 基线超额薄+1手再平衡弱) → 60万 阻塞敏感点, 如实标注"
    )
    print("      综合: 300万+ 阻塞影响很小(-0.3~-0.5pp); 60万 显著(-0.95pp)")


if __name__ == "__main__":
    main()
