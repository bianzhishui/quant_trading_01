#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 42 "2-3元+质量筛选"策略验证 —— 按 docs/factor_round42_low23_quality_plan.md v1.0。

规则(预注册): 区间 2.00<=真实价<3.00; A23无差别/B23质量/C全市场; 等权月频15bp/45bp;
判定 ①-④ 全过=通过; ⑤⑥归因。敏感性: 最后价清算 + 边界 [1.8,2.2)/[2.8,3.2)。
复用 Round41: load_data/ret_matrix/ew_nav/delist_exposure/build_sets。

用法: uv run python scripts/factor_round42_low23_quality.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config, load_config
from quant_trading_01.dividend_factor import metrics
from scripts.factor_round41_low_price import (
    build_sets,
    delist_exposure,
    ew_nav,
    load_data,
    ret_matrix,
    COST_BASE,
    COST_HIGH,
)

LOW23 = (2.0, 3.0)


def _cfg():
    return get_config()


def run(data: dict, mode: str) -> dict:
    """一个退市口径下的完整结果。"""
    out_date = data["out_date"]
    ret = ret_matrix(data["close"], out_date, mode)
    A23, B23, C, _, _ = build_sets(data, None, sub_price=LOW23)
    navA = ew_nav(ret, A23, COST_BASE)
    navB = ew_nav(ret, B23, COST_BASE)
    navC = ew_nav(ret, C, COST_BASE)
    navB45 = ew_nav(ret, B23, COST_HIGH)
    return {
        "A23": metrics(navA),
        "B23": metrics(navB),
        "C": metrics(navC),
        "B45": metrics(navB45),
        "navB": navB,
        "navC": navC,
        "exB": delist_exposure(B23, out_date),
        "nB": [len(s) for s in B23.values() if s],
    }


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("加载数据...", flush=True)
    data = load_data()
    print(f"数据就绪 {time.time() - t0:.0f}s", flush=True)

    print("\n=== 主口径(退市归零) ===")
    r = run(data, "zero")
    for k in ["A23", "B23", "C"]:
        m = r[k]
        print(
            f"  {k}: 年化 {m['年化']:+.1%} 夏普 {m['夏普']:.2f} 回撤 {m['最大回撤']:.1%}"
        )
    print(f"  B23(45bp): 年化 {r['B45']['年化']:+.1%}")

    # 判定 ①-④
    exc = r["B23"]["年化"] - r["C"]["年化"]
    dd_ok = r["B23"]["最大回撤"] >= r["C"]["最大回撤"]  # 回撤数值>= 即不超过C
    stable = 0
    for name, (s, e) in _cfg().r5.eras.to_dict().items():
        b = r["navB"][s:e] / r["navB"][s:e].dropna().iloc[0]
        c = r["navC"][s:e] / r["navC"][s:e].dropna().iloc[0]
        mb, mc = metrics(b), metrics(c)
        ok = mb["年化"] > 0 and mb["年化"] > mc["年化"]
        stable += ok
        print(f"  {name}: B23 {mb['年化']:+.1%} vs C {mc['年化']:+.1%} 跑赢:{ok}")
    exc45 = r["B45"]["年化"] - r["C"]["年化"]
    print("\n== 判定(①-④全过=通过) ==")
    print(f"  ① B23 vs C 超额 {exc:+.1%} (>=3pp: {exc >= 0.03})")
    print(
        f"  ② 回撤 B23 {r['B23']['最大回撤']:.1%} vs C {r['C']['最大回撤']:.1%} (不超C: {dd_ok})"
    )
    print(f"  ③ 分年代 {stable}/3 跑赢 (>=2: {stable >= 2})")
    print(f"  ④ 45bp 超额 {exc45:+.1%} (>=1pp: {exc45 >= 0.01})")
    print(
        f"  ⑤ 归因 B23-A23 超额 {r['B23']['年化'] - r['A23']['年化']:+.1%} (<2pp区间主导: {(r['B23']['年化'] - r['A23']['年化']) < 0.02})"
    )
    print(
        f"  ⑥ 退市暴露 B23 {r['exB']['delist_ratio'].mean():.1%} (月均持仓 {sum(r['nB']) / len(r['nB']):.0f} 只)"
    )
    passed = exc >= 0.03 and dd_ok and stable >= 2 and exc45 >= 0.01
    print(f"  ==> 判定: {'通过' if passed else '未达标'}(需①-④全过)")

    print("\n=== 敏感性: 最后价清算 ===")
    rl = run(data, "last")
    print(
        f"  B23: 年化 {rl['B23']['年化']:+.1%} 回撤 {rl['B23']['最大回撤']:.1%} | A23 {rl['A23']['年化']:+.1%}"
    )

    print("\n=== 边界敏感性(仅报告, 不调参) ===")
    for lo, hi, tag in [(1.8, 2.2, "1.8-2.2"), (2.8, 3.2, "2.8-3.2")]:
        A, B, C, _, _ = build_sets(data, None, sub_price=(lo, hi))
        ret = ret_matrix(data["close"], data["out_date"], "zero")
        mb = metrics(ew_nav(ret, B, COST_BASE))
        print(f"  {tag}元: B 年化 {mb['年化']:+.1%} 回撤 {mb['最大回撤']:.1%}")

    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
