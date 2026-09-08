#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 11 全选满仓变体: 预算 = 100 × 目标集合内最高执行日收盘价 (全选满仓, 无高价股被跳过)。

与 paper_trade.replay 同一套 share 级全口径成本 (佣金万1.5最低5元/印花万5/过户万0.1/
1手取整/现金无息/因子事件补分红税后10%)。仅预算规则不同 → 每只目标股数由价格决定:
  B = 100 × max(执行日目标股收盘价);  target_shares = int(B/价/100)×100
隐含资金量 ≈ 575×B。输出与 600万/300万 既有回测的对比。

用法: python research/factor_round11_fullbuy.py
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
    r5_rebalances,
    metrics,
)
from research.reversal_factor import ew_nav


def main():
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    idx = close.index
    F_prev = F.shift(1).fillna(F.iloc[0])

    # 首个执行日: 初始资金 = 全选满仓所需 (≈575×B), 精确 = Σ目标股数×价
    rb0 = rebs[0]
    p0 = raw.loc[rb0["exec"]]
    B0 = 100.0 * p0[list(rb0["target"])].max()
    tgt_sh0 = {c: int(B0 / p0[c] / 100) * 100 for c in rb0["target"]}
    aum0 = sum(tgt_sh0[c] * p0[c] for c in rb0["target"])
    pf = PaperPortfolio(aum0)

    navs, n_orders, tot_fee = [], 0, 0.0
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        fn, fp = F.iloc[i], F_prev.iloc[i]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
        rb = next((r for r in rebs if r["exec"] == dt), None)
        if rb is not None:
            S = rb["target"]
            B = 100.0 * prices[list(S)].max()  # 本月预算 = 最高价×100
            tgt = {c: int(B / prices[c] / 100) * 100 for c in S}
            # 卖出: 退出持仓 + 超出目标(≥1手才动)
            for c in list(pf.shares.keys()):
                if c not in S:
                    if trad.loc[dt].get(c, False):
                        pf._order(c, "sell", pf.shares[c], prices.get(c, np.nan))
                else:
                    held = pf.shares[c]
                    want = tgt[c]
                    if (
                        held > want
                        and held - want >= 100
                        and trad.loc[dt].get(c, False)
                    ):
                        pf._order(c, "sell", held - want, prices.get(c, np.nan))
            # 买入: 未达标 ≥1手, 受现金约束
            for c in sorted(S, key=lambda x: prices.get(x, np.inf)):
                p = prices.get(c, np.nan)
                if pd.isna(p) or not trad.loc[dt].get(c, False):
                    continue
                diff = tgt[c] - pf.shares.get(c, 0)
                if diff >= 100:
                    need = diff * p * 1.0 + max(diff * p * 1e-4, 5.0)
                    if need <= pf.cash:
                        pf._order(c, "buy", diff, p)
            n_orders += len(pf.trades)
            tot_fee += sum(
                t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades
            )
            pf.trades = []
        navs.append(pf.value(prices))

    nav = pd.Series(navs, index=idx) / aum0
    m = metrics(nav)
    years = len(nav) / 244
    exc = m["年化"] - ann_bench
    # 当前隐含资金量(最新信号执行日)
    close_now, amount_now, tst_now, isst_now, ind_now = _load()
    raw_now, _ = _load_corp(close_now)
    rebs_now, _, _ = r5_rebalances(close_now, amount_now, tst_now, isst_now, ind_now)
    last = rebs_now[-1]
    pn = raw_now.loc[last["exec"]]
    Bn = 100.0 * pn[list(last["target"])].max()
    need = sum(int(Bn / pn[c] / 100) * 100 * pn[c] for c in last["target"])
    maxc = pn[list(last["target"])].max()

    print("== Round 11 全选满仓(最高价预算) 历史全口径回放 ==")
    print(
        f"  预算/只 B = 100×最高价(当前 {maxc:.2f}×100 = {Bn:.0f}元) | 目标 {len(last['target'])} 只"
    )
    print(f"  当前隐含资金量 ≈ {need / 1e4:.0f} 万 (575×{Bn:.0f}元)")
    print(
        f"  年化 {m['年化']:.1%} | 同池等权基准 {ann_bench:.1%} | 全口径超额 {exc:+.2%}pp"
    )
    print(
        f"  夏普 {m['夏普']:.2f} | 最大回撤 {m['最大回撤']:.1%} | 期末净值 {nav.iloc[-1]:.2f}"
    )
    print(
        f"  费用率 {tot_fee / aum0 / years:.2%}/年 (累计 {tot_fee / 1e4:.1f}万) | 分红(税后) {pf.div_cash / 1e4:.1f}万"
    )
    print("\n  对比参考 (既有回测):")
    print(
        "    300万: 预算5212元/只 持551只 年化11.9% 超额+4.43pp 回撤-49.2% 费用1.32%/年"
    )
    print(
        "    600万: 预算10430元/只 持575只 年化12.2% 超额+4.72pp 回撤-49.4% 费用0.95%/年"
    )


if __name__ == "__main__":
    main()
