#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P3 池子质量监控 —— 低价池(真实价3-4元)的"扣非为正通过率"历史趋势(R46 归因: 池子劣化)。

口径与 P3 选股完全一致(防前视):
- 池: 每个月末 T 真实价 ∈ [3.0, 4.0) 的股票
- 通过率: 池内"近3个可见年报(报告期+120天<=T)扣非均为正"的比例
- 池规模: 池内股票数

输出:
- output/p3/pool_quality_trend.png   通过率曲线 + 池规模柱状(双轴)
- output/p3/pool_quality_trend.csv   逐月末 date/pool_n/pass_rate
- 终端: 分段均值(2014-17/2018-21/2022-26) + 最新

用法: .venv/bin/python scripts/p3/pool_quality.py
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
from quant_trading_01.config import load_config  # noqa: E402
from quant_trading_01.dividend_factor import month_last_days  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Hiragino Sans GB",
    "Arial Unicode MS",
    "Heiti SC",
    "SimHei",
    "STHeiti",
]
plt.rcParams["axes.unicode_minus"] = False


def compute() -> pd.DataFrame:
    from scripts.factor_round41_low_price import load_data

    data = load_data()
    real, ded = data["real"], data["ded"]
    rows = []
    for T in month_last_days(real.index):
        real_T = real.loc[T]
        pool = real_T.between(3.0, 4.0, inclusive="left")
        codes = list(pool[pool].index)
        vis = ded.index[ded.index + pd.Timedelta(days=120) <= T]
        if len(vis) < 3 or not codes:
            continue
        last3 = ded.loc[vis[-3:], codes]
        rate = float((last3 > 0).all(axis=0).mean())
        rows.append({"date": T, "pool_n": len(codes), "pass_rate": rate})
    return pd.DataFrame(rows)


def plot(df: pd.DataFrame, out_dir: Path) -> Path:
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax1.plot(
        df["date"],
        df["pass_rate"] * 100,
        color="#c0392b",
        lw=1.6,
        label="扣非为正通过率%",
    )
    ax1.axhline(35, color="#c0392b", ls="--", lw=1.0, alpha=0.5)
    ax1.set_ylabel("通过率 %", color="#c0392b")
    ax1.set_ylim(0, 100)
    ax2 = ax1.twinx()
    ax2.bar(
        df["date"],
        df["pool_n"],
        color="#95a5a6",
        alpha=0.35,
        width=25,
        label="低价池规模",
    )
    ax2.set_ylabel("池规模(只)", color="#7f8c8d")
    ax1.set_title("P3 低价池质量趋势(真实价3-4元 · 近3年扣非为正通过率)", fontsize=13)
    ax1.grid(alpha=0.3)
    fig.legend(loc="upper left", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    out = out_dir / "pool_quality_trend.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main() -> None:
    load_config(None)
    df = compute()
    if df.empty:
        print("无数据")
        return
    out_dir = Path("output/p3")
    out_dir.mkdir(parents=True, exist_ok=True)
    # CSV
    csv = out_dir / "pool_quality_trend.csv"
    df.assign(pass_rate=df["pass_rate"].round(4)).to_csv(csv, index=False)
    # 图
    png = plot(df, out_dir)

    # 分段均值
    def seg(a, b):
        m = df[(df["date"] >= a) & (df["date"] <= b)]
        return m["pass_rate"].mean() * 100 if len(m) else float("nan")

    print(f"已输出: {png} / {csv}")
    print(
        f"  低价池质量分段均值(通过率%): 2014-17 {seg('2014-01-01', '2017-12-31'):.1f} | "
        f"2018-21 {seg('2018-01-01', '2021-12-31'):.1f} | 2022-26 {seg('2022-01-01', '2099-12-31'):.1f}"
    )
    print(
        f"  最新({df['date'].iloc[-1].date()}): 池 {df['pool_n'].iloc[-1]} 只, 通过率 {df['pass_rate'].iloc[-1]:.0%}"
    )


if __name__ == "__main__":
    main()
