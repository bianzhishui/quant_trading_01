#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""绘制四账户每日图（年度场景 或 建仓以来实时场景）。

每次调用输出 5 个文件：
- 每日 NAV（元）: 每账户单独一张 → output/daily_nav_aum{60w,100w,300w,600w}.png
  （年度场景 → output/daily_nav_{PREFIX}_aum{tag}.png）
  每张图: 数据点标注每日 NAV 值 + 灰色虚线标注建仓资金水平线
- 累计净值 + 每日涨幅%: 四账户合并一张双面板图 → output/daily_gains_live.png
  （年度场景 → output/daily_gains_{PREFIX}.png）

用法: python research/plot_daily_gains.py [--prefix 20250101] [--title '2025全年']
      python research/plot_daily_gains.py --live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import OUT

plt.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Hiragino Sans GB",
    "Arial Unicode MS",
    "Heiti SC",
    "SimHei",
    "STHeiti",
]
plt.rcParams["axes.unicode_minus"] = False

# (tag, 显示名, 建仓本金)
AUM_LIST = [
    ("60w", "60万", 600_000),
    ("100w", "100万", 1_000_000),
    ("300w", "300万", 3_000_000),
    ("600w", "600万", 6_000_000),
]
COLORS = ["#c0392b", "#e67e22", "#2980b9", "#27ae60"]


def _plot_nav_single(
    name: str, col: str, df: pd.DataFrame, nav_out: Path, initial_aum: float
) -> None:
    """单账户每日 NAV（元）独立图：标注每日值 + 建仓资金水平线。"""
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(df["date"], df["nav"], color=col, lw=1.6, marker="o", markersize=4)
    # 建仓资金水平线
    ax.axhline(initial_aum, color="gray", ls="--", lw=1.2, alpha=0.8)
    ax.text(
        df["date"].iloc[-1],
        initial_aum,
        f"  建仓资金 {initial_aum:,.0f} 元",
        va="bottom",
        ha="left",
        fontsize=9,
        color="dimgray",
    )
    # 每日值标注
    for x, y in zip(df["date"], df["nav"]):
        ax.annotate(
            f"{y:,.0f}",
            (x, y),
            textcoords="offset points",
            xytext=(0, 9),
            ha="center",
            fontsize=8,
            color=col,
        )
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.set_title(f"{name} · 每日 NAV（元）", fontsize=13)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(nav_out, dpi=130)
    plt.close(fig)
    print(f"已输出: {nav_out}")


def _plot_norm_ret(
    dfs: list[tuple[str, str, pd.DataFrame]],
    title: str,
    out: Path,
) -> None:
    """四账户合并双面板图：上=累计净值(建仓日=1.0)，下=每日涨幅%(细线)+20日MA(粗线)。"""
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [1, 1.2]}
    )
    for name, col, df in dfs:
        nav_norm = df["nav"] / df["nav"].iloc[0]
        ax1.plot(df["date"], nav_norm, label=name, color=col, lw=1.4)
        ax2.plot(df["date"], df["涨幅%"], label=name, color=col, lw=0.7, alpha=0.55)
        ma = df["涨幅%"].rolling(20).mean()
        ax2.plot(df["date"], ma, color=col, lw=1.5, alpha=0.95)
    ax1.set_title(f"{title} · 四账户累计净值（建仓日=1.0）", fontsize=13)
    ax1.legend(loc="upper left", fontsize=10)
    ax1.grid(alpha=0.3)
    ax2.set_title("每日涨幅 %（细线=当日涨幅，粗线=20日滚动均线）", fontsize=13)
    ax2.axhline(0, color="gray", lw=0.8)
    ax2.legend(loc="upper left", fontsize=10, ncol=4)
    ax2.grid(alpha=0.3)
    ax2.set_xlabel("日期")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"已输出: {out}")


def _draw(
    csv_tpl: str,
    title: str,
    norm_ret_out: Path,
    nav_tpl: str,
) -> list[Path]:
    """读四账户 CSV → 每账户 NAV 单图(nav_tpl 含 {tag}) + 累计净值/涨幅% 双面板(norm_ret_out)。"""
    dfs: list[tuple[str, str, pd.DataFrame]] = []
    for (tag, name, aum), col in zip(AUM_LIST, COLORS):
        df = pd.read_csv(OUT / csv_tpl.format(tag=tag), parse_dates=["date"])
        df["涨幅%"] = df["涨幅%"].fillna(0.0)
        dfs.append((name, col, df))
        _plot_nav_single(name, col, df, OUT / nav_tpl.format(tag=tag), aum)
    _plot_norm_ret(dfs, title, norm_ret_out)
    return [OUT / nav_tpl.format(tag=tag) for tag, _, _ in AUM_LIST] + [norm_ret_out]


def plot_live(title: str = "建仓以来（2026-09-01 起）") -> list[Path]:
    """建仓以来实时场景：读无前缀 daily_nav_aum*.csv。"""
    return _draw(
        "daily_nav_aum{tag}.csv",
        title,
        OUT / "daily_gains_live.png",
        "daily_nav_aum{tag}.png",
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="四账户每日图（NAV单图×4 + 累计净值/涨幅%双面板）"
    )
    ap.add_argument(
        "--live", action="store_true", help="读建仓以来无前缀文件 daily_nav_aum*.csv"
    )
    ap.add_argument("--prefix", default="20250101")
    ap.add_argument("--title", default="2025全年")
    args = ap.parse_args()
    if args.live:
        plot_live()
        return
    _draw(
        f"daily_nav_{args.prefix}_aum{{tag}}.csv",
        args.title,
        OUT / f"daily_gains_{args.prefix}.png",
        f"daily_nav_{args.prefix}_aum{{tag}}.png",
    )


if __name__ == "__main__":
    main()
