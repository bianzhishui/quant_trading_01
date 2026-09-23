#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 43 样本外拆分验证 —— 按 docs/factor_round43_outsample_plan.md v1.0。

训练段 2014-2020(子区间选择时间检验) / 验证段 2021-2026(独立判定)。
复用 round41/42: load_data/ret_matrix/ew_nav/build_sets/metrics。
用法: uv run python scripts/factor_round43_outsample.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import load_config
from quant_trading_01.dividend_factor import metrics
from scripts.factor_round41_low_price import (
    build_sets,
    ew_nav,
    load_data,
    ret_matrix,
    COST_BASE,
    COST_HIGH,
)

TRAIN = ("2014-01-01", "2020-12-31")
VAL = ("2021-01-01", "2026-12-31")
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]


def seg_metrics(nav: pd.Series, s: str, e: str) -> dict:
    n = nav[s:e]
    if len(n) < 50:
        return {"年化": float("nan"), "夏普": float("nan"), "最大回撤": float("nan")}
    return metrics(n / n.dropna().iloc[0])


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("加载数据...", flush=True)
    data = load_data()
    ret = ret_matrix(data["close"], data["out_date"], "zero")
    print(f"数据就绪 {time.time() - t0:.0f}s", flush=True)

    # ---- 训练段: 子区间选择时间检验 ----
    print("\n=== 训练段(2014-2020) 子区间 B 组排序 ===")
    train_rank = []
    for lo, hi, tag in [(0, 2, "0-2元"), (2, 3, "2-3元"), (3, 5, "3-5元")]:
        A, B, _, _, _ = build_sets(data, None, sub_price=(lo, hi))
        nav = ew_nav(ret, B, COST_BASE)
        m = seg_metrics(nav, *TRAIN)
        train_rank.append((tag, m["年化"], m["最大回撤"]))
        print(f"  {tag}: 年化 {m['年化']:+.1%} 回撤 {m['最大回撤']:.1%}")
    best_train = max(train_rank, key=lambda x: x[1])
    print(f"  训练段最优区间: {best_train[0]} (年化 {best_train[1]:+.1%})")

    # ---- 验证段: B23(2-3元+质量) 独立评估 ----
    print("\n=== 验证段(2021-2026) B23 vs 全市场 ===")
    A23, B23, C, _, _ = build_sets(data, None, sub_price=(2.0, 3.0))
    navB = ew_nav(ret, B23, COST_BASE)
    navC = ew_nav(ret, C, COST_BASE)
    navB45 = ew_nav(ret, B23, COST_HIGH)

    mB = seg_metrics(navB, *VAL)
    mC = seg_metrics(navC, *VAL)
    mB45 = seg_metrics(navB45, *VAL)
    print(
        f"  B23: 年化 {mB['年化']:+.1%} 夏普 {mB['夏普']:.2f} 回撤 {mB['最大回撤']:.1%}"
    )
    print(
        f"  C  : 年化 {mC['年化']:+.1%} 夏普 {mC['夏普']:.2f} 回撤 {mC['最大回撤']:.1%}"
    )
    print(f"  B23(45bp): 年化 {mB45['年化']:+.1%}")

    # 分年度
    print("\n  分年度(验证段):")
    win = 0
    for y in YEARS:
        s, e = f"{y}-01-01", f"{y}-12-31"
        mb = seg_metrics(navB, s, e)
        mc = seg_metrics(navC, s, e)
        ok = mb["年化"] > mc["年化"]
        win += ok
        print(f"    {y}: B23 {mb['年化']:+.1%} vs C {mc['年化']:+.1%} 跑赢:{ok}")
    print(f"    跑赢年份: {win}/{len(YEARS)}")

    # ---- 判定 ----
    exc = mB["年化"] - mC["年化"]
    dd_ok = mB["最大回撤"] >= mC["最大回撤"]
    exc45 = mB45["年化"] - mC["年化"]
    sharpe_ok = mB["夏普"] >= 0.5
    print("\n== 判定(验证段, ①-⑤全过=通过) ==")
    print(f"  ① B23 vs C 超额 {exc:+.1%} (>=3pp: {exc >= 0.03})")
    print(f"  ② 回撤 {mB['最大回撤']:.1%} vs C {mC['最大回撤']:.1%} (<=C: {dd_ok})")
    print(f"  ③ 分年度跑赢 {win}/{len(YEARS)} (>=一半: {win >= len(YEARS) // 2})")
    print(f"  ④ 45bp 超额 {exc45:+.1%} (>=1pp: {exc45 >= 0.01})")
    print(f"  ⑤ 夏普 {mB['夏普']:.2f} (>=0.5: {sharpe_ok})")
    passed = (
        exc >= 0.03 and dd_ok and win >= len(YEARS) // 2 and exc45 >= 0.01 and sharpe_ok
    )
    print(f"  ==> 判定: {'通过' if passed else '未达标'}")

    # ---- 2.3-3.2 对照(仅报告) ----
    A2, B2, _, _, _ = build_sets(data, None, sub_price=(2.3, 3.2))
    navB2 = ew_nav(ret, B2, COST_BASE)
    mB2 = seg_metrics(navB2, *VAL)
    print(
        f"\n  对照 2.3-3.2 元(仅报告): 验证段 年化 {mB2['年化']:+.1%} 回撤 {mB2['最大回撤']:.1%}"
    )

    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
