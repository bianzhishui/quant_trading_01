#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 7 幸存者偏差验证 —— 扩池重跑 R5（全市场，去指数成分幸存者偏差）。

数据：data/fundamental/full_daily.parquet（全市场主连+中小板，baostock qfq 同口径）
     + data/round2/industry_full.parquet（全市场行业，需先抓取）
对照：800 池 R5（+5.7pp） vs 全市场 R5。回答：
  ① 超额是真实还是幸存者偏差造出来的？ ② Amihud+动量在更广池子上还成立吗？
代码：research/factor_round7_fullmarket_validate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research.data_io import load_full_daily  # noqa: E402

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days, metrics
from research.reversal_factor import ERAS, build_pool, ew_nav

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
COST = 15e-4
COST_SWEEP = [35e-4]
MIN_N = 50
MIN_IND = 5
START = "2013-06-01"


def load_full() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """全市场: 返回 (close, amount, tst, isst) 宽表, 2013-06 起。"""
    d = load_full_daily()
    d["date"] = pd.to_datetime(d["date"])

    def _pivot(col: str) -> pd.DataFrame:
        x = d.pivot(index="date", columns="code", values=col).sort_index()
        return x.loc[START:]

    return _pivot("close"), _pivot("amount"), _pivot("tradestatus"), _pivot("isST")


def main() -> None:
    print("== Round 7 幸存者偏差验证 (扩池重跑 R5) ==")
    close, amount, tst, isst = load_full()
    ret_qfq = close.pct_change()
    pool = build_pool(close, tst, isst)
    print(
        f"全市场数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
        f"{close.index[0].date()} ~ {close.index[-1].date()}"
    )

    ind = pd.read_parquet(R2 / "industry_full.parquet").set_index("code")["industry"]
    ind = ind.reindex(close.columns).dropna()
    print(f"行业映射覆盖: {len(ind)}/{close.shape[1]} 只")

    amihud = (
        ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    )
    mom = close.shift(21) / close.shift(250) - 1.0

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    sets_R5: dict = {}
    bench_sets: dict = {}
    coverage = []
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        common = a.index.intersection(m.index).intersection(ind.index)
        ind_s = ind.reindex(common)
        keep = ind_s.value_counts()[ind_s.value_counts() >= MIN_IND].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < MIN_N:
            continue
        if k + 1 < len(sig_days):
            bench_sets[exec_day] = set(codes)
        coverage.append(len(codes))
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = (pa + pm) / 2
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        sets_R5[exec_day] = set(codes[q == 4])

    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    long_nav, turn = ew_nav(ret_qfq, sets_R5, COST)
    long35, _ = ew_nav(ret_qfq, sets_R5, COST_SWEEP[0])
    era_exc = {}
    for era, (s, e_) in ERAS.items():
        a, b = long_nav[s:e_], nav_bench[s:e_]
        era_exc[era] = (
            metrics(a / a.dropna().iloc[0])["年化"]
            - metrics(b / b.dropna().iloc[0])["年化"]
        )
    m = metrics(long_nav)
    dd = (long_nav / long_nav.cummax() - 1).min()
    print(
        f"\n调仓期数 {len(bench_sets)}, 全市场中性化池月均 {np.mean(coverage):.0f} 只, "
        f"基准年化 {ann_bench:+.1%}"
    )
    print(
        f"\n■ 全市场 R5: 超额15bp {m['年化'] - ann_bench:+.1%} | "
        f"35bp {metrics(long35)['年化'] - ann_bench:+.1%} | 换手 {turn:.1f} | "
        f"夏普 {m['夏普']:.2f} | 回撤 {dd:.1%}"
    )
    print("   分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items()))
    print("\n对照 800 池 R5: 超额 +5.7% | 夏普 0.80 | 换手 3.4 | 回撤 -51.8%")
    print("  分段: +2.2/+10.7/+5.7")

    pd.DataFrame(
        {
            "指标": ["超额15bp", "超额35bp", "夏普", "换手", "回撤"],
            "800池R5": [0.057, 0.041, 0.80, 3.4, -0.518],
            "全市场R5": [
                round(m["年化"] - ann_bench, 4),
                round(metrics(long35)["年化"] - ann_bench, 4),
                round(m["夏普"], 2),
                round(turn, 1),
                round(float(dd), 3),
            ],
        }
    ).to_csv(OUT / "factor_round7_summary.csv", index=False)
    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(long_nav, lw=1.4, label="全市场 R5")
    ax.plot(nav_bench, lw=1, alpha=0.6, color="gray", label="全市场同池等权基准")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_title("Round 7 全市场 R5 (对数净值, 15bp)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round7.png", dpi=130)
    print("\nCSV: output/factor_round7_summary.csv | 图: output/factor_round7.png")


if __name__ == "__main__":
    main()
