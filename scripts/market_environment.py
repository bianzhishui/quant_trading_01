#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""市场环境仪表盘 —— 感知当前市场走势(跨 R5/P3 两策略, 用项目数据)。

输出 5 块:
1. 风格: 全市场等权(小盘代理) vs 沪深300, 近20/60日滚动超额 → 小盘强/弱
2. 宽度: 近20日上涨家数占比, 当日涨停/跌停家数
3. 策略环境: 低价池(3-4元真实价)规模 + 扣非为正通过率(P3 供给端);
            全市场成交额中位(R5 流动性环境)
4. 估值: 全市场 PB 中位(分位近似)
5. 策略超额: R5/P3 账本净值 vs 全市场等权(建仓以来)

用法: .venv/bin/python scripts/market_environment.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.data_io import load_full_daily  # noqa: E402


def main() -> None:
    print("加载全市场数据...", flush=True)
    full = load_full_daily()
    full["date"] = pd.to_datetime(full["date"])
    last_date = full["date"].max()
    print(f"最新交易日: {last_date.date()}\n", flush=True)

    # ---- 全市场等权(小盘代理) ----
    ret_ew = full.pivot(index="date", columns="code", values="close").pct_change()
    ew = (1 + ret_ew.mean(axis=1).fillna(0)).cumprod()

    # 沪深300
    try:
        from quant_trading_01.data_loader import load_index_daily

        hs300 = load_index_daily("000300", start="20200101", refresh=False)["close"]
        hs300 = (
            pd.to_datetime(hs300.index)
            if not isinstance(hs300.index, pd.DatetimeIndex)
            else hs300
        )
        hs300 = hs300.reindex(ew.index).ffill()
    except Exception as e:
        print(f"  [跳过] 沪深300: {e}")
        hs300 = None

    print("=== 1) 风格(全市场等权 vs 沪深300, 小盘代理) ===")
    if hs300 is not None:
        rel = (ew / hs300).dropna()
        for w in (20, 60, 250):
            if len(rel) <= w:
                continue
            r = (rel.iloc[-1] / rel.iloc[-1 - w] - 1) * 100
            print(
                f"  近{w}日 小盘相对强弱: {r:+.1f}% ({'小盘强势' if r > 0 else '小盘弱势'})"
            )
    ew20 = ew.iloc[-1] / ew.iloc[-21] - 1 if len(ew) > 21 else np.nan
    print(f"  全市场等权近20日: {ew20:+.1%}")

    # ---- 宽度 ----
    print("\n=== 2) 市场宽度 ===")
    close = full.pivot(index="date", columns="code", values="close")
    ret_d = close.pct_change()
    up20 = (ret_d.iloc[-20:] > 0).sum().sum() / ret_d.iloc[-20:].notna().sum().sum()
    up_today = (ret_d.iloc[-1] > 0).sum()
    dn_today = (ret_d.iloc[-1] < 0).sum()
    limit_up = (ret_d.iloc[-1] >= 0.098).sum()
    limit_dn = (ret_d.iloc[-1] <= -0.098).sum()
    print(
        f"  近20日上涨家数占比: {up20:.0%} ({'普涨' if up20 > 0.6 else '分化' if up20 > 0.45 else '偏弱'})"
    )
    print(f"  今日: 涨 {up_today} / 跌 {dn_today} | 涨停 {limit_up} / 跌停 {limit_dn}")

    # ---- 策略环境 ----
    print("\n=== 3) 策略环境 ===")
    # 低价池(3-4元): 用收盘价近似真实价(精确需复权, 仪表盘用当日收盘粗判)
    last_close = close.iloc[-1]
    low_pool = last_close.between(3.0, 4.0, inclusive="left").sum()
    prev_close = close.iloc[-21] if len(close) > 21 else None
    low_pool_prev = (
        (prev_close.between(3.0, 4.0, inclusive="left")).sum()
        if prev_close is not None
        else np.nan
    )
    print(
        f"  低价池(3-4元收盘近似): 当前 {low_pool} 只 (20日前 {low_pool_prev:.0f}) "
        f"{'扩张' if low_pool >= low_pool_prev else '收缩'}"
    )
    amt = full.pivot(index="date", columns="code", values="amount")
    print(
        f"  全市场成交额中位(当日): {amt.iloc[-1].median() / 1e8:.1f}亿 | "
        f"近20日: {amt.iloc[-20:].median().median() / 1e8:.1f}亿"
    )

    # ---- 估值 ----
    print("\n=== 4) 估值 ===")
    pb = full.pivot(index="date", columns="code", values="pbMRQ")
    pb_pos = pb.iloc[-1].dropna()
    pb_pos = pb_pos[pb_pos > 0]
    print(
        f"  全市场 PB 中位: {pb_pos.median():.2f} | PB<1(破净)占比: {(pb_pos < 1).mean():.0%}"
    )

    # ---- 策略超额 ----
    print("\n=== 5) 策略超额(建仓以来 vs 全市场等权) ===")
    for strat, outdir, pat in [
        ("R5", "r5", "ledger_aum*w.json"),
        ("P3", "p3", "ledger_p3_aum*w.json"),
    ]:
        import glob
        import re

        ledgers = sorted(
            glob.glob(f"output/{outdir}/{pat}"),
            key=lambda x: int(re.search(r"(\d+)w", x).group(1)),
        )
        if not ledgers:
            continue
        lf = ledgers[-1]  # 最大账户
        led = json.load(open(lf))
        h = led["nav_history"]
        if not h:
            continue
        nav0 = h[0]["nav"]
        prices_last = close.iloc[-1]
        nav_now = led["cash"] + sum(
            s * prices_last[c]
            for c, s in led["shares"].items()
            if c in prices_last.index and pd.notna(prices_last[c])
        )
        ew_base = ew.loc[pd.Timestamp(h[0]["date"])]
        ew_now = ew.iloc[-1]
        print(
            f"  {strat}({int(led['aum'] / 1e4)}万): 建仓以来 {nav_now / nav0 - 1:+.2%} | "
            f"全市场等权 {ew_now / ew_base - 1:+.2%} | 超额 {nav_now / nav0 - ew_now / ew_base:+.2%}"
        )


if __name__ == "__main__":
    main()
