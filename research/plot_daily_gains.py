#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""绘制四账户每日涨幅图（年度场景 或 建仓以来实时场景）。

- 年度: 读 output/daily_nav_{PREFIX}_aum*.csv → 输出 output/daily_gains_{PREFIX}.png
- 实时: --live 读 output/daily_nav_aum*.csv(建仓以来, 无前缀) → 输出 output/daily_gains_live.png
上: 累计净值(建仓日=1.0); 下: 每日涨幅% (细线=当日, 粗线=20日MA)。
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

AUM_TAG = [("60w", "60万"), ("100w", "100万"), ("300w", "300万"), ("600w", "600万")]
COLORS = ["#c0392b", "#e67e22", "#2980b9", "#27ae60"]


def _draw(csv_tpl: str, title: str, out: Path) -> Path:
    """读四账户 CSV（模板含 {tag}）→ 画双面板图 → 返回输出路径。"""
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [1, 1.6]}
    )
    for (tag, name), col in zip(AUM_TAG, COLORS):
        df = pd.read_csv(OUT / csv_tpl.format(tag=tag), parse_dates=["date"])
        df["涨幅%"] = df["涨幅%"].fillna(0.0)
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
    return out


def plot_live(title: str = "建仓以来（2026-09-01 起）") -> Path:
    """建仓以来实时场景：读无前缀 daily_nav_aum*.csv → daily_gains_live.png。"""
    return _draw("daily_nav_aum{tag}.csv", title, OUT / "daily_gains_live.png")


def main() -> None:
    ap = argparse.ArgumentParser(description="四账户每日涨幅图")
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
    )


if __name__ == "__main__":
    main()
