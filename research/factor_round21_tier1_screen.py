#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 21 梯队一因子批量筛选（预注册）：低β/价格水平/长期反转/下行波动。

框架沿用 Round 1/2（四层判定 + ERAS 三段 + 同池等权基准 15bp），横向可比。
池 = 全市场（与 R5 一致, build_pool）。附加: 与 Amihud/中期动量 截面相关矩阵。

用法: python research/factor_round21_tier1_screen.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days  # noqa: E402
from research.paper_trade import _load, _load_corp, metrics  # noqa: E402
from research.reversal_factor import ERAS, N_Q, build_pool, ew_nav  # noqa: E402

COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
MIN_N = 50

# 方向: +1=因子值高→看好(多头=Q5); -1=值低→看好(多头=Q1)
FACTORS: dict[str, tuple[int, int]] = {
    "低beta": (-1, MIN_N),
    "价格水平": (-1, MIN_N),
    "长期反转": (+1, MIN_N),
    "下行波动": (-1, MIN_N),
}
# 相关矩阵成员（4 新 + 2 现有）
MATRIX_MEMBERS = list(FACTORS) + ["Amihud", "中期动量"]


def build_factors(close: pd.DataFrame, raw: pd.DataFrame, amount: pd.DataFrame) -> dict:
    """返回 {因子名: 宽表(date×code)}。口径见 plan §2。"""
    ret = close.pct_change()
    f: dict[str, pd.DataFrame] = {}

    # 低 beta: 对全池等权收益的 250 日滚动 β(样本协方差/方差, min_periods=120)
    mkt = ret.mean(axis=1)
    rb = ret.rolling(250, min_periods=120).mean()
    mb = mkt.rolling(250, min_periods=120).mean()
    cov = ret.mul(mkt, axis=0).rolling(250, min_periods=120).mean() - rb.mul(mb, axis=0)
    var = (mkt**2).rolling(250, min_periods=120).mean() - mb**2
    f["低beta"] = cov.div(var, axis=0)

    # 价格水平: 真实价 = 前复权 ÷ 复权因子 (_load_corp 已算 raw)
    f["价格水平"] = raw

    # 长期反转: T-750 ~ T-250 累计收益(买长期输家)
    f["长期反转"] = close.shift(250) / close.shift(750) - 1.0

    # 下行波动: 21 日下行半方差
    f["下行波动"] = (ret.clip(upper=0.0) ** 2).rolling(21, min_periods=15).mean() ** 0.5

    # 矩阵成员: Amihud / 中期动量
    f["Amihud"] = ((ret.abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    f["中期动量"] = close.shift(21) / close.shift(250) - 1.0
    return f


def main() -> None:
    print("== Round 21 梯队一因子批量筛选 (预注册 v1.0): 4 因子 ==")
    close, amount, tst, isst, ind = _load()
    raw, _ = _load_corp(close)
    print(
        f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
        f"{close.index[0].date()} ~ {close.index[-1].date()}"
    )
    pool = build_pool(close, tst, isst)
    ret_qfq = close.pct_change()
    factors = build_factors(close, raw, amount)

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]

    # ---- 逐月: 各因子分组集合 + IC + 相关矩阵累积 ----
    q_sets = {name: [dict() for _ in range(N_Q)] for name in MATRIX_MEMBERS}
    bench_sets: dict = {}
    ics: dict[str, list] = {name: [] for name in MATRIX_MEMBERS}
    corr_sum = {m: {n: 0.0 for n in MATRIX_MEMBERS} for m in MATRIX_MEMBERS}
    corr_cnt = {m: {n: 0 for n in MATRIX_MEMBERS} for m in MATRIX_MEMBERS}
    n_eff = {name: 0 for name in MATRIX_MEMBERS}
    ic_dates: dict[str, list] = {name: [] for name in MATRIX_MEMBERS}

    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        # 各因子截面值（池内）
        vals: dict[str, pd.Series] = {}
        for name in MATRIX_MEMBERS:
            fv = factors[name].loc[T][e].dropna()
            if len(fv) < MIN_N:
                continue
            vals[name] = fv
        if not vals:
            continue
        # 分组 + IC + 相关（矩阵成员都参与）
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
            T2 = sig_days[k + 1] if k + 1 < len(sig_days) else None
            if T2 is None:
                continue
            fwd = close.loc[T2] / close.loc[T] - 1.0
            m = fv.index.intersection(fwd.dropna().index)
            if len(m) < MIN_N:
                continue
            from scipy import stats as sps

            ics[name].append(sps.spearmanr(fv[m], fwd[m])[0])
            ic_dates[name].append(T)
        # 截面相关（月均 Spearman, 池内交集）
        from scipy import stats as sps

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

    # ---- 回测 ----
    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    n_periods = len(bench_sets)
    print(f"\n调仓期数 {len(bench_sets)}, 基准(同池等权)年化 {ann_bench:+.1%}")

    rows: dict = {}
    for name, (direction, _min_n) in FACTORS.items():
        eff_ratio = n_eff[name] / n_periods
        if eff_ratio < 0.6:
            rows[name] = {"判定": f"数据不足({n_eff[name]}/{n_periods})"}
            print(
                f"\n■ {name}: 数据不足 {n_eff[name]}/{n_periods} (有效截面 {eff_ratio:.0%})"
            )
            continue
        g_navs = [ew_nav(ret_qfq, q_sets[name][g], COST)[0] for g in range(N_Q)]
        anns = [metrics(v)["年化"] for v in g_navs]
        li = N_Q - 1 if direction == +1 else 0
        si = N_Q - 1 - li
        long_nav, turn = ew_nav(ret_qfq, q_sets[name][li], COST)
        long25, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[0])
        long35, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[1])
        ic = ic_df[name].dropna()
        ic_mean = ic.mean()
        ic_t = ic.mean() / ic.std() * np.sqrt(len(ic)) if len(ic) > 1 else np.nan
        sign_ok = (ic_mean > 0) == (direction == +1)
        era_exc = {}
        for era, (s, e_) in ERAS.items():
            a, b = long_nav[s:e_], nav_bench[s:e_]
            era_exc[era] = (
                metrics(a / a.dropna().iloc[0])["年化"]
                - metrics(b / b.dropna().iloc[0])["年化"]
            )
        c1 = sign_ok and abs(ic_mean) >= 0.03 and abs(ic_t) >= 2
        c2 = (anns[li] == max(anns)) and (anns[si] == min(anns))
        c3 = metrics(long_nav)["年化"] - ann_bench >= 0.01
        c4 = sum(v > 0 for v in era_exc.values()) >= 2
        n_pass = sum([c1, c2, c3, c4])
        verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
        rows[name] = {
            "方向": direction,
            "IC均值": round(ic_mean, 4),
            "IC_t": round(ic_t, 2),
            "多头超额15bp": round(metrics(long_nav)["年化"] - ann_bench, 4),
            "多头超额25bp": round(metrics(long25)["年化"] - ann_bench, 4),
            "多头超额35bp": round(metrics(long35)["年化"] - ann_bench, 4),
            "年换手": round(turn, 1),
            "回撤": round(metrics(long_nav)["最大回撤"], 4),
            "①IC": c1,
            "②单调": c2,
            "③超额": c3,
            "④分段": c4,
            "判定": f"{verdict}({n_pass}/4)",
        }
        print(
            f"\n■ {name} (方向{'高好' if direction == +1 else '低好'}) 判定: {verdict}"
        )
        print(
            "  分组年化: "
            + " ".join(
                f"Q{g + 1}{'*' if g == li else ''}:{anns[g]:+.1%}" for g in range(N_Q)
            )
        )
        print(
            f"  IC {ic_mean:+.4f}(t={ic_t:+.2f}) | 超额 15bp:{rows[name]['多头超额15bp']:+.1%} "
            f"25bp:{rows[name]['多头超额25bp']:+.1%} 35bp:{rows[name]['多头超额35bp']:+.1%} "
            f"| 换手 {turn:.1f} | 回撤 {rows[name]['回撤']:.1%}"
        )
        print("  分段超额: " + " ".join(f"{e}:{v:+.1%}" for e, v in era_exc.items()))

    print("\n== 因子值截面相关(月均 Spearman) ==")
    print(corr_cs.loc[MATRIX_MEMBERS, MATRIX_MEMBERS].round(3).to_string())
    corr_ic = ic_df.corr()
    print("\n== IC 序列相关 ==")
    print(corr_ic.loc[MATRIX_MEMBERS, MATRIX_MEMBERS].round(3).to_string())
    print("\n== 判定汇总 ==")
    print(pd.DataFrame(rows).T.to_string())


if __name__ == "__main__":
    main()
