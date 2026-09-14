#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""短期反转因子月频实验 —— 严格按 docs/reversal_factor_plan.md v1.0 实施。

规则(预注册定死):
  池: 月末T日 days_count>=375 & tradestatus==1 & isST==0 & 非创业/科创/北交 & T日未涨停
  因子: rev21 = close(T)/close(T-21) - 1 (前复权), 值越低越超跌
  组合: 可交易池 rank 等分5组, 多头=Q1(超跌)等权, 基准=同池等权, 成本15bp/单边
  判定: ①IC<=-0.05且t<=-2 ②Q1最高Q5最低 ③扣成本年化超额>=3pp ④三分段2段为正
  (失败协议: 如实归档, 禁止回头改参数重跑)

用法: uv run python research/reversal_factor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import os

# matplotlib 配置/缓存目录 → 项目内可写位置(默认 ~/.matplotlib 在本环境不可写,
# 否则每次进程重建字体缓存 30-90s); setdefault: 用户已设 MPLCONFIGDIR 时不覆盖。
os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parent.parent / ".mplconfig")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sps

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.config import get_config
from research.dividend_factor import load_all, month_last_days, metrics


def _cfg():
    """当前进程配置单例（main() 里 load_config 后生效；被 import 时用默认）。"""
    return get_config()


def ew_nav(ret: pd.DataFrame, sets: dict, cost: float) -> tuple[pd.Series, float]:
    """月度完全等权持仓模拟(与 dividend_factor.equal_weight_nav 同口径, cost 参数化)。

    sets: {执行日: 成员集合}; 停牌日收益 NaN 视为价格延续(0)。
    返回 (净值序列, 年化单边换手)。
    """
    cols = ret.columns
    W = pd.DataFrame(0.0, index=ret.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    for dt in ret.index:
        if dt in sets:
            S = sets[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                w[list(S)] = 1.0 / len(S)
        W.iloc[W.index.get_loc(dt)] = w
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret.fillna(0.0)).sum(axis=1)
    nav = (1 + gross - turn * cost).cumprod()
    years = len(nav) / 244
    return nav, float(turn.sum() / 2 / years)


def build_pool(
    close: pd.DataFrame, tst: pd.DataFrame, isst: pd.DataFrame
) -> pd.DataFrame:
    """逐日可交易池(布尔宽表): seasoning 日 + 非ST + 非创业/科创/北交 + 未涨停。"""
    cfg = _cfg()
    limit_thr = cfg.strategy.limit_thr
    seasoning = cfg.strategy.r5.seasoning
    days_count = close.notna().cumsum()
    board_ok = pd.Series(
        {
            c: not (c.startswith("bj.") or c[3:6] in {"300", "688"})
            for c in close.columns
        }
    )
    tst_ok = tst.apply(pd.to_numeric, errors="coerce") == 1
    isst_ok = isst.apply(pd.to_numeric, errors="coerce") == 0
    limit_up = close.pct_change() >= limit_thr
    pool = (
        (days_count >= seasoning)
        & tst_ok
        & isst_ok
        & board_ok
        & ~limit_up.fillna(False)
        & close.notna()
    )
    return pool


def main() -> None:
    cfg = _cfg()
    lookback = cfg.strategy.lookback
    n_q = cfg.strategy.n_q
    cost_base = cfg.costs.cost_base
    cost_sweep = cfg.costs.cost_sweep
    eras = cfg.strategy.eras
    out = Path(cfg.paths.output)
    print("== 短期反转因子月频实验 (预注册 v1.0) ==")
    close, real, pb, tst, isst, *_ = load_all()
    print(
        f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
        f"{close.index[0].date()} ~ {close.index[-1].date()}"
    )

    rev = close / close.shift(lookback) - 1.0  # 因子: 越低越超跌
    pool = build_pool(close, tst, isst)
    ret_qfq = close.pct_change()  # 组合收益(前复权)

    # ---- 逐月: 分组集合 + 基准集合 + 月度 RankIC ----
    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    q_sets: list[dict] = [dict() for _ in range(n_q)]
    bench_sets: dict = {}
    ics: dict = {}
    pool_sizes, q_sizes = [], []
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        f = rev.loc[T][e].dropna()
        if len(f) < 50:
            continue
        exec_day = idx[idx.get_loc(T) + 1]  # 次月首个交易日生效
        rk = f.rank(method="first")
        q = pd.qcut(rk, n_q, labels=False)
        for g in range(n_q):
            q_sets[g][exec_day] = set(f.index[q == g])
        bench_sets[exec_day] = set(f.index)
        pool_sizes.append(len(f))
        q_sizes.append(len(f) / n_q)
        T2 = sig_days[k + 1] if k + 1 < len(sig_days) else None
        if T2 is not None:
            fwd = close.loc[T2] / close.loc[T] - 1.0  # 未来一个月收益
            m = f.index.intersection(fwd.dropna().index)
            if len(m) >= 50:
                ics[T] = sps.spearmanr(f[m], fwd[m])[0]

    ic = pd.Series(ics, name="rank_ic").sort_index()
    print(
        f"\n调仓期数 {len(bench_sets)}, 月均可交易池 {np.mean(pool_sizes):.0f} 只, "
        f"组均 {np.mean(q_sizes):.1f} 只, IC 有效期 {len(ic)}"
    )

    # ---- 回测: 五分组 + 基准 + 成本压测 ----
    navs, turns = {}, {}
    for g in range(n_q):
        navs[f"Q{g + 1}"], turns[f"Q{g + 1}"] = ew_nav(ret_qfq, q_sets[g], cost_base)
    navs["基准(等权全池)"], turns["基准"] = ew_nav(ret_qfq, bench_sets, cost_base)
    q1_25, _ = ew_nav(ret_qfq, q_sets[0], cost_sweep[0])
    q1_35, _ = ew_nav(ret_qfq, q_sets[0], cost_sweep[1])

    anns = {k: metrics(v)["年化"] for k, v in navs.items()}
    print("\n== 各分组年化(扣15bp, 2014-2026 全样本) ==")
    for g in range(n_q):
        print(
            f"  Q{g + 1}: {anns[f'Q{g + 1}']:+.1%}  (年换手 {turns[f'Q{g + 1}']:.1f})"
        )
    print(f"  基准: {anns['基准(等权全池)']:+.1%}")
    excess15 = anns["Q1"] - anns["基准(等权全池)"]
    excess25 = metrics(q1_25)["年化"] - anns["基准(等权全池)"]
    excess35 = metrics(q1_35)["年化"] - anns["基准(等权全池)"]
    print(
        f"  多空示意 Q1-Q5(毛, 无空头成本): "
        f"{metrics(navs['Q1'] / navs['Q5'])['年化']:+.1%}/年(几何)"
    )

    # ---- IC 统计 ----    预期方向: 负(过去涨→未来跌)
    ic_mean, ic_std = ic.mean(), ic.std()
    ic_t = ic_mean / ic_std * np.sqrt(len(ic))
    print("\n== RankIC (月度) ==")
    print(
        f"  均值 {ic_mean:+.4f} | 标准差 {ic_std:.4f} | ICIR {ic_mean / ic_std:+.2f} | "
        f"t={ic_t:+.2f} | IC<0 占比 {(ic < 0).mean():.0%}"
    )

    # ---- 分年代稳定性 ----
    print("\n== 分年代 Q1(扣15bp) vs 基准 ==")
    era_excess = {}
    for name, (s, e) in eras.items():
        a = navs["Q1"][s:e]
        b = navs["基准(等权全池)"][s:e]
        ma, mb = metrics(a / a.dropna().iloc[0]), metrics(b / b.dropna().iloc[0])
        era_excess[name] = ma["年化"] - mb["年化"]
        print(
            f"  {name}: Q1 {ma['年化']:+.1%} vs 基准 {mb['年化']:+.1%} "
            f"→ 超额 {ma['年化'] - mb['年化']:+.1%} (回撤 {ma['最大回撤']:.1%})"
        )

    # ---- 预注册判定 ----
    group_ann = [anns[f"Q{g + 1}"] for g in range(n_q)]
    mono_rho = sps.spearmanr(range(1, n_q + 1), group_ann)[0]
    c1 = (ic_mean <= -0.05) and (ic_t <= -2)
    c2 = (group_ann[0] == max(group_ann)) and (group_ann[-1] == min(group_ann))
    c3 = excess15 >= 0.03
    c4 = sum(v > 0 for v in era_excess.values()) >= 2
    n_pass = sum([c1, c2, c3, c4])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    print("\n== 预注册判定 ==")
    print(
        f"  ① IC显著性 (均值<=-0.05 且 t<=-2): {'过' if c1 else '不过'} "
        f"(实际 {ic_mean:+.4f}, t={ic_t:+.2f})"
    )
    print(
        f"  ② 单调性 (Q1最高且Q5最低): {'过' if c2 else '不过'} "
        f"(组序Spearman {mono_rho:+.2f})"
    )
    print(
        f"  ③ 可交易 (15bp超额>=3pp): {'过' if c3 else '不过'} "
        f"(实际 {excess15:+.1%}; 25bp档 {excess25:+.1%}, 35bp档 {excess35:+.1%})"
    )
    print(
        f"  ④ 稳定性 (三段>=2段超额>0): {'过' if c4 else '不过'} "
        f"({sum(v > 0 for v in era_excess.values())}/3)"
    )
    print(f"  ==> 判定: {verdict} ({n_pass}/4)")
    print(
        "⚠ 解读提醒: 池=当前成分(幸存者偏差)+中大市值(反转强度下界估计), "
        "读相对量不作绝对收益宣称。"
    )

    # ---- 输出 ----
    out.mkdir(exist_ok=True)
    nav_df = pd.DataFrame(navs)
    nav_df.to_csv(out / "reversal_factor_quantile_navs.csv")
    ic.to_csv(out / "reversal_factor_ic.csv", header=True)
    pd.DataFrame(
        {
            "年化": anns,
            "年换手": {
                **{f"Q{g + 1}": turns[f"Q{g + 1}"] for g in range(n_q)},
                "基准": turns["基准"],
            },
        }
    ).to_csv(out / "reversal_factor_summary.csv")

    fig, axes = plt.subplots(3, 1, figsize=(11.5, 13))
    for g in range(n_q):
        axes[0].plot(
            navs[f"Q{g + 1}"],
            lw=1.1,
            label=f"Q{g + 1}" + ("(超跌,多头)" if g == 0 else ""),
        )
    axes[0].plot(
        navs["基准(等权全池)"], lw=1.0, ls="--", color="gray", label="等权全池基准"
    )
    axes[0].set_yscale("log")
    axes[0].legend(fontsize=9)
    axes[0].grid(alpha=0.3)
    axes[0].set_title("五分组净值(扣15bp, 对数) — Q1=超跌组")

    ratio = navs["Q1"] / navs["基准(等权全池)"]
    axes[1].plot(ratio, lw=1.2, color="tab:red")
    axes[1].axhline(1.0, color="gray", lw=0.8)
    axes[1].grid(alpha=0.3)
    axes[1].set_title("Q1 / 等权基准 (扣成本后相对强弱)")

    colors = ["tab:red" if v < 0 else "tab:blue" for v in ic.values]
    axes[2].bar(ic.index, ic.values, width=18, color=colors)
    axes[2].plot(
        ic.index, ic.rolling(12).mean(), color="black", lw=1.2, label="12期滚动IC"
    )
    axes[2].axhline(0, color="gray", lw=0.8)
    axes[2].legend(fontsize=9)
    axes[2].grid(alpha=0.3)
    axes[2].set_title(f"月度 RankIC (均值 {ic_mean:+.3f}, 负IC=反转方向成立)")

    fig.tight_layout()
    out_png = out / "reversal_factor.png"
    fig.savefig(out_png, dpi=130)
    print(f"\n图已保存: {out_png}")
    print(
        "CSV: reversal_factor_quantile_navs.csv / reversal_factor_ic.csv / "
        "reversal_factor_summary.csv"
    )


if __name__ == "__main__":
    main()
