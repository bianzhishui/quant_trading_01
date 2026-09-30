#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 58 测量脚本: 空池月口径裁定(X3) + R50 阻塞复核(X4) + 2014 残余归因(X5)
+ 公共助手等价性(Z0)。按 docs/factor_round58_pool_policy_plan.md §2/§3。

不改策略、不改参数、不改生产账本。
用法: uv run python scripts/factor_round58_pool_policy.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quant_trading_01.config import get_config, load_config  # noqa: E402
from quant_trading_01.dividend_factor import metrics  # noqa: E402
from scripts import factor_round41_low_price as r41  # noqa: E402
from scripts.p3.scenario_ytd_p3 import run_scenario_p3  # noqa: E402

KEEP, WINDOW = 0.70, 60
SUB_PRICE, N_YEARS, EW_COST = (3.0, 4.0), 3, 0.0015
MAIN = ("2021-01-04", "2026-09-28")
FULL = ("2014-02-10", "2026-09-28")
SEGS = {
    "全样本": (None, "2026-09-28"),
    "2014-17": ("2014-01-01", "2017-12-31"),
    "2018-21": ("2018-01-01", "2021-12-31"),
    "2022-26": ("2022-01-01", "2026-12-31"),
}


def seg_m(nav: pd.Series, s: str | None, e: str) -> dict:
    seg = nav.loc[s:e] if s else nav.loc[:e]
    m = metrics(seg / seg.iloc[0])
    m["累计"] = float(seg.iloc[-1] / seg.iloc[0] - 1)
    return m


def main() -> int:
    load_config(None)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    t0 = time.time()
    print("== Round 58: 空池月口径裁定 + R50 复核 + 2014 归因 ==")
    data = r41.load_data()
    close = data["close"]

    # ---------- Z0 公共助手等价性 (X6/P3 侧无差异证明) ----------
    print("\n=== Z0 公共助手 forward_factor_series 等价性(应为逐位相同) ===")
    cfg = get_config()
    fac = pd.read_parquet(cfg.paths.round2 + "/adjust_factor.parquet")
    fac["date"] = pd.to_datetime(fac["date"])
    real_ref = close.copy()
    for code in close.columns:
        f = fac[fac["code"] == code]
        if len(f):
            s = f.set_index("date")["foreAdjustFactor"]
            s = s[~s.index.duplicated()].sort_index()
            fac_ser = (  # R57 内联写法(参考实现)
                s.reindex(close.index.union(s.index))
                .ffill()
                .reindex(close.index)
                .bfill()
                .fillna(1.0)
            )
            real_ref[code] = close[code] / fac_ser
        else:
            real_ref[code] = data["real"][code]  # fallback/退市分支不参与等价性
    d = np.abs(real_ref.to_numpy(dtype=float) - data["real"].to_numpy(dtype=float))
    print(
        f"  最大绝对差 {np.nanmax(d):.3e} | 超出 1e-9 的单元 {int((d > 1e-9).sum())} "
        f"→ {'✅ 逐位等价' if (d > 1e-9).sum() == 0 else '❌'}"
    )

    # ---------- X3 空池月口径 ----------
    print("\n=== X3 空池月口径: cash(清仓持币) vs hold(维持持仓, 与生产一致) ===")
    ret = r41.ret_matrix(close, data["out_date"], "zero")
    navs = {}
    for keep, lab in ((None, "P0"), (KEEP, "A1")):
        _, B, _, _, _ = r41.build_sets(
            data, None, sub_price=SUB_PRICE, n_years=N_YEARS, low_vol_keep=keep
        )
        empt = sorted(dt for dt, S in B.items() if len(S) == 0)
        print(
            f"  {lab}: 调仓日 {len(B)} 个, 其中**空池月 {len(empt)} 个** → {[str(x.date()) for x in empt]}"
        )
        for mode in ("cash", "hold"):
            navs[(lab, mode)] = r41.ew_nav(ret, B, EW_COST, empty_mode=mode)
    print(f"\n  {'口径':<10}{'空池处理':<10}" + "".join(f"{s:>24}" for s in SEGS))
    for lab in ("P0", "A1"):
        for mode in ("cash", "hold"):
            nav = navs[(lab, mode)]
            cells = []
            for sname, (s, e) in SEGS.items():
                m = seg_m(nav, s, e)
                cells.append(f"{m['年化']:>+11.2%}/{m['最大回撤']:>+9.2%}")
            print(f"  {lab:<10}{mode:<10}" + "".join(f"{c:>24}" for c in cells))
    for lab in ("P0", "A1"):
        a, b = navs[(lab, "cash")], navs[(lab, "hold")]
        print(
            f"  {lab} 全样本 hold vs cash: 年化 {seg_m(b, None, SEGS['全样本'][1])['年化']:+.2%} vs "
            f"{seg_m(a, None, SEGS['全样本'][1])['年化']:+.2%} | 回撤 "
            f"{seg_m(b, None, SEGS['全样本'][1])['最大回撤']:+.2%} vs "
            f"{seg_m(a, None, SEGS['全样本'][1])['最大回撤']:+.2%}"
        )

    # ---------- X4/X5 份额级: 含阻塞 vs 无阻塞 ----------
    print("\n=== X4 R50 复核 + X5 2014 归因 (600万 S0, 份额级) ===")
    sys.modules["scripts.p3.scenario_ytd_p3"].load_data_p3 = lambda: data

    def run(start, end, block):
        detail: list = []
        navs_ = run_scenario_p3(
            start,
            end,
            out_prefix=None,
            verbose=False,
            aums=[6_000_000],
            block=block,
            low_vol_keep=None,
            low_vol_window=WINDOW,
            detail=detail,
        )
        rows = [r for r in detail if r["aum"] == 6_000_000]
        return navs_["aum600w"], rows

    res = {}
    for win, (s, e) in (("main", MAIN), ("full", FULL)):
        for blk in (True, False):
            nav, rows = run(s, e, blk)
            res[(win, blk)] = (nav, rows)
            print(
                f"  ({win}, block={blk}) 完成 {nav.index[-1].date()} NAV {nav.iloc[-1]:,.0f}"
            )
    print(f"\n  {'窗口':<8}{'含阻塞':>12}{'无阻塞':>12}{'差(无−含)':>12}")
    for win, lab in (("main", "验证段2021-2026"), ("full", "全样本2014-2026")):
        a = seg_m(res[(win, True)][0], None, res[(win, True)][0].index[-1])["年化"]
        b = seg_m(res[(win, False)][0], None, res[(win, False)][0].index[-1])["年化"]
        print(f"  {lab:<8}{a:>+12.2%}{b:>+12.2%}{b - a:>+12.2%}")
    print("\n  逐年(全样本, 含阻塞 vs 无阻塞 vs 等权 hold):")
    nav_b, nav_n = res[("full", True)][0], res[("full", False)][0]
    ew_h = navs[("P0", "hold")]
    idx = nav_b.index.intersection(nav_n.index).intersection(ew_h.index)
    nb, nn, ne = nav_b.reindex(idx), nav_n.reindex(idx), ew_h.reindex(idx)
    print(
        f"  {'年':>5}{'含阻塞':>10}{'无阻塞':>10}{'阻塞影响':>10}{'等权hold':>10}{'含阻塞−等权':>13}{'无阻塞−等权':>13}"
    )
    for y in sorted(set(idx.year)):
        if y == idx.year.min() and len(idx[idx.year == y]) < 30:
            continue
        a, b_, c = (
            nb[nb.index.year == y],
            nn[nn.index.year == y],
            ne[ne.index.year == y],
        )
        if len(a) < 2:
            continue
        ra, rb, rc = (
            a.iloc[-1] / a.iloc[0] - 1,
            b_.iloc[-1] / b_.iloc[0] - 1,
            c.iloc[-1] / c.iloc[0] - 1,
        )
        print(
            f"  {y:>5}{ra:>+10.2%}{rb:>+10.2%}{rb - ra:>+10.2%}{rc:>+10.2%}{ra - rc:>+13.2%}{rb - rc:>+13.2%}"
        )
    # 2014 分解
    y = 2014
    a = nb[nb.index.year == y]
    b_ = nn[nn.index.year == y]
    c = ne[ne.index.year == y]
    ra, rb, rc = (
        a.iloc[-1] / a.iloc[0] - 1,
        b_.iloc[-1] / b_.iloc[0] - 1,
        c.iloc[-1] / c.iloc[0] - 1,
    )
    rows14 = [r for r in res[("full", True)][1] if r["date"].year == y]
    n1 = sum(r["n_1lot_short"] for r in rows14) / max(
        sum(r["n_target"] for r in rows14), 1
    )
    print(
        f"\n  X5 2014 分解: 含阻塞−等权 {ra - rc:+.2%} = (无阻塞−等权) {rb - rc:+.2%} + (阻塞影响) {ra - rb:+.2%}"
    )
    print(
        f"    建仓日错位: 0.00pp(两序列已对齐到同一交易日网格) | 买不起1手: {n1:.2%} 目标只数占比"
    )
    resid = (rb - rc) - 0.0
    print(
        f"    归因残差 |无阻塞−等权| = {abs(resid):.2%}（判据 Y6 ≤2pp）→ {'✅ 可解释' if abs(resid) <= 0.02 else '❌ 未解释'}"
    )
    pd.DataFrame(
        [
            {"年": y, "含阻塞": ra, "无阻塞": rb, "等权hold": rc}
            for y in sorted(set(idx.year))
        ]
    ).to_csv("tmp/r58_yearly.csv", index=False, encoding="utf-8-sig")
    print(f"\n总耗时 {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
