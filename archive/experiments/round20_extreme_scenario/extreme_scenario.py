#!/usr/bin/env python3
"""Round 20 极端行情回放演练: 四账户从历史极端起点建仓, 量化回撤/恢复路径。

纯回放研究(不动 R5/运营账户), 复用 scenario_ytd.run_scenario(导入直调)。
预注册方案: docs/factor_round20_extreme_scenario_plan.md

用法: python research/extreme_scenario.py

输出:
  output/extreme_scenario_summary.csv  场景×账户 回撤/恢复统计
  output/extreme_S1_2015.png ... S4    每场景一张图(净值+回撤)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import OUT  # noqa: E402
from research.scenario_ytd import run_scenario  # noqa: E402

# (场景名, 区间起点, 区间终点, 标题)
SCENARIOS = [
    ("S1_2015", "2015-06-01", "2016-06-30", "S1 股灾+熔断(2015-06 高点建仓 → 2016-06)"),
    ("S2_2018", "2018-01-01", "2018-12-31", "S2 全年熊市(2018)"),
    ("S3_2024", "2024-01-01", "2024-06-30", "S3 微盘危机(2024-02 崩盘 → 反弹)"),
    ("S4_2022", "2022-01-01", "2022-12-31", "S4 熊市(2022)"),
]
TAGS = ["aum60w", "aum100w", "aum300w", "aum600w"]
NAMES = {"aum60w": "60万", "aum100w": "100万", "aum300w": "300万", "aum600w": "600万"}
COLORS = {
    "aum60w": "#c0392b",
    "aum100w": "#e67e22",
    "aum300w": "#2980b9",
    "aum600w": "#27ae60",
}
HS300_FILE = Path("data/idx000300_daily_20130601_20260904.csv")


def load_hs300(start: str, end: str) -> pd.Series:
    df = pd.read_csv(HS300_FILE, parse_dates=["date"]).set_index("date")["close"]
    return df.loc[pd.Timestamp(start) : pd.Timestamp(end)]


def dd_stats(nav: pd.Series) -> dict:
    """区间内最大回撤/谷底日期/峰值→谷底交易日/恢复交易日/区间累计。"""
    peak = nav.cummax()
    dd = nav / peak - 1
    trough_i = dd.idxmin()
    trough = dd.min()
    peak_date = nav.loc[:trough_i].idxmax()
    i_trough = nav.index.get_loc(trough_i)
    i_peak = nav.index.get_loc(peak_date)
    after = nav.loc[trough_i:]
    rec = after[after >= nav.loc[peak_date]]
    rec_days = None
    if len(rec):
        rec_days = nav.index.get_loc(rec.index[0]) - i_trough
    end_ret = nav.iloc[-1] / nav.iloc[0] - 1
    return {
        "最大回撤": trough,
        "谷底日期": str(trough_i.date()),
        "峰值→谷底(交易日)": i_trough - i_peak,
        "恢复(交易日)": rec_days if rec_days is not None else "未恢复",
        "区间累计": end_ret,
    }


def main() -> None:
    rows = []
    for sid, start, end, title in SCENARIOS:
        print(f"== {title} ==", flush=True)
        navs = run_scenario(start, end, verbose=False)
        hs = load_hs300(start, end)
        for tag in TAGS:
            st = dd_stats(navs[tag])
            st.update({"场景": sid, "区间": f"{start}~{end}", "标的": NAMES[tag]})
            rows.append(st)
        st = dd_stats(hs)
        st.update({"场景": sid, "区间": f"{start}~{end}", "标的": "沪深300"})
        rows.append(st)
        _plot(sid, title, navs, hs)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "extreme_scenario_summary.csv", index=False)
    pd.set_option("display.width", 160)
    print("\n========== 极端行情回放演练汇总 ==========")
    print(df.to_string(index=False))


def _plot(sid: str, title: str, navs: dict, hs: pd.Series) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "PingFang SC",
        "Hiragino Sans GB",
        "Arial Unicode MS",
        "Heiti SC",
        "SimHei",
        "STHeiti",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    for tag in TAGS:
        nav = navs[tag]
        norm = nav / nav.iloc[0]
        ax1.plot(nav.index, norm, label=NAMES[tag], color=COLORS[tag], lw=1.3)
        dd = nav / nav.cummax() - 1
        ax2.plot(nav.index, dd * 100, color=COLORS[tag], lw=1.1, label=NAMES[tag])
        trough_i = dd.idxmin()
        ax2.scatter([trough_i], [dd.min() * 100], color=COLORS[tag], s=40, zorder=5)
    hs_n = hs / hs.iloc[0]
    ax1.plot(hs.index, hs_n, color="black", lw=1.0, ls="--", alpha=0.7, label="沪深300")
    ax1.axhline(1.0, color="gray", lw=0.6, ls=":")
    ax1.set_ylabel("净值(区间起点=1.0)")
    ax1.legend(loc="lower left", fontsize=9, ncol=3)
    ax1.grid(alpha=0.3)
    ax2.axhline(0, color="gray", lw=0.6)
    ax2.set_ylabel("回撤 %")
    ax2.set_xlabel("日期")
    ax2.grid(alpha=0.3)
    fig.suptitle(f"极端行情回放演练 · {title}", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = OUT / f"extreme_{sid}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  图已输出: {out}")


if __name__ == "__main__":
    main()
