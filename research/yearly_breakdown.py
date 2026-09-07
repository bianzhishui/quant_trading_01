#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""R5 全期分年收益分解 —— 只读分析。

复用 paper_trade 的冻结信号逻辑(r5_rebalances, 零参数改动),
按 15bp 研究基准口径(= spec 文档 +4.61pp 口径)输出每个日历年的:
策略绝对收益 / 同池等权基准 / 超额 / 年内最大回撤。

用途: 回答"会不会出现大亏年份"——用 2014-2026 全历史实证, 不用猜测。
用法: uv run python research/yearly_breakdown.py   (只读, 约数分钟)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import _load, r5_rebalances
from research.reversal_factor import ew_nav
from research.dividend_factor import metrics


def main() -> None:
    print("== R5 全期分年收益分解 (15bp 研究口径, 只读) ==")
    close, amount, tst, isst, ind = _load()
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    strat_sets = {r["exec"]: r["target"] for r in rebs}
    nav_s, _ = ew_nav(ret, strat_sets, 15e-4)
    nav_b, _ = ew_nav(ret, bench, 15e-4)

    m_s, m_b = metrics(nav_s), metrics(nav_b)
    print(f"对账: 策略年化 {m_s['年化']:+.1%} vs 基准 {m_b['年化']:+.1%} "
          f"→ 超额 {m_s['年化']-m_b['年化']:+.2%} (spec 记载 +4.61pp 口径) | "
          f"最大回撤 {m_s['最大回撤']:.1%}\n")

    print(f"{'年份':<6}{'策略':>9}{'基准':>9}{'超额':>9}{'年内回撤':>9}")
    rows = []
    for y in sorted(nav_s.index.year.unique()):
        s = nav_s[nav_s.index.year == y]
        b = nav_b[nav_b.index.year == y]
        if len(s) < 30:                       # 2013 半年热身段
            print(f"{y}(部分) {s.iloc[-1]/s.iloc[0]-1:+.1%}")
            continue
        rs = s.iloc[-1] / s.iloc[0] - 1
        rb = b.iloc[-1] / b.iloc[0] - 1
        dd = (s / s.cummax() - 1).min()
        rows.append({"年份": y, "策略": rs, "基准": rb, "超额": rs - rb, "年内回撤": dd})
        print(f"{y:<6}{rs:>+9.1%}{rb:>+9.1%}{rs-rb:>+9.1%}{dd:>+9.1%}")

    df = pd.DataFrame(rows)
    neg = df[df["策略"] < -0.10]
    print(f"\n策略年收益 < -10% 的年份: {len(neg)} 个" +
          (f": {', '.join(neg['年份'].astype(str))}" if len(neg) else ""))
    print(f"最差年: {df.loc[df['策略'].idxmin(), '年份']} "
          f"({df['策略'].min():+.1%}) | 最好年: {df.loc[df['策略'].idxmax(), '年份']} "
          f"({df['策略'].max():+.1%})")
    # 回撤最深的episode
    ddser = nav_s / nav_s.cummax() - 1
    trough = ddser.idxmin()
    peak = nav_s.loc[:trough].idxmax()
    rec = ddser.loc[trough:][ddser.loc[trough:] > -0.01]
    rec_date = rec.index[0] if len(rec) else None
    print(f"最深回撤: {peak.date()} 顶部 → {trough.date()} 谷底 "
          f"({ddser.min():+.1%})" +
          (f", 收复于 {rec_date.date()}" if rec_date is not None else ", 至今未收复"))


if __name__ == "__main__":
    main()
