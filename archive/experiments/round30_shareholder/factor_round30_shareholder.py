#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 30 股东户数变化/筹码集中度因子筛选（预注册）。

因子 = 月末 T 取该股最近已公告(公告日≤T)的股东户数增减比例(环比%), 方向-1(户数降=筹码集中=看多)。
数据: data/round2/shareholder_count.parquet (akshare 54报告期 206k行 2013-2026)。
框架沿用四层判定 + 与 Amihud/动量 相关矩阵。

用法: python research/factor_round30_shareholder.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days  # noqa: E402
from research.paper_trade import _load, metrics  # noqa: E402
from research.reversal_factor import ERAS, N_Q, build_pool, ew_nav  # noqa: E402
from scipy import stats as sps  # noqa: E402

COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
MIN_N = 50
SH_FILE = Path("data/round2/shareholder_count.parquet")
MATRIX_MEMBERS = ["股东户数", "Amihud", "中期动量"]


def build_holder_factor(close: pd.DataFrame) -> pd.DataFrame:
    """股东户数增减比例宽表(date×code): 最近已公告环比%, ffill。"""
    ann = pd.read_parquet(SH_FILE)
    ann["公告日期"] = pd.to_datetime(ann["公告日期"])
    ann["code6"] = ann["代码"].astype(str).str.zfill(6)
    ann["code_full"] = np.where(
        ann["code6"].str.startswith(("60", "68")),
        "sh." + ann["code6"],
        "sz." + ann["code6"],
    )
    ann = ann[["code_full", "公告日期", "股东户数-增减比例"]].dropna(
        subset=["股东户数-增减比例"]
    )
    fac = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    for code in close.columns:
        sub = ann[ann["code_full"] == code].sort_values("公告日期")
        if sub.empty:
            continue
        s = sub.set_index("公告日期")["股东户数-增减比例"]
        s = s[~s.index.duplicated(keep="last")].sort_index()
        fac[code] = s.reindex(close.index, method="ffill")
    return fac


def main() -> None:
    print("== Round 30 股东户数/筹码集中度因子 (预注册 v1.0) ==")
    close, amount, tst, isst, ind = _load()
    print(
        f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
        f"{close.index[0].date()} ~ {close.index[-1].date()}"
    )
    pool = build_pool(close, tst, isst)
    ret_qfq = close.pct_change()
    holder = build_holder_factor(close)
    amihud = ((ret_qfq.abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    mom = close.shift(21) / close.shift(250) - 1.0
    factors = {"股东户数": holder, "Amihud": amihud, "中期动量": mom}

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]

    q_sets = {name: [dict() for _ in range(N_Q)] for name in MATRIX_MEMBERS}
    bench_sets: dict = {}
    ics = {name: [] for name in MATRIX_MEMBERS}
    ic_dates = {name: [] for name in MATRIX_MEMBERS}
    n_eff = {name: 0 for name in MATRIX_MEMBERS}
    corr_sum = {m: {n: 0.0 for n in MATRIX_MEMBERS} for m in MATRIX_MEMBERS}
    corr_cnt = {m: {n: 0 for n in MATRIX_MEMBERS} for m in MATRIX_MEMBERS}

    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        vals = {}
        for name in MATRIX_MEMBERS:
            fv = factors[name].loc[T][e].dropna()
            if len(fv) < MIN_N:
                continue
            vals[name] = fv
        if not vals:
            continue
        for name in MATRIX_MEMBERS:
            if name not in vals:
                continue
            fv = vals[name]
            rk = fv.rank(method="first")
            q = pd.qcut(rk, N_Q, labels=False)
            for g in range(N_Q):
                q_sets[name][g][exec_day] = set(fv.index[q == g])
            bench_sets[exec_day] = set(fv.index)
            n_eff[name] += 1
            if k + 1 < len(sig_days):
                T2 = sig_days[k + 1]
                fwd = close.loc[T2] / close.loc[T] - 1.0
                m = fv.index.intersection(fwd.dropna().index)
                if len(m) >= MIN_N:
                    ics[name].append(sps.spearmanr(fv[m], fwd[m])[0])
                    ic_dates[name].append(T)
        names_present = [n for n in MATRIX_MEMBERS if n in vals]
        for a in names_present:
            for b in names_present:
                both = vals[a].index.intersection(vals[b].index)
                if len(both) >= MIN_N:
                    corr_sum[a][b] += sps.spearmanr(vals[a][both], vals[b][both])[0]
                    corr_cnt[a][b] += 1

    corr_cs = (
        pd.DataFrame(corr_sum)
        .div(pd.DataFrame(corr_cnt).replace(0, np.nan))
        .fillna(0.0)
    )
    ic_df = pd.DataFrame(
        {n: pd.Series(ics[n], index=ic_dates[n]) for n in MATRIX_MEMBERS}
    ).sort_index()

    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    n_periods = len(bench_sets)
    print(f"\n调仓期数 {len(bench_sets)}, 基准(同池等权)年化 {ann_bench:+.1%}")

    name = "股东户数"
    eff_ratio = n_eff[name] / n_periods
    if eff_ratio < 0.6:
        print(
            f"\n■ {name}: 数据不足 {n_eff[name]}/{n_periods} (有效截面 {eff_ratio:.0%})"
        )
        return
    g_navs = [ew_nav(ret_qfq, q_sets[name][g], COST)[0] for g in range(N_Q)]
    anns = [metrics(v)["年化"] for v in g_navs]
    li = 0  # direction -1: 多头=Q1(户数降幅最大)
    si = N_Q - 1
    long_nav, turn = ew_nav(ret_qfq, q_sets[name][li], COST)
    long25, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[0])
    long35, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[1])
    ic = ic_df[name].dropna()
    ic_mean = ic.mean()
    ic_t = ic.mean() / ic.std() * np.sqrt(len(ic)) if len(ic) > 1 else np.nan
    era_exc = {}
    for era, (s, e_) in ERAS.items():
        a, b = long_nav[s:e_], nav_bench[s:e_]
        era_exc[era] = (
            metrics(a / a.dropna().iloc[0])["年化"]
            - metrics(b / b.dropna().iloc[0])["年化"]
        )
    c1 = ic_mean < 0 and abs(ic_mean) >= 0.03 and abs(ic_t) >= 2  # 方向-1: IC 应为负
    c2 = (anns[li] == max(anns)) and (anns[si] == min(anns))
    c3 = metrics(long_nav)["年化"] - ann_bench >= 0.01
    c4 = sum(v > 0 for v in era_exc.values()) >= 2
    n_pass = sum([c1, c2, c3, c4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")

    print(f"\n■ {name} (方向低好: 户数降=看多) 判定: {verdict} ({n_pass}/4)")
    print(
        "  分组年化: "
        + " ".join(
            f"Q{g + 1}{'*' if g == li else ''}:{anns[g]:+.1%}" for g in range(N_Q)
        )
    )
    print(
        f"  IC {ic_mean:+.4f}(t={ic_t:+.2f}, n={len(ic)}) | 超额 15bp:{metrics(long_nav)['年化'] - ann_bench:+.1%} "
        f"25bp:{metrics(long25)['年化'] - ann_bench:+.1%} 35bp:{metrics(long35)['年化'] - ann_bench:+.1%} "
        f"| 换手 {turn:.1f} | 回撤 {metrics(long_nav)['最大回撤']:.1%}"
    )
    print("  分段超额: " + " ".join(f"{e}:{v:+.1%}" for e, v in era_exc.items()))

    print("\n== 因子值截面相关(月均 Spearman) ==")
    print(corr_cs.loc[MATRIX_MEMBERS, MATRIX_MEMBERS].round(3).to_string())
    print("\n== IC 序列相关 ==")
    print(ic_df.corr().loc[MATRIX_MEMBERS, MATRIX_MEMBERS].round(3).to_string())
    print(f"\n结论: {verdict} —— 若通过, 下一步组合验证(能否并入R5, Round22方法)")


if __name__ == "__main__":
    main()
