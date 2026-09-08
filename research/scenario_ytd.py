#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""场景回放: 指定起始日期建仓, 四账户的每日净值+每日涨幅。

同一套 R5 等权575策略 + 全口径成本(佣金万1.5最低5元/印花万5/过户万0.1/1手取整/
现金无息/因子事件补分红税后10%), 仅建仓起点可指定。
不触碰正式账本(ledger_aum*.json), 输出:
  output/daily_nav_{START}start_aum{60w,100w,300w,600w}.csv  (date, nav, 涨幅%)

用法: python research/scenario_ytd.py [--start 2025-01-01]   (默认 2026-01-01)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import OUT, PaperPortfolio, _load, _load_corp, r5_rebalances
from research.paper_live import _factor_panel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default=None, help="截止日期(含), 默认数据末尾")
    args = ap.parse_args()
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else None
    prefix = start.strftime("%Y%m%d")

    close, amount, tst, isst, ind = _load()
    raw, _ = _load_corp(close)
    rebs, _, _ = r5_rebalances(close, amount, tst, isst, ind)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    F = _factor_panel(close)
    idx = close.index
    F_prev = F.shift(1).fillna(F.iloc[0])

    # 起始后首个执行日 (= 指定日期的建仓日)
    rb0 = next(r for r in rebs if r["exec"].date() >= start.date())
    rb_by_exec = {
        r["exec"]: r
        for r in rebs
        if r["T"] >= rb0["T"]
        and r["exec"] <= idx[-1]
        and (end is None or r["exec"] <= end)
    }
    i0 = idx.get_loc(rb0["exec"])
    i1 = idx.get_indexer([end], method="ffill")[0] if end is not None else len(idx) - 1

    print(
        f"== 建仓场景: 信号 {rb0['T'].date()} → 建仓执行 {rb0['exec'].date()} "
        f"({len(rb_by_exec)} 次月频调仓, 至 {idx[i1].date()}) =="
    )
    for aum in [600_000, 1_000_000, 3_000_000, 6_000_000]:
        pf = PaperPortfolio(aum)
        navs = []
        funds_rows = []  # 每次调仓的资金变动
        prev_post = None
        for i in range(i0, i1 + 1):
            prices = raw.iloc[i]
            if i > i0:  # 因子事件补除权缺口
                fn, fp = F.iloc[i], F_prev.iloc[i]
                for c in list(pf.shares.keys()):
                    if fn[c] != fp[c]:
                        pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
            rb = rb_by_exec.get(idx[i])
            if rb is not None:
                pre_nav = pf.value(prices)
                div_before = pf.div_cash
                pf.rebalance(rb["target"], prices, trad.loc[idx[i]])
                post_nav = pf.value(prices)
                buy = sum(t["amount"] for t in pf.trades if t["side"] == "buy")
                sell = sum(t["amount"] for t in pf.trades if t["side"] == "sell")
                fee = sum(
                    t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades
                )
                funds_rows.append(
                    {
                        "date": str(idx[i].date()),
                        "pre_nav": pre_nav,
                        "post_nav": post_nav,
                        "mret": (post_nav / prev_post - 1) * 100
                        if prev_post is not None
                        else None,
                        "buy": buy,
                        "sell": sell,
                        "turnover": (buy + sell) / 2 / pre_nav * 100
                        if pre_nav
                        else 0.0,
                        "fee": fee,
                        "div": pf.div_cash - div_before,
                        "cash": pf.cash,
                        "pos": post_nav - pf.cash,
                    }
                )
                prev_post = post_nav
                pf.trades = []
            navs.append(pf.value(prices))
        nav = pd.Series(navs, index=idx[i0 : i1 + 1])
        ret = nav.pct_change() * 100
        df = pd.DataFrame(
            {
                "date": nav.index.strftime("%Y-%m-%d"),
                "nav": nav.round(2),
                "涨幅%": ret.round(4),
                "较本金盈亏": (nav - aum).round(2),
            }
        )
        out = OUT / f"daily_nav_{prefix}_aum{int(aum / 1e4)}w.csv"
        df.to_csv(out, index=False)
        # 月度资金变动 CSV (与 paper_live 同列)
        fdf = pd.DataFrame(
            [
                {
                    "date": r["date"],
                    "pre_nav": r["pre_nav"],
                    "post_nav": r["post_nav"],
                    "月涨幅%": r["mret"],
                    "买入额": r["buy"],
                    "卖出额": r["sell"],
                    "换手率%": r["turnover"],
                    "费用": r["fee"],
                    "分红入账": r["div"],
                    "期末现金": r["cash"],
                    "期末持仓": r["pos"],
                    "较本金盈亏": r["post_nav"] - aum,
                }
                for r in funds_rows
            ]
        )
        fdf = fdf[
            [
                "date",
                "pre_nav",
                "post_nav",
                "月涨幅%",
                "买入额",
                "卖出额",
                "换手率%",
                "费用",
                "分红入账",
                "期末现金",
                "期末持仓",
                "较本金盈亏",
            ]
        ]
        fout = OUT / f"monthly_funds_{prefix}_aum{int(aum / 1e4)}w.csv"
        fdf.to_csv(fout, index=False)
        cum = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
        print(
            f"\n[{int(aum / 1e4)}万] {nav.index[0].date()} → {nav.index[-1].date()} "
            f"({len(nav) - 1} 个交易日) | 期间累计 {cum:+.2f}% | 资金文件 {fout.name}"
        )
        print("  近3次调仓资金变动(买/卖/换手/费用/月涨, 万):")
        for r in funds_rows[-3:]:
            m = r["mret"]
            m_s = f"{m:+.2f}%" if m is not None else "建仓"
            print(
                f"    {r['date']}: 买 {r['buy'] / 1e4:.1f} / 卖 {r['sell'] / 1e4:.1f} "
                f"| 换手 {r['turnover']:.1f}% | 费 {r['fee']:.0f}元 | {m_s}"
            )


if __name__ == "__main__":
    main()
