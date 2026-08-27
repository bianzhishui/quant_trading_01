#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""回测入口：拉数据 -> 生成信号 -> 回测 -> 输出报告和图。

用法:
    .venv/bin/python run_backtest.py                    # 默认 贵州茅台 600519
    .venv/bin/python run_backtest.py --symbol 300750    # 换标的（创业板 limit=20%）
    .venv/bin/python run_backtest.py --synthetic        # 离线演示，不发网络请求
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")          # 无界面环境也能出图
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data_loader import load_index_daily, load_stock_daily, make_synthetic_daily
from src.backtest import run_backtest
from strategies.dual_ma import dual_moving_average


def main() -> None:
    ap = argparse.ArgumentParser(description="双均线策略回测")
    ap.add_argument("--symbol", default="600519", help="6位股票代码")
    ap.add_argument("--start", default="20190101")
    ap.add_argument("--end", default=None)
    ap.add_argument("--short", type=int, default=20)
    ap.add_argument("--long", dest="long_", type=int, default=60)
    ap.add_argument("--synthetic", action="store_true", help="使用随机数据离线测试")
    ap.add_argument("--limit", type=float, default=None,
                    help="涨跌停幅度：默认按代码自动判断(300/688开头=0.20，其余0.10)")
    args = ap.parse_args()

    if args.limit is not None:
        limit = args.limit
    else:
        limit = 0.20 if args.symbol[:3] in {"300", "688"} else 0.10

    # ---------- 数据 ----------
    if args.synthetic:
        df = make_synthetic_daily()
        bench = None
        print("== 使用合成随机行情（离线演示）==\n")
    else:
        print(f"下载/读取缓存: {args.symbol} 自 {args.start} ...")
        df = load_stock_daily(args.symbol, start=args.start, end=args.end)
        try:
            bench = load_index_daily("000300", start=args.start, end=args.end)
            bench = bench.reindex(df.index).ffill()
        except Exception as e:                     # 基准失败不影响主流程
            print(f"警告: 沪深300基准获取失败({e})，跳过对比")
            bench = None

    # ---------- 信号 + 回测 ----------
    signal = dual_moving_average(df["close"], short=args.short, long_=args.long_)
    res = run_backtest(df, signal, limit_pct=limit)

    print(res.summary())

    # ---------- 买入持有 & 基准对照 ----------
    bnh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    print(f"\n同期买入持有       : {bnh:.2%}")
    if bench is not None and len(bench.dropna()) > 1:
        b_ret = bench["close"].iloc[-1] / bench["close"].iloc[0] - 1
        print(f"同期沪深300        : {b_ret:.2%}")

    # ---------- 出图 ----------
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1, 1]})
    ax = axes[0]
    ax.plot(df.index, df["close"], lw=1, label="收盘价")
    ma_s = df["close"].rolling(args.short).mean()
    ma_l = df["close"].rolling(args.long_).mean()
    ax.plot(df.index, ma_s, lw=0.8, label=f"MA{args.short}")
    ax.plot(df.index, ma_l, lw=0.8, label=f"MA{args.long_}")
    title = ("合成数据" if args.synthetic else args.symbol) + \
        f" 双均线策略 (MA{args.short}/MA{args.long_})"
    ax.set_title(title)
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)

    ax = axes[1]
    ax.fill_between(res.weights.index, res.weights, step="post", alpha=0.5)
    ax.set_ylabel("仓位"); ax.set_ylim(-0.05, 1.1); ax.grid(alpha=0.3)

    ax = axes[2]
    dd = res.equity / res.equity.cummax() - 1
    ax.fill_between(dd.index, dd, alpha=0.5, color="tomato")
    ax.set_ylabel("回撤"); ax.grid(alpha=0.3)

    out = Path(__file__).parent / "output" / \
        f"backtest_{args.symbol}_ma{args.short}_{args.long_}.png"
    out.parent.mkdir(exist_ok=True)
    fig.tight_layout(); fig.savefig(out, dpi=130)
    print(f"\n图表已保存: {out}")

    csv_out = out.with_suffix(".trades.csv")
    res.trades.to_csv(csv_out, index=False)
    print(f"成交明细已保存: {csv_out}  ({len(res.trades)} 笔)")


if __name__ == "__main__":
    main()
