#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""星期效应研究：一周中不同交易日（周一~周五）的市场收益是否存在系统性差异？

研究框架（对应方案的三层验证）：
  第1层 描述    ：按星期几分组，统计平均收益/中位数/胜率/波动率
  第2层 显著性  ：Welch t 检验 + 置换检验(非参数)，Bonferroni 校正多重比较
  第3层 稳定性  ：分年代切片 + 滚动5年曲线；跨时期方向一致才承认效应存在
  第4层 可交易性：把收益差折算成年化，对比周频换手的交易成本

用法:
    uv run python research/weekday_effect.py                     # 沪深300, 2005年起
    uv run python research/weekday_effect.py --symbol 000905     # 中证500 交叉验证
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_loader import load_index_daily

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五"]
# 提前写死的判定标准（防事后找补）：Bonferroni 校正 alpha = 0.05/5
ALPHA = 0.01
ERAS = {
    "2005-2012": ("2005-01-01", "2012-12-31"),
    "2013-2018": ("2013-01-01", "2018-12-31"),
    "2019-2026": ("2019-01-01", "2026-12-31"),
}
# 周频策略成本估算：往返一次 ≈ 佣金0.025%*2 + 滑点0.1%*2 + 印花税0.05%
COST_PER_ROUND_TRIP = 0.0025


def load_returns(symbol: str, start: str, end: str | None) -> pd.Series:
    """日收益率序列，并附加星期标签。"""
    df = load_index_daily(symbol, start=start, end=end, refresh=True)
    ret = df["close"].pct_change().dropna()
    return ret


def group_stats(ret: pd.Series) -> pd.DataFrame:
    """第1层：按星期几分组的描述统计。"""
    g = ret.groupby(ret.index.dayofweek)
    out = pd.DataFrame(
        {
            "样本数": g.count(),
            "平均收益(bp)": g.mean() * 1e4,  # 1bp = 0.01%
            "中位数(bp)": g.median() * 1e4,
            "胜率": g.apply(lambda x: (x > 0).mean()),
            "波动率(bp)": g.std() * 1e4,
        }
    )
    out.index = WEEKDAY_NAMES
    return out


def significance_tests(ret: pd.Series, n_perm: int = 10000) -> pd.DataFrame:
    """第2层：每个交易日 vs 其余全部，Welch t 检验 + 置换检验。

    置换检验：把星期标签随机打乱 n_perm 次，看真实差异在随机世界里的排位。
    """
    rows = []
    rng = np.random.default_rng(42)
    arr = ret.to_numpy()
    labels = ret.index.dayofweek.to_numpy()
    for wd in range(5):
        x, rest = arr[labels == wd], arr[labels != wd]
        t_stat, p_welch = stats.ttest_ind(x, rest, equal_var=False)

        # 置换检验
        obs_diff = x.mean() - rest.mean()
        pooled = arr.copy()
        perm_diffs = np.empty(n_perm)
        for i in range(n_perm):
            rng.shuffle(pooled)
            d = pooled[: len(x)].mean() - pooled[len(x) :].mean()
            perm_diffs[i] = d
        p_perm = (np.abs(perm_diffs) >= abs(obs_diff)).mean()

        rows.append(
            {
                "星期": WEEKDAY_NAMES[wd],
                "差异(bp)": obs_diff * 1e4,
                "Welch_p": p_welch,
                "置换_p": p_perm,
                "Bonferroni显著": p_perm < ALPHA,
            }
        )
    return pd.DataFrame(rows).set_index("星期")


def stability_by_era(ret: pd.Series) -> pd.DataFrame:
    """第3层：分年代切片，看每组的平均收益方向是否跨时期一致。"""
    slices = {}
    for name, (s, e) in ERAS.items():
        sub = ret[(ret.index >= s) & (ret.index <= e)]
        if len(sub) > 100:
            slices[name] = sub.groupby(sub.index.dayofweek).mean() * 1e4
    df = pd.DataFrame(slices)
    df.index = WEEKDAY_NAMES
    era_cols = list(slices)
    df["方向一致"] = [
        len({np.sign(v) for v in row}) == 1 for row in df[era_cols].to_numpy()
    ]
    return df


def rolling_weekday_mean(ret: pd.Series, window_obs: int = 244) -> pd.DataFrame:
    """每个星期几的滚动均值（约5年: 每年该星期约出现49次）。"""
    out = {}
    for wd in range(5):
        s = ret[ret.index.dayofweek == wd]
        out[WEEKDAY_NAMES[wd]] = s.rolling(window_obs, min_periods=100).mean() * 1e4
    return pd.DataFrame(out)


def make_conclusion(
    sig: pd.DataFrame, stab: pd.DataFrame, desc: pd.DataFrame, symbol: str
) -> str:
    """综合三层 + 可交易性，生成一段结论。"""
    lines = [f"\n{'=' * 62}\n结论（{symbol}）\n{'=' * 62}"]
    sig_days = []
    for wd in WEEKDAY_NAMES:
        p = sig.loc[wd, "置换_p"]
        consistent = stab.loc[wd, "方向一致"]
        edge_bp = desc.loc[wd, "平均收益(bp)"]
        if p < ALPHA and consistent:
            lines.append(
                f"● {wd}: 效应存在且跨时期稳定 (p={p:.4f}, {edge_bp:+.1f}bp/天)"
            )
            sig_days.append(wd)
        elif p < 0.05:
            lines.append(
                f"○ {wd}: p={p:.4f}<0.05 但未过 Bonferroni 校正或跨时期方向不一致 —— 按噪音处理"
            )
        else:
            lines.append(f"× {wd}: 无显著差异 (p={p:.4f})")

    if not sig_days:
        lines.append("\n➤ 未发现任何同时满足[统计显著+跨时期稳定]的星期效应。")
        lines.append(
            "  这与文献一致：早年记录的周内效应大多已衰减或本就是数据挖掘产物。"
        )
    else:
        d = desc.loc[sig_days[0], "平均收益(bp)"] / 1e4
        annual_edge = d * 244
        annual_cost = COST_PER_ROUND_TRIP * 52
        lines.append(f"\n➤ 可交易性检验：即便效应为真，年化超额≈{annual_edge:.1%}，")
        lines.append(
            f"  而周频换仓的年成本≈{annual_cost:.1%} —— "
            f"{'勉强可交易' if annual_edge > annual_cost else '扣完成本为负，不可交易'}。"
        )
    lines.append("\n※ 提醒：历史规律≠未来有效；本结论仅针对所测区间，不构成投资建议。")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="星期效应研究")
    ap.add_argument("--symbol", default="000300", help="指数代码: 000300/000905/000001")
    ap.add_argument("--start", default="20050101")
    ap.add_argument("--end", default=None)
    ap.add_argument("--n-perm", type=int, default=10000, help="置换检验次数")
    args = ap.parse_args()

    print(f"加载 {args.symbol} 自 {args.start} ...")
    ret = load_returns(args.symbol, args.start, args.end)
    print(f"共 {len(ret)} 个交易日: {ret.index[0].date()} ~ {ret.index[-1].date()}\n")

    # ---- 第1层 描述 ----
    desc = group_stats(ret)
    print("【第1层】描述统计")
    print(desc.to_string(float_format=lambda v: f"{v:.2f}"))

    # ---- 第2层 显著性 ----
    sig = significance_tests(ret, n_perm=args.n_perm)
    print(
        f"\n【第2层】显著性检验 (vs 其余交易日; 置换 {args.n_perm} 次;"
        f" Bonferroni alpha={ALPHA})"
    )
    print(sig.to_string(float_format=lambda v: f"{v:.4f}"))

    # ---- 第3层 稳定性 ----
    stab = stability_by_era(ret)
    print("\n【第3层】分年代平均收益(bp) —— 方向是否跨时期一致?")
    print(stab.to_string(float_format=lambda v: f"{v:.1f}"))

    # ---- 第4层 结论 ----
    print(make_conclusion(sig, stab, desc, args.symbol))

    # ---- 图表 ----
    fig, axes = plt.subplots(
        2, 1, figsize=(11, 8), gridspec_kw={"height_ratios": [1, 1]}
    )
    ax = axes[0]
    means = desc["平均收益(bp)"].to_numpy()
    # bootstrap 置信区间（组内重采样）
    rng = np.random.default_rng(7)
    cis = []
    for wd in range(5):
        x = ret[ret.index.dayofweek == wd].to_numpy()
        boots = rng.choice(x, size=(2000, len(x)), replace=True).mean(axis=1)
        cis.append(np.percentile(boots, [2.5, 97.5]) * 1e4)
    cis = np.array(cis)
    err = np.abs(cis - means[:, None]).T
    colors = [
        "crimson" if sig.loc[w, "Bonferroni显著"] else "steelblue"
        for w in WEEKDAY_NAMES
    ]
    ax.bar(WEEKDAY_NAMES, means, yerr=err, capsize=4, alpha=0.8, color=colors)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title(f"{args.symbol} 按星期分组的平均日收益 (bp, 误差棒=95% bootstrap CI)")
    ax.grid(alpha=0.3, axis="y")

    ax = axes[1]
    roll = rolling_weekday_mean(ret)
    for col in roll.columns:
        ax.plot(roll.index, roll[col], lw=1, label=col)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("滚动5年平均日收益(bp) —— 看效应是否随时间消失")
    ax.legend(ncol=5, fontsize=9)
    ax.grid(alpha=0.3)

    out = (
        Path(__file__).resolve().parent.parent
        / "output"
        / f"weekday_effect_{args.symbol}.png"
    )
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"\n图表已保存: {out}")


if __name__ == "__main__":
    main()
