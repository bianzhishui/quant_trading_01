#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""导出当前策略选股清单(可每月复用)。

用法: python research/export_holdings.py [--csv output/strategy_holdings_YYYY-MM-DD.csv]
输出列: code 代码 | name 名称 | industry 行业(申万一级) | amihud 非流动性
        | mom 中期动量 | pa Amihud行业内百分位 | pm 动量行业内百分位
        | score 合成分 | price 执行日收盘(不复权) | qty300 300万股数(0=未买入)
        | qty600 600万股数 | weight 等权权重
数据: 信号 = 最新月末 → 执行日 T+1; 与 paper_live/paper_trade 同一信号代码路径。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import (OUT, ROOT, build_pool, _load, _load_corp, r5_rebalances)


def main(csv: str | None = None):
    close, amount, tst, isst, ind = _load()
    raw, _ = _load_corp(close)
    rebs, _, _ = r5_rebalances(close, amount, tst, isst, ind)
    last = rebs[-1]  # 最新信号 → 权威目标集(合成分前20%)
    target = last["target"]

    # 因子分(全池计算, 与 r5_rebalances 同一口径, 供百分位列使用)
    amihud = ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    mom = close.shift(21) / close.shift(250) - 1.0
    T = last["T"]
    e = build_pool(close, tst, isst).loc[T]
    a = amihud.loc[T][e].dropna()
    m = mom.loc[T][e].dropna()
    common = a.index.intersection(m.index).intersection(ind.index)
    ind_s = ind.reindex(common)
    keep = ind_s.value_counts()[ind_s.value_counts() >= 5].index
    codes_pool = common[ind_s.isin(keep)]
    pa = a.reindex(codes_pool).groupby(ind_s[codes_pool]).rank(pct=True)
    pm = m.reindex(codes_pool).groupby(ind_s[codes_pool]).rank(pct=True)
    sc = (pa + pm) / 2

    # 名称/行业
    sb = pd.read_parquet(ROOT / "data" / "fundamental" / "stock_basic.parquet")
    names = sb.set_index("code")["code_name"]
    indn = ind.rename("industry")

    # 两账户股数(账本)
    qty = {}
    for aum, key in [(3_000_000, "qty300"), (6_000_000, "qty600")]:
        lp = OUT / f"ledger_aum{int(aum/1e4)}w.json"
        if lp.exists():
            import json
            led = json.loads(lp.read_text())
            qty[key] = pd.Series(led["shares"], dtype=int)
        else:
            qty[key] = pd.Series(dtype=int)

    px = raw.loc[last["exec"]]
    codes = pd.Index(target)  # 权威目标(前20%)
    df = pd.DataFrame({
        "code": codes,
        "amihud": a.reindex(codes).round(6),
        "mom": m.reindex(codes).round(4),
        "pa": pa.reindex(codes).round(4),
        "pm": pm.reindex(codes).round(4),
        "score": sc.reindex(codes).round(4),
    })
    df["name"] = df["code"].map(names).fillna("?")
    df["industry"] = df["code"].map(indn).fillna("?")
    df["price"] = df["code"].map(px).round(2)
    for key in ("qty300", "qty600"):
        df[key] = df["code"].map(qty[key]).fillna(0).astype(int)
    df["weight"] = 1.0 / len(codes)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    cols = ["code", "name", "industry", "amihud", "mom", "pa", "pm", "score",
            "price", "qty300", "qty600", "weight"]
    out = csv or OUT / f"strategy_holdings_{last['exec'].date()}.csv"
    df[cols].to_csv(out, index=False)

    n300 = int((df["qty300"] > 0).sum())
    n600 = int((df["qty600"] > 0).sum())
    print(f"== 策略选股清单 信号 {last['T'].date()} → 执行 {last['exec'].date()} ==")
    print(f"  目标 {len(codes)} 只 | 300万实买 {n300} (差 {len(codes)-n300} 只: 停牌/涨停/1手不足)"
          f" | 600万实买 {n600}")
    print(f"  文件: {out}")
    print(f"\n  前 10 (按合成分):")
    print(df.head(10)[["code", "name", "industry", "amihud", "mom", "score", "price"]].to_string(index=False))
    print(f"\n  后 5 (按合成分):")
    print(df.tail(5)[["code", "name", "industry", "score", "price"]].to_string(index=False))
    print(f"\n  行业分布 top8: ")
    print(df["industry"].value_counts().head(8).to_string())


if __name__ == "__main__":
    csv = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("--csv") else None
    main(csv=csv)
