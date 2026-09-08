#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 1 因子批量筛选 —— 严格按 docs/factor_screen_round1_plan.md v1.0 实施。

四因子(候选池梯队一): BP / 低波动 / 中期动量 / 距52周高点
每因子: 预注册方向 → 月度 RankIC + 五分组(扣15bp) + 分年代 → 四层判定
另产出: 因子值截面相关矩阵(月均 Spearman) + IC 序列相关矩阵
池/成本/分组口径与 reversal_factor.py 完全一致(直接复用其函数)。

用法: uv run python research/factor_screen_round1.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sps

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import load_all, month_last_days, metrics
from research.reversal_factor import ERAS, N_Q, build_pool, ew_nav

COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
OUT = Path(__file__).resolve().parent.parent / "output"

# 方向: +1 = 因子值高→看好(多头=Q5); -1 = 值低→看好(多头=Q1)  —— 预注册写死
FACTORS = {"BP": +1, "低波动": -1, "中期动量": +1, "距52周高点": +1}


def build_factors(close: pd.DataFrame, pb: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ret1 = close.pct_change()
    return {
        "BP": 1.0 / pb.where(pb > 0),
        "低波动": ret1.rolling(21, min_periods=15).std(),
        "中期动量": close.shift(21) / close.shift(250) - 1.0,
        "距52周高点": close / close.rolling(250, min_periods=200).max() - 1.0,
    }


def main() -> None:
    print("== Round 1 因子批量筛选 (预注册 v1.0): BP/低波动/中期动量/距52周高点 ==")
    close, real, pb, tst, isst, *_ = load_all()
    print(
        f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
        f"{close.index[0].date()} ~ {close.index[-1].date()}"
    )
    pool = build_pool(close, tst, isst)
    ret_qfq = close.pct_change()
    factors = build_factors(close, pb)

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]

    # ---- 逐月: 每因子分组集合 + IC; 基准集合; 截面相关累积 ----
    q_sets = {name: [dict() for _ in range(N_Q)] for name in FACTORS}
    bench_sets: dict = {}
    ics = {name: {} for name in FACTORS}
    corr_sum = pd.DataFrame(0.0, index=list(FACTORS), columns=list(FACTORS))
    corr_n = 0
    n_months = 0
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        T2 = sig_days[k + 1] if k + 1 < len(sig_days) else None
        exec_day = idx[idx.get_loc(T) + 1]
        fwd = (close.loc[T2] / close.loc[T] - 1.0) if T2 is not None else None

        # 截面相关矩阵(四因子共同有效截面)
        common = e.copy()
        for f in factors.values():
            common &= f.loc[T].notna()
        if common.sum() >= 50:
            sub = pd.DataFrame({name: f.loc[T][common] for name, f in factors.items()})
            corr_sum += sub.corr(method="spearman")
            corr_n += 1

        bench_codes = e[e].index
        if len(bench_codes) >= 50:
            bench_sets[exec_day] = set(bench_codes)
            n_months += 1
        for name, f in factors.items():
            fv = f.loc[T][e].dropna()
            if len(fv) < 50:
                continue
            rk = fv.rank(method="first")
            q = pd.qcut(rk, N_Q, labels=False)
            for g in range(N_Q):
                q_sets[name][g][exec_day] = set(fv.index[q == g])
            if fwd is not None:
                m = fv.index.intersection(fwd.dropna().index)
                if len(m) >= 50:
                    ics[name][T] = sps.spearmanr(fv[m], fwd[m])[0]

    corr_cs = corr_sum / corr_n
    ic_df = pd.DataFrame(ics).sort_index(axis=1)
    corr_ic = (
        ic_df.corr()
    )  # 因子×因子（月度IC序列相关；bug修复：此前误用 ic_df.T.corr()）

    # ---- 回测: 基准一次, 各因子五分组 + 多头 + 成本压测 ----
    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    rows, long_navs = {}, {}
    for name, direction in FACTORS.items():
        g_navs = [ew_nav(ret_qfq, q_sets[name][g], COST)[0] for g in range(N_Q)]
        anns = [metrics(v)["年化"] for v in g_navs]
        li = N_Q - 1 if direction == +1 else 0  # 多头组下标
        si = N_Q - 1 - li  # 空头组下标
        long_nav, turn = ew_nav(ret_qfq, q_sets[name][li], COST)
        long_navs[name] = long_nav
        long25, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[0])
        long35, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[1])
        ic = ic_df[name].dropna()
        ic_mean, ic_t = ic.mean(), ic.mean() / ic.std() * np.sqrt(len(ic))
        sign_ok = (ic_mean > 0) == (direction == +1)
        era_exc = {}
        for era, (s, e_) in ERAS.items():
            a = long_nav[s:e_]
            b = nav_bench[s:e_]
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
            "IC方向正确": sign_ok,
            "多头年化15bp": round(metrics(long_nav)["年化"], 4),
            "基准年化": round(ann_bench, 4),
            "超额15bp": round(metrics(long_nav)["年化"] - ann_bench, 4),
            "超额25bp": round(metrics(long25)["年化"] - ann_bench, 4),
            "超额35bp": round(metrics(long35)["年化"] - ann_bench, 4),
            "多头年换手": round(turn, 1),
            "空头年化": round(anns[si], 4),
            "多空毛(几何)": round(metrics(long_nav / g_navs[si])["年化"], 4),
            **{f"超额{era}": round(v, 4) for era, v in era_exc.items()},
            "①IC": c1,
            "②单调": c2,
            "③可交易": c3,
            "④稳定": c4,
            "判定": f"{verdict}({n_pass}/4)",
        }
        print(
            f"\n■ {name} (方向{'高好' if direction == +1 else '低好'}) 判定: {verdict}"
        )
        print(
            "  分组年化: "
            + "  ".join(
                f"Q{g + 1}{'*' if g == li else ''}:{anns[g]:+.1%}" for g in range(N_Q)
            )
            + f"  基准:{ann_bench:+.1%}"
        )
        print(
            f"  IC均值 {ic_mean:+.4f} (t={ic_t:+.2f}, 方向{'对' if sign_ok else '反'}) | "
            f"多头超额 15bp:{metrics(long_nav)['年化'] - ann_bench:+.1%} "
            f"25bp:{metrics(long25)['年化'] - ann_bench:+.1%} "
            f"35bp:{metrics(long35)['年化'] - ann_bench:+.1%} | 年换手 {turn:.1f}"
        )
        print(
            "  分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items())
        )

    # ---- 相关性矩阵读数 ----
    print(f"\n== 因子值截面相关(月均 Spearman, {corr_n} 期) ==")
    print(corr_cs.round(2).to_string())
    print("\n== IC 序列相关(动态互补性) ==")
    print(corr_ic.round(2).to_string())
    same_source = [
        (a, b)
        for i, a in enumerate(corr_cs.index)
        for b in corr_cs.index[i + 1 :]
        if corr_cs.at[a, b] > 0.6
    ]
    if same_source:
        print(
            f"\n⚠ 预注册同源判据触发(截面相关>0.6): {same_source} → 组合阶段每组只留判定更优者"
        )

    # ---- 输出 ----
    OUT.mkdir(exist_ok=True)
    pd.DataFrame(rows).T.to_csv(OUT / "factor_screen_round1_summary.csv")
    corr_cs.round(4).to_csv(OUT / "factor_corr_crosssec.csv")
    corr_ic.round(4).to_csv(OUT / "factor_corr_ic.csv")

    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    for ax, (name, _) in zip(axes.flat, FACTORS.items()):
        ln = long_navs[name]
        v = rows[name]["判定"]
        ax.plot(ln, lw=1.1, label=f"多头({name})")
        ax.plot(nav_bench, lw=1.0, ls="--", color="gray", label="等权基准")
        ax.set_yscale("log")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax.set_title(f"{name}  {v}", fontsize=10)
    fig.suptitle("Round 1 四因子多头净值 vs 同池等权基准 (扣15bp, 对数)", fontsize=12)
    fig.tight_layout()
    out_png = OUT / "factor_screen_round1.png"
    fig.savefig(out_png, dpi=130)
    print(f"\n图已保存: {out_png}")
    print(
        "CSV: factor_screen_round1_summary.csv / factor_corr_crosssec.csv / factor_corr_ic.csv"
    )


if __name__ == "__main__":
    main()
