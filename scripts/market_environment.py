#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""市场环境仪表盘 v2 —— 感知市场走势(跨 R5/P3, 更高精度)。

v2 改进(2026-09-24):
- 风格: 中证1000(纯小盘) vs 沪深300, 滚动相对强弱(原全市场等权近似升级)
- 低价池: 真实价(复权) 3-4 元池 + 近3年扣非通过率(P3 精确供给端, 原收盘价近似升级)
- 估值: PB 中位 + 历史分位(2014 以来) + 破净率(原绝对值升级)
保留: 宽度/成交额/策略超额

用法: .venv/bin/python scripts/market_environment.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.data_io import load_full_daily  # noqa: E402


def _load_index(symbol: str, start: str = "20140101") -> pd.Series | None:
    """指数日线(缓存在 data/)。"""
    try:
        from quant_trading_01.data_loader import load_index_daily

        s = load_index_daily(symbol, start=start, refresh=False)["close"]
        s = pd.to_datetime(s.index) if not isinstance(s.index, pd.DatetimeIndex) else s
        return s
    except Exception as e:
        print(f"  [跳过] 指数 {symbol}: {e}", flush=True)
        return None


def main() -> None:
    print("加载全市场数据...", flush=True)
    full = load_full_daily()
    full["date"] = pd.to_datetime(full["date"])
    last_date = full["date"].max()

    # ---- 真实价 + 财务(load_data 一次, 供低价池/扣非) ----
    print("加载真实价与财务...", flush=True)
    from scripts.factor_round41_low_price import load_data

    data = load_data()
    real, ded = data["real"], data["ded"]

    print(f"最新交易日: {last_date.date()}\n", flush=True)

    # ---- 1) 风格: 中证1000 vs 沪深300 ----
    print("=== 1) 风格(中证1000 vs 沪深300, 纯小盘代理) ===")
    zs1000 = _load_index("000852")
    hs300 = _load_index("000300")
    if zs1000 is not None and hs300 is not None:
        rel = (zs1000 / hs300).dropna()
        for w in (20, 60, 250):
            if len(rel) <= w:
                continue
            r = (rel.iloc[-1] / rel.iloc[-1 - w] - 1) * 100
            print(
                f"  近{w}日 小盘相对强弱: {r:+.1f}% ({'小盘强势' if r > 0 else '小盘弱势'})"
            )
    else:
        print("  (指数不可用)")

    # ---- 2) 宽度 ----
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

    # ---- 3) 策略环境(真实价低价池 + 扣非通过率) ----
    print("\n=== 3) 策略环境(P3 供给端, 真实价) ===")
    real_T = real.loc[last_date]
    pool_now = real_T.between(3.0, 4.0, inclusive="left").sum()
    i20 = close.index.get_indexer([last_date], method="nearest")[0]
    d20 = close.index[max(0, i20 - 20)]
    pool_20 = real.loc[d20].between(3.0, 4.0, inclusive="left").sum()
    print(
        f"  真实价低价池(3-4元): 当前 {pool_now} 只 (20日前 {pool_20:.0f}) "
        f"{'扩张' if pool_now >= pool_20 else '收缩'}"
    )
    vis = ded.index[ded.index + pd.Timedelta(days=120) <= last_date]
    if len(vis) >= 3:
        pool_mask = real_T.between(3.0, 4.0, inclusive="left").astype(bool)
        pool_codes = list(pool_mask[pool_mask].index)
        last3 = ded.loc[vis[-3:], pool_codes]
        pass_rate = (last3 > 0).all(axis=0).mean()
        print(
            f"  低价池近3年扣非为正通过率: {pass_rate:.0%} "
            f"({'健康' if pass_rate > 0.35 else '恶化中' if pass_rate > 0.25 else '显著恶化'})"
        )
    amt = full.pivot(index="date", columns="code", values="amount")
    print(
        f"  全市场成交额中位: 当日 {amt.iloc[-1].median() / 1e8:.1f}亿 | 近20日 {amt.iloc[-20:].median().median() / 1e8:.1f}亿"
    )

    # ---- 4) 估值(PB 中位 + 历史分位) ----
    print("\n=== 4) 估值 ===")
    pb = full.pivot(index="date", columns="code", values="pbMRQ")
    pb_pos = pb[pb > 0]
    pb_med = pb_pos.median(axis=1).dropna()
    cur = pb_med.iloc[-1]
    pct = (pb_med < cur).mean() * 100
    brk = (pb_pos.iloc[-1] < 1).mean()
    print(
        f"  全市场 PB 中位: {cur:.2f} | 历史分位(2014以来): {pct:.0f}% "
        f"({'偏高' if pct > 70 else '中性' if pct > 30 else '偏低'}) | 破净率 {brk:.0%}"
    )

    # ---- 5) 策略超额 ----
    print("\n=== 5) 策略超额(建仓以来 vs 全市场等权) ===")
    ret_ew = close.pct_change()
    ew = (1 + ret_ew.mean(axis=1).fillna(0)).cumprod()
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
        led = json.load(open(ledgers[-1]))
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
