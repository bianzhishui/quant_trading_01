#!/usr/bin/env python3
"""R5 因子失效监控（Round 18）：RankIC 滚动监控 Amihud×中期动量 是否衰减。

只读数据，输出报告+状态灯，绝不自动改策略/调仓。
预注册方案: docs/factor_round18_factor_health_plan.md

用法:
  python research/factor_health.py            # 全量: 历史基准 + 运营期状态灯
  python research/factor_health.py --chart    # 额外画出 RankIC 时序 + μ±2σ 带

输出:
  output/factor_health_rankic.csv    每期(月末T) × 因子 × 口径 的 RankIC 时间序列
  output/factor_health_baseline.json 历史基准(μ/σ/胜率), 首次计算后固定不复算
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days  # noqa: E402
from research.paper_trade import MIN_IND, MIN_N, _load  # noqa: E402
from research.reversal_factor import build_pool  # noqa: E402

OUT = Path("output")
BASELINE_START = pd.Timestamp("2014-01-01")
BASELINE_END = pd.Timestamp("2026-08-31")
LIVE_START = pd.Timestamp("2026-09-01")
BASELINE_FILE = OUT / "factor_health_baseline.json"
CSV_FILE = OUT / "factor_health_rankic.csv"

# 监控因子×口径 (与 r5_rebalances 逐公式一致)
COLS = ["amihud_full", "amihud_ind", "mom_full", "mom_ind", "score"]


def compute_rankic_panel() -> pd.DataFrame:
    """逐月末 T 计算 RankIC 面板。

    口径(与 paper_trade.r5_rebalances 完全一致):
      Amihud = (|ret|/amount×1e6) 21日滚动(min_periods=15)
      动量   = close.shift(21)/close.shift(250)-1 (T-250~T-21)
      合成分 = 行业内 pct rank(Amihud) 与 pct rank(动量) 平均
      未来收益 = close[T2]/close[T]-1 (T2=下月信号日)
    全池口径用原始因子值; 行业内口径用行业内 pct rank 值。
    """
    close, amount, tst, isst, ind = _load()
    pool = build_pool(close, tst, isst)
    ret = close.pct_change()
    amihud = ((ret.abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    mom = close.shift(21) / close.shift(250) - 1.0
    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]

    rows: list[dict] = []
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        common = a.index.intersection(m.index).intersection(ind.index)
        ind_s = ind.reindex(common)
        keep = ind_s.value_counts()[ind_s.value_counts() >= MIN_IND].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < MIN_N:
            continue
        if k + 1 >= len(sig_days):
            continue  # 最后一期无未来收益
        T2 = sig_days[k + 1]
        fwd = close.loc[T2] / close.loc[T] - 1.0
        m2 = codes.intersection(fwd.dropna().index)
        if len(m2) < MIN_N:
            continue
        # 行业内 pct rank (与 R5 打分同口径)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = (pa + pm) / 2  # 合成分已是行业内口径, 无全池/行业内之分
        row = {"date": T.date().isoformat()}
        row["amihud_full"] = sps.spearmanr(a[m2], fwd[m2])[0]
        row["amihud_ind"] = sps.spearmanr(pa[m2], fwd[m2])[0]
        row["mom_full"] = sps.spearmanr(m[m2], fwd[m2])[0]
        row["mom_ind"] = sps.spearmanr(pm[m2], fwd[m2])[0]
        row["score"] = sps.spearmanr(sc[m2], fwd[m2])[0]
        rows.append(row)

    df = pd.DataFrame(rows).set_index("date")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def load_or_compute_baseline(df: pd.DataFrame) -> dict:
    """历史基准(2014-01~2026-08): μ/σ/胜率。存在则读, 否则计算并写入(固定不复算)。"""
    if BASELINE_FILE.exists():
        return json.loads(BASELINE_FILE.read_text())
    seg = df.loc[BASELINE_START:BASELINE_END]
    base: dict = {}
    for c in COLS:
        s = seg[c].dropna()
        base[c] = {
            "n": int(len(s)),
            "mu": float(s.mean()),
            "sigma": float(s.std(ddof=0)),
            "winrate": float((s > 0).mean()),
            "start": str(seg.index[0].date()),
            "end": str(seg.index[-1].date()),
        }
    BASELINE_FILE.write_text(json.dumps(base, ensure_ascii=False, indent=2))
    print(f"  历史基准已写入 {BASELINE_FILE} (不复算)")
    return base


def status_light(ic: pd.Series, base: dict) -> tuple[str, float | None, int | None]:
    """运营期状态灯: (灯, 12期滚动均值, 连续负期数)。样本<6期返回'样本不足'。"""
    if len(ic) < 6:
        return "样本不足", None, None
    mu, sigma = base["mu"], base["sigma"]
    roll = ic.iloc[-12:].mean()
    neg_streak = 0
    for v in ic.iloc[::-1]:
        if v < 0:
            neg_streak += 1
        else:
            break
    if (
        roll < mu - 2 * sigma
        or neg_streak >= 12
        or roll / (sigma / np.sqrt(len(ic.iloc[-12:]))) < 1.0
    ):
        return "🔴 失效预警", roll, neg_streak
    if roll < mu - sigma or neg_streak >= 6:
        return "🟡 警戒", roll, neg_streak
    return "🟢 正常", roll, neg_streak


def main() -> None:
    ap = argparse.ArgumentParser(description="R5 因子失效监控 (RankIC 滚动)")
    ap.add_argument("--chart", action="store_true", help="画出 RankIC 时序 + μ±2σ 带")
    args = ap.parse_args()

    print("== R5 因子失效监控 (Round 18) ==")
    df = compute_rankic_panel()
    print(f"  RankIC 期数: {len(df)} ({df.index[0].date()} ~ {df.index[-1].date()})")
    base = load_or_compute_baseline(df)

    # 历史复现检查 (Amihud 应显著为正, 动量弱正)
    seg = df.loc[BASELINE_START:BASELINE_END]
    print("\n-- 历史基准 (2014-01 ~ 2026-08) --")
    for c in COLS:
        s = seg[c].dropna()
        t = s.mean() / (s.std(ddof=0) / np.sqrt(len(s))) if len(s) > 1 else 0.0
        print(
            f"  {c:<11} μ={s.mean():+.3f} σ={s.std(ddof=0):.3f} "
            f"胜率={(s > 0).mean():.0%} t={t:+.1f} n={len(s)}"
        )

    print("\n-- 运营期状态灯 (2026-09 起, 行业内口径为主) --")
    live = df.loc[df.index >= LIVE_START]
    for c in COLS:
        ic = live[c].dropna()
        light, roll, streak = status_light(ic, base[c])
        detail = (
            f"  已积累 {len(ic)} 期"
            if light == "样本不足"
            else f"12期滚动={roll:+.3f} (基准μ={base[c]['mu']:+.3f}σ={base[c]['sigma']:.3f}) 连负={streak}期"
        )
        print(f"  {c:<11} {light} | {detail}")

    # 落盘 CSV (追加合并去重)
    if CSV_FILE.exists():
        old = pd.read_csv(CSV_FILE, parse_dates=["date"]).set_index("date")
        df = pd.concat([old, df])[
            ~pd.concat([old, df]).index.duplicated(keep="last")
        ].sort_index()
    df.to_csv(CSV_FILE)
    print(f"\n  RankIC 时序已写入: {CSV_FILE}")

    if args.chart:
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
        fig, axes = plt.subplots(5, 1, figsize=(13, 16), sharex=True)
        for ax, c in zip(axes, COLS):
            s = df[c].dropna()
            ax.plot(s.index, s, lw=0.9, label=c)
            mu, sig = base[c]["mu"], base[c]["sigma"]
            ax.axhline(mu, color="green", lw=0.8, ls="--", label=f"μ={mu:+.3f}")
            ax.axhline(mu - 2 * sig, color="red", lw=0.8, ls="--", label="μ-2σ")
            ax.axhline(mu + 2 * sig, color="red", lw=0.8, ls="--")
            ax.legend(loc="upper left", fontsize=8)
            ax.grid(alpha=0.3)
        fig.suptitle("R5 因子 RankIC 时序 (阴影=μ±2σ)", fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, 0.985))
        out = OUT / "factor_health_rankic.png"
        fig.savefig(out, dpi=120)
        plt.close(fig)
        print(f"  图已输出: {out}")


if __name__ == "__main__":
    main()
