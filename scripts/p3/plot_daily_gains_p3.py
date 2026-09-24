#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""P3 八账户每日图 → output/p3/（与 R5 plot_daily_gains.py 对齐, 产物目录取 p3.out_dir）。

输出 2 个文件:
- daily_nav_p3.png      8 账户 NAV 合并 2×4 子图(每格标注最新 NAV + 建仓资金水平线)
- daily_gains_p3.png    累计净值(8 条, 建仓日=1.0) + 每日涨幅%(8 条+20日MA) 双面板

用法: python scripts/p3/plot_daily_gains_p3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import os

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parent.parent.parent / ".mplconfig")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from quant_trading_01.config import get_config  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Hiragino Sans GB",
    "Arial Unicode MS",
    "Heiti SC",
    "SimHei",
    "STHeiti",
]
plt.rcParams["axes.unicode_minus"] = False

COLORS = [
    "#c0392b",
    "#e67e22",
    "#2980b9",
    "#27ae60",
    "#8e44ad",
    "#16a085",
    "#f39c12",
    "#2c3e50",
]


def _out() -> Path:
    return Path(get_config().p3.out_dir)


def _load_dfs() -> list[tuple[str, int, pd.DataFrame]]:
    out = _out()
    dfs = []
    for aum in get_config().p3.aum_list:
        tag = f"{int(aum / 1e4)}w"
        p = out / f"daily_nav_p3_aum{tag}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, parse_dates=["date"])
        df["涨幅%"] = df["涨幅%"].fillna(0.0)
        dfs.append((f"{int(aum / 1e4)}万", int(aum), df))
    return dfs


def plot() -> list[Path]:
    out = _out()
    dfs = _load_dfs()
    if not dfs:
        print(f"P3 无 daily_nav_p3_aum*.csv（先跑 paper_live_p3.py mark）: {out}")
        return []
    outs: list[Path] = []

    # 1) 每账户 NAV 单图(对齐 R5 plot_daily_gains: 每账户一张 daily_nav_p3_aum{tag}.png)
    for i, (name, aum, df) in enumerate(dfs):
        c = COLORS[i]
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(df["date"], df["nav"], color=c, lw=1.6, marker="o", markersize=4)
        ax.axhline(aum, color="gray", ls="--", lw=1.2, alpha=0.8)
        ax.text(
            df["date"].iloc[-1],
            aum,
            f"  建仓资金 {aum:,.0f} 元",
            va="bottom",
            ha="left",
            fontsize=9,
            color="dimgray",
        )
        for x, y in zip(df["date"], df["nav"]):
            ax.annotate(
                f"{y:,.0f}",
                (x, y),
                textcoords="offset points",
                xytext=(0, 9),
                ha="center",
                fontsize=8,
                color=c,
            )
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.set_title(f"P3 {name} · 每日 NAV（元）", fontsize=13)
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        tag = f"{int(aum / 1e4)}w"
        nav_out = out / f"daily_nav_p3_aum{tag}.png"
        fig.savefig(nav_out, dpi=130)
        plt.close(fig)
        outs.append(nav_out)
        print(f"已输出: {nav_out}")

    # 2) 累计净值 + 每日涨幅% 双面板
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(15, 10), sharex=True, gridspec_kw={"height_ratios": [1, 1.2]}
    )
    for i, (name, aum, df) in enumerate(dfs):
        c = COLORS[i]
        ax1.plot(df["date"], df["nav"] / df["nav"].iloc[0], label=name, color=c, lw=1.3)
        ax2.plot(df["date"], df["涨幅%"], color=c, lw=0.6, alpha=0.5)
        ax2.plot(
            df["date"], df["涨幅%"].rolling(20).mean(), color=c, lw=1.4, label=name
        )
    ax1.set_title("P3 八账户累计净值（建仓日=1.0）", fontsize=13)
    ax1.legend(loc="upper left", fontsize=9, ncol=4)
    ax1.grid(alpha=0.3)
    ax2.set_title("每日涨幅 %（细线=当日，粗线=20日MA）", fontsize=13)
    ax2.axhline(0, color="gray", lw=0.8)
    ax2.legend(loc="upper left", fontsize=9, ncol=4)
    ax2.grid(alpha=0.3)
    ax2.set_xlabel("日期")
    fig.tight_layout()
    gains_out = out / "daily_gains_p3.png"
    fig.savefig(gains_out, dpi=130)
    plt.close(fig)
    outs.append(gains_out)
    print(f"已输出: {gains_out}")
    return outs


if __name__ == "__main__":
    plot()
