#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""可转债双低轮动实验 —— 严格按 docs/convertible_double_low_plan.md v1.0 实施。

主组合: 双低(价格+溢价率)最低前20只等权, 周频(周五信号→下周一执行=T+1收盘)
对照:   月频变体 / 低溢价前20 / 低价格前20(归因分解) / 中证转债指数 / 全池等权
判定(预注册): ② 月超额vs000832 p<0.05  ③ 三段每段夏普>0.5且跑赢
              ④ 30bp档年超额≥3%     失败如实归档
用法: uv run python research/convertible_double_low.py
"""

from __future__ import annotations

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
from research.dividend_factor import metrics, monthly

CDIR = Path(__file__).resolve().parent.parent / "data" / "convertible"
START = "2018-01-01"
TOP_N = 20
WARMUP = 20  # 上市满20交易日
BASE_COST = 5e-4  # 5bp/单边
COST_30 = 30e-4  # ④ 压测档
ERAS = {
    "2018-2020": ("2018-01-01", "2020-12-31"),
    "2021-2023": ("2021-01-01", "2023-12-31"),
    "2024-2026": ("2024-01-01", None),
}


def load_wide() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = pd.read_parquet(CDIR / "value_analysis.parquet")
    close = df.pivot(index="date", columns="code", values="close").sort_index()
    prem = df.pivot(index="date", columns="code", values="premium").reindex(close.index)
    uni = pd.read_parquet(CDIR / "universe.parquet").set_index("code")
    close.index = pd.to_datetime(close.index)
    return close.loc[START:], prem.loc[START:], uni


def pick_sets(
    close: pd.DataFrame,
    prem: pd.DataFrame,
    factor: pd.DataFrame,
    sig_days: list[pd.Timestamp],
) -> dict:
    """每个信号日 → 双低/因子最低前20集合。factor 传入 close 或 prem 实现归因分组。"""
    warm = close.notna().cumsum()
    sets = {}
    for T in sig_days:
        elig = (warm.loc[T] >= WARMUP) & close.loc[T].notna() & prem.loc[T].notna()
        codes = elig[elig].index
        if len(codes) == 0:
            sets[T] = frozenset()
            continue
        f = factor.loc[T, codes]
        sets[T] = frozenset(f.nsmallest(TOP_N).index)
    return sets


def signal_to_exec(sets: dict, idx: pd.DatetimeIndex) -> dict:
    """信号日 → 次一交易日执行(收盘)。"""
    out, pos = {}, {d: i for i, d in enumerate(idx)}
    for T, s in sets.items():
        i = pos.get(T)
        if i is not None and i + 1 < len(idx):
            out[idx[i + 1]] = s
    return out


def rebalance_nav(
    close: pd.DataFrame, sets_exec: dict, cost: float
) -> tuple[pd.Series, float]:
    """等权+执行日完全再平衡; 退市债以最后有效收盘自然退出。"""
    ret = close.pct_change()
    cols = close.columns
    W = pd.DataFrame(0.0, index=close.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    for i, dt in enumerate(close.index):
        if dt in sets_exec:
            S = sets_exec[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                w[list(S)] = 1.0 / len(S)
        W.iloc[i] = w
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret.fillna(0.0)).sum(axis=1)
    nav = (1 + gross - turn * cost).cumprod()
    years = len(nav) / 244
    return nav, float(turn.sum() / 2 / years)


def weekly_last_days(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    iso = pd.Series(
        idx.isocalendar().week.astype(int)
        | (idx.isocalendar().year.astype(int) * 1000),
        index=idx,
    )
    return idx[iso.shift(-1) != iso]


def month_last_days(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    m = pd.Series(idx.to_period("M"), index=idx)
    return idx[m.shift(-1) != m]


def main() -> None:
    print("== 可转债双低轮动实验 (预注册 v1.0) ==")
    close, prem, uni = load_wide()
    print(
        f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
        f"{close.index[0].date()} ~ {close.index[-1].date()}"
    )
    dbl = close + prem  # 双低因子

    wk_days = weekly_last_days(close.index)
    mo_days = month_last_days(close.index)
    sets_wk_main = signal_to_exec(
        pick_sets(close, prem, dbl, list(wk_days)), close.index
    )
    sets_mo_main = signal_to_exec(
        pick_sets(close, prem, dbl, list(mo_days)), close.index
    )
    sets_wk_prem = signal_to_exec(
        pick_sets(close, prem, prem, list(wk_days)), close.index
    )
    sets_wk_px = signal_to_exec(
        pick_sets(close, prem, close, list(wk_days)), close.index
    )

    sizes = [len(s) for s in sets_wk_main.values() if s]
    print(
        f"周频入选数: 中位 {int(np.median(sizes))}, 范围 {min(sizes)}~{max(sizes)} "
        f"(2018初可选池较小属预期)\n"
    )

    nav_main, turn_main = rebalance_nav(close, sets_wk_main, BASE_COST)
    nav_mo, turn_mo = rebalance_nav(close, sets_mo_main, BASE_COST)
    nav_prem, _ = rebalance_nav(close, sets_wk_prem, BASE_COST)
    nav_px, _ = rebalance_nav(close, sets_wk_px, BASE_COST)
    nav_30, _ = rebalance_nav(close, sets_wk_main, COST_30)

    bench = load_index_daily("000832", start="20180101", refresh=False)["close"]
    bench = bench.reindex(close.index).ffill()
    bench = bench / bench.dropna().iloc[0]
    warm = close.notna().cumsum() >= WARMUP
    ew_pool = (1 + (close.pct_change()[warm]).mean(axis=1).fillna(0)).cumprod()

    mMain, mMo, mP = metrics(nav_main), metrics(nav_mo), metrics(nav_prem)
    mPx, mB, mE = metrics(nav_px), metrics(bench), metrics(ew_pool)

    print("== 汇总 (5bp 基础成本) ==")
    rows = []
    for label, m, tn in [
        ("主组合 双低20·周频", mMain, turn_main),
        ("月频变体", mMo, turn_mo),
        ("低溢价前20(归因)", mP, np.nan),
        ("低价格前20(归因)", mPx, np.nan),
        ("中证转债指数", mB, 0.0),
        ("全池等权", mE, 0.0),
    ]:
        rows.append(
            {
                "组合": label,
                "年化": m["年化"],
                "夏普": m["夏普"],
                "回撤": m["最大回撤"],
                "年换手": tn,
            }
        )
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    # ---- ② 显著性 ----
    diff = (monthly(nav_main) - monthly(bench)).dropna()
    t, p_welch = stats.ttest_1samp(diff, 0)
    rng = np.random.default_rng(7)
    arr = diff.to_numpy()
    p_perm = float(
        (
            np.abs(rng.choice([1, -1], (10000, len(arr))).dot(arr)) / len(arr)
            >= abs(arr.mean())
        ).mean()
    )

    # ---- ③ 稳定性 ----
    print("\n主组合分年代稳定性(第③层, 夏普>0.5 且跑赢指数):")
    stable = True
    for name, (s, e) in ERAS.items():
        a = nav_main[s:e] / nav_main[s:e].dropna().iloc[0]
        b = bench[s:e] / bench[s:e].dropna().iloc[0]
        ma, mb = metrics(a), metrics(b)
        ok = ma["夏普"] > 0.5 and ma["年化"] > mb["年化"]
        stable &= ok
        print(
            f"  {name}: 主 {ma['年化']:+.1%} 夏普 {ma['夏普']:.2f} | "
            f"000832 {mb['年化']:+.1%} | 跑赢 {ma['年化'] > mb['年化']}, 夏普过线 {ma['夏普'] > 0.5}"
        )

    # ---- ④ 可交易 ----
    exc30 = metrics(nav_30)["年化"] - mB["年化"]
    print(
        f"\n④ 30bp档: 年化 {metrics(nav_30)['年化']:+.1%} vs 指数 {mB['年化']:+.1%} "
        f"→ 年超额 {exc30:+.1%}, 达标(≥3%): {exc30 >= 0.03}"
    )

    # ---- 归因读数 ----
    print("\n== 归因读数 ==")
    print(
        f"周频 vs 月频: {mMain['年化']:+.1%} vs {mMo['年化']:+.1%} "
        f"→ 周频边际价值 {mMain['年化'] - mMo['年化']:+.1%}/年 (换手 {turn_main:.0f} vs {turn_mo:.0f})"
    )
    print(
        f"低溢价组 {mP['年化']:+.1%} | 低价格组 {mPx['年化']:+.1%} | 主组合 {mMain['年化']:+.1%}"
    )
    if mP["年化"] > mPx["年化"]:
        print("  → 超额主要由低溢价驱动(均值回归逻辑, 健康面)")
    else:
        print("  → 超额主要由低价格驱动(信用风险敞口, 警报面: 债底非铁底)")

    print(
        f"\n②显著性: Welch p={p_welch:.4f}, 置换 p={p_perm:.4f} → "
        f"{'通过' if p_perm < 0.05 else '未通过'}"
    )
    print(f"③稳定性: {'通过' if stable else '未通过'}")
    print(f"④可交易: {'通过' if exc30 >= 0.03 else '未通过'}")

    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(nav_main, lw=1.5, label="双低20·周频(主)")
    ax.plot(nav_mo, lw=1.1, label="双低20·月频")
    ax.plot(nav_prem, lw=1, alpha=0.8, label="低溢价前20")
    ax.plot(nav_px, lw=1, alpha=0.8, label="低价格前20")
    ax.plot(bench, lw=1, alpha=0.7, label="中证转债指数")
    ax.plot(ew_pool, lw=1, alpha=0.5, label="全池等权")
    for y in ("2021-01-01", "2024-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    ax.set_title("可转债双低轮动 (对数净值, 5bp基础成本)")
    out = (
        Path(__file__).resolve().parent.parent / "output" / "convertible_double_low.png"
    )
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"\n图已保存: {out}")


if __name__ == "__main__":
    main()
