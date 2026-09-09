#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""绘制四账户每日图（年度场景 或 建仓以来实时场景）。

- 年度: 读 output/daily_nav_{PREFIX}_aum*.csv → 输出 output/daily_gains_{PREFIX}.png
- 实时: --live 读 output/daily_nav_aum*.csv(建仓以来, 无前缀) → 输出 output/daily_gains_live.png
布局: 4行×3列 — 行=账户(独立y轴尺度), 列=每日NAV(元)/累计净值(建仓日=1.0)/每日涨幅%(细线+20日MA粗线)。
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
    """读四账户 CSV（模板含 {tag}）→ 画 4行×3列 分账户图 → 返回输出路径。

    行=账户(60万/100万/300万/600万)，每行独立 y 轴尺度；
    列=每日NAV(元) / 累计净值(建仓日=1.0) / 每日涨幅%(细线)+20日MA(粗线)。
    """
    fig, axes = plt.subplots(
        4,
        3,
        figsize=(16, 16),
        sharex=True,
        gridspec_kw={"hspace": 0.35, "wspace": 0.28},
    )
    col_titles = [
        "每日 NAV（元）",
        "累计净值（建仓日=1.0）",
        "每日涨幅 %（细线=当日，粗线=20日MA）",
    ]
    for i, ((tag, name), col) in enumerate(zip(AUM_TAG, COLORS)):
        df = pd.read_csv(OUT / csv_tpl.format(tag=tag), parse_dates=["date"])
        df["涨幅%"] = df["涨幅%"].fillna(0.0)
        nav_norm = df["nav"] / df["nav"].iloc[0]
        ax_nav, ax_norm, ax_ret = axes[i]
        ax_nav.plot(df["date"], df["nav"], color=col, lw=1.6)
        ax_nav.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax_norm.plot(df["date"], nav_norm, color=col, lw=1.6)
        ax_ret.plot(df["date"], df["涨幅%"], color=col, lw=0.7, alpha=0.55)
        ma = df["涨幅%"].rolling(20).mean()
        ax_ret.plot(df["date"], ma, color=col, lw=1.6)
        ax_ret.axhline(0, color="gray", lw=0.8)
        for ax in (ax_nav, ax_norm, ax_ret):
            ax.grid(alpha=0.3)
        ax_nav.set_ylabel(name, fontsize=12, fontweight="bold")
        if i == 0:
            for ax, ct in zip((ax_nav, ax_norm, ax_ret), col_titles):
                ax.set_title(ct, fontsize=12)
    fig.suptitle(f"{title} · 四账户每日图（分账户独立尺度）", fontsize=14)
    for ax in axes[-1]:
        ax.set_xlabel("日期")
    fig.tight_layout(rect=(0, 0, 1, 0.98))
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
