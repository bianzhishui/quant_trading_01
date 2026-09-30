#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 56: 修 scenario_ytd_p3 估值口径(R48 eval_prices) + 重跑份额级验证 —— 按 plan §3。

V1 口径锚点: 活窗口(2026-09-01→数据末尾) 600万 单账户 vs 生产账本每日 CSV 逐日对齐。
V2 主窗口回归: 2021-01-04→2026-09-28 × {S0 不截断, S1 A1} × 8 账户, 对照 R53 记录值。
V3 全样本重跑: 2014-02-10→2026-09-28 × {S0, S1} × 8 账户(上轮因估值缺陷作废的窗口)。

口径: A1 target_fn 与 summarize 与 R53 归档实现逐行一致(sorted(S) 防哈希抖动)。
用法: uv run python scripts/factor_round56_p3_eval_fix.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from quant_trading_01.config import get_config, load_config  # noqa: E402
from quant_trading_01.dividend_factor import metrics  # noqa: E402
from scripts.p3.scenario_ytd_p3 import run_scenario_p3  # noqa: E402

KEEP = 0.70
AUMS8 = [30_000, 100_000, 200_000, 300_000, 600_000, 1_000_000, 3_000_000, 6_000_000]
MAIN = ("2021-01-04", "2026-09-28")
FULL = ("2014-02-10", "2026-09-28")
# R53 §0 主窗口记录值(修复前口径) —— V2 回归基准
R53_MAIN = {
    (30_000, "S0"): (-0.0399, -0.3494, 0.526, 0.491, 0.3500),
    (30_000, "S1"): (0.0809, -0.2047, 0.997, 0.220, 0.4773),
    (100_000, "S0"): (0.1328, -0.2382, 0.996, 0.091, 0.3016),
    (100_000, "S1"): (0.1514, -0.2137, 0.998, 0.060, 0.2841),
    (200_000, "S0"): (0.1595, -0.2450, 0.996, 0.043, 0.2261),
    (200_000, "S1"): (0.1704, -0.2168, 0.998, 0.028, 0.2202),
    (300_000, "S0"): (0.1683, -0.2473, 0.996, 0.029, 0.1955),
    (300_000, "S1"): (0.1781, -0.2169, 0.998, 0.018, 0.1949),
    (600_000, "S0"): (0.1764, -0.2480, 0.996, 0.015, 0.1596),
    (600_000, "S1"): (0.1848, -0.2177, 0.998, 0.009, 0.1682),
    (1_000_000, "S0"): (0.1803, -0.2489, 0.996, 0.010, 0.1451),
    (1_000_000, "S1"): (0.1878, -0.2179, 0.998, 0.005, 0.1583),
    (3_000_000, "S0"): (0.1835, -0.2494, 0.996, 0.005, 0.1323),
    (3_000_000, "S1"): (0.1901, -0.2182, 0.998, 0.002, 0.1512),
    (6_000_000, "S0"): (0.1842, -0.2496, 0.996, 0.003, 0.1302),
    (6_000_000, "S1"): (0.1905, -0.2183, 0.998, 0.002, 0.1499),
}
# R55 §0.3 等权参考(同一数据版本, 全样本 2014-01~2026-09)
EW_FULL = {
    "P0(1.00)": {"年化": 0.2043, "回撤": -0.4554},
    "A1(0.70)": {"年化": 0.2225, "回撤": -0.4308},
}


def make_target_fn(vol: pd.DataFrame):
    """低波截断: 池内 vol60 升序取前 70%（NaN 记最差）。与 R53 归档实现一致。"""

    def fn(T: pd.Timestamp, S: set) -> set:
        if not S:
            return set()
        v = (
            vol.loc[T]
            .reindex(sorted(S))
            .replace([np.inf, -np.inf], np.nan)
            .fillna(np.inf)
        )
        n = max(int(np.ceil(len(v) * KEEP)), 1)
        return set(v.sort_values(ascending=True).index[:n])

    return fn


def summarize(nav: pd.Series, rows: list, aum: float) -> dict:
    m = metrics(nav / nav.iloc[0])  # nav 以 aum 起 → 先归一化(否则年化失真)
    d = pd.DataFrame(rows)
    tgt = float(d["n_target"].mean())
    hold = float(d["n_hold"].mean())
    short = float(d["n_1lot_short"].sum() / max(d["n_target"].sum(), 1))
    return {
        "年化": m["年化"],
        "回撤": m["最大回撤"],
        "夏普": m["夏普"],
        "累计": float(nav.iloc[-1] / nav.iloc[0] - 1),
        "目标只数": tgt,
        "实际持仓": hold,
        "持仓率": hold / tgt if tgt else np.nan,
        "买不起1手占比": short,
        "现金占比": float((d["cash"] / d["post_nav"]).mean()),
        "累计费用%": float(d["fee"].sum() / aum),
        "调仓次数": int(len(d)),
    }


def run_window(start: str, end: str, aums: list, keep: float | None) -> dict:
    """keep=None → S0(不截断); keep=0.70 → S1(A1)。"""
    detail: list = []
    navs = run_scenario_p3(
        start,
        end,
        out_prefix=None,
        verbose=False,
        aums=aums,
        low_vol_keep=keep,
        low_vol_window=60,
        detail=detail,
    )
    out = {}
    for aum in aums:
        tag = f"aum{int(aum / 1e4)}w"
        rows = [r for r in detail if r["aum"] == aum]
        out[aum] = (navs[tag], rows)
    return out


def main() -> None:
    load_config(None)
    cfg = get_config()
    t0 = time.time()
    print("== Round 56: scenario_ytd_p3 估值口径修复 + 份额级重跑 ==", flush=True)
    print(
        f"配置: low_vol_keep={cfg.p3.low_vol_keep} window={cfg.p3.low_vol_window} | "
        f"账户 {[int(a / 1e4) for a in cfg.p3.aum_list]} 万",
        flush=True,
    )
    src = Path("scripts/p3/scenario_ytd_p3.py").read_text()
    print(
        f"修复自检: raw_e=raw.ffill() {'✅' if 'raw_e = raw.ffill()' in src else '❌'} | "
        f"估值切 raw_e 次数 {src.count('pf.value(raw_e.iloc[i])')}（应为 3）",
        flush=True,
    )

    # ---------- V1 口径锚点: 活窗口 vs 生产账本 ----------
    print(
        "\n=== V1 口径锚点: 活窗口 2026-09-01→数据末尾, 600万, vs 生产账本 ===",
        flush=True,
    )
    live = run_window("2026-09-01", None, [6_000_000], cfg.p3.low_vol_keep)[6_000_000]
    nav_live, rows_live = live
    prod = pd.read_csv("output/p3/daily_nav_p3_aum600w.csv")
    prod["date"] = pd.to_datetime(prod["date"])
    prod_s = prod.set_index("date")["nav"]
    j = pd.concat([nav_live.rename("scenario"), prod_s.rename("prod")], axis=1).dropna()
    rel = (j["scenario"] / j["prod"] - 1).abs()
    v1a = abs(j["scenario"].iloc[0] / j["prod"].iloc[0] - 1)
    v1b = float(rel.max())
    n_hold0 = rows_live[0]["n_hold"] if rows_live else -1
    n_tgt0 = rows_live[0]["n_target"] if rows_live else -1
    print(
        f"  对齐 {len(j)} 日（scenario {nav_live.index[0].date()}~{nav_live.index[-1].date()} vs "
        f"prod {prod_s.index[0].date()}~{prod_s.index[-1].date()}）"
    )
    print(
        f"  首日: scenario {j['scenario'].iloc[0]:,.2f} vs prod {j['prod'].iloc[0]:,.2f} | "
        f"相对差 {v1a:.4%} → V1a({'✅' if v1a <= 0.0005 else '❌'}, ≤0.05%)"
    )
    print(
        f"  逐日最大相对差 {v1b:.4%}（末日 {j.index[-1].date()} scenario "
        f"{j['scenario'].iloc[-1]:,.2f} vs prod {j['prod'].iloc[-1]:,.2f}）→ "
        f"V1b({'✅' if v1b <= 0.0010 else '❌'}, ≤0.10%)"
    )
    print(
        f"  首日持仓 {n_hold0:.0f} 只（目标 {n_tgt0:.0f}）→ V1c"
        f"({'✅' if n_hold0 == 36 else '❌'}, =36)"
    )

    # ---------- V2 主窗口回归 ----------
    print(
        f"\n=== V2 主窗口 {MAIN[0]}→{MAIN[1]} × {{S0,S1}} × 8 账户（对照 R53）===",
        flush=True,
    )
    s0 = run_window(*MAIN, AUMS8, None)
    s1 = run_window(*MAIN, AUMS8, KEEP)
    print(f"  数据+主窗口耗时 {time.time() - t0:.0f}s", flush=True)
    v2a_ok, v2b_max = True, 0.0
    print(
        "  账户 | 变体 |    年化 |    R53 |   Δ |    回撤 |    R53 |  持仓率 |  现金% | 费用%"
    )
    rows_v2 = []
    for aum in AUMS8:
        for tag, res in (("S0", s0), ("S1", s1)):
            nav, rows = res[aum]
            m = summarize(nav, rows, aum)
            r53 = R53_MAIN[(aum, tag)]
            d_ann = m["年化"] - r53[0]
            print(
                f"  {int(aum / 1e4):>4}万 | {tag} | {m['年化']:+7.2%} | {r53[0]:+7.2%} | "
                f"{d_ann:+5.2%} | {m['回撤']:+7.2%} | {r53[1]:+7.2%} | {m['持仓率']:7.1%} | "
                f"{m['现金占比']:6.1%} | {m['累计费用%']:5.2%}"
            )
            rows_v2.append(
                {"aum": aum, "tag": tag, **m, "R53年化": r53[0], "Δ年化": d_ann}
            )
    for aum in AUMS8:
        m_s0 = summarize(*s0[aum], aum)
        m_s1 = summarize(*s1[aum], aum)
        if not (m_s1["年化"] >= m_s0["年化"] and m_s1["回撤"] >= m_s0["回撤"]):
            v2a_ok = False
            print(
                f"  ⚠️ V2a 符号翻转: {int(aum / 1e4)}万 "
                f"S0 {m_s0['年化']:+.2%}/{m_s0['回撤']:+.2%} vs "
                f"S1 {m_s1['年化']:+.2%}/{m_s1['回撤']:+.2%}"
            )
    d2 = pd.DataFrame(rows_v2)
    v2b_max = float(d2["Δ年化"].abs().max())
    m3 = summarize(*s0[30_000], 30_000)
    v2c = m3["持仓率"] < 0.70 and m3["现金占比"] > 0.30 and m3["累计费用%"] > 0.30
    print(
        f"  V2a 八账户 S1 年化 ≥ S0: {'✅' if v2a_ok else '❌'} | "
        f"V2b |Δ年化| 最大 {v2b_max:.2%}（>1.0pp 须解释）: "
        f"{'✅' if v2b_max <= 0.010 else '⚠️'} | "
        f"V2c 3万仍执行失败（持仓率 {m3['持仓率']:.1%} 现金 {m3['现金占比']:.1%} "
        f"费用 {m3['累计费用%']:.1%}）: {'✅' if v2c else '❌'}"
    )

    # ---------- V3 全样本重跑 ----------
    print(f"\n=== V3 全样本 {FULL[0]}→{FULL[1]} × {{S0,S1}} × 8 账户 ===", flush=True)
    f0 = run_window(*FULL, AUMS8, None)
    f1 = run_window(*FULL, AUMS8, KEEP)
    print(f"  总耗时 {time.time() - t0:.0f}s", flush=True)
    print(
        "  账户 | 变体 |    年化 |    回撤 | 夏普 | 目标/实际 | 持仓率 | 买不起1手 | 现金% | 费用%"
    )
    rows_v3 = []
    for aum in AUMS8:
        for tag, res in (("S0", f0), ("S1", f1)):
            nav, rows = res[aum]
            m = summarize(nav, rows, aum)
            print(
                f"  {int(aum / 1e4):>4}万 | {tag} | {m['年化']:+7.2%} | {m['回撤']:+7.2%} | "
                f"{m['夏普']:4.2f} | {m['目标只数']:4.1f}/{m['实际持仓']:4.1f} | "
                f"{m['持仓率']:6.1%} | {m['买不起1手占比']:8.2%} | {m['现金占比']:6.1%} | "
                f"{m['累计费用%']:5.2%}"
            )
            rows_v3.append({"aum": aum, "tag": tag, **m})
    d3 = pd.DataFrame(rows_v3)
    p600 = d3[(d3["aum"] == 6_000_000) & (d3["tag"] == "S0")].iloc[0]
    v3a = -0.55 <= p600["回撤"] <= -0.35
    v3b = p600["累计费用%"] <= 0.15
    n_ok = 0
    for aum in AUMS8:
        a, b = (
            d3[(d3["aum"] == aum) & (d3["tag"] == "S0")].iloc[0],
            d3[(d3["aum"] == aum) & (d3["tag"] == "S1")].iloc[0],
        )
        if b["年化"] >= a["年化"] and b["回撤"] >= a["回撤"]:
            n_ok += 1
    v3c = n_ok >= 7
    print(
        f"\n  V3a 600万 S0 全样本回撤 {p600['回撤']:+.2%} ∈ [−55%,−35%]: "
        f"{'✅' if v3a else '❌'}（等权 P0 同窗 {EW_FULL['P0(1.00)']['回撤']:+.2%}）"
    )
    print(
        f"  V3b 600万 S0 累计费用 {p600['累计费用%']:.2%} ≤15% 本金: {'✅' if v3b else '❌'}"
        f"（缺陷特征 117-165%）"
    )
    print(
        f"  V3c S1 不劣于 S0（年化与非浅回撤同时）: {n_ok}/8 账户 → "
        f"{'✅' if v3c else '❌'}（需 ≥7）"
    )
    print(
        f"  等权参考(R55 同数据版本, 2014-01~2026-09): P0 {EW_FULL['P0(1.00)']['年化']:+.2%}/"
        f"{EW_FULL['P0(1.00)']['回撤']:+.2%} | A1 {EW_FULL['A1(0.70)']['年化']:+.2%}/"
        f"{EW_FULL['A1(0.70)']['回撤']:+.2%}"
    )
    print(
        f"\n  600万 全样本: S0 {p600['年化']:+.2%}/{p600['回撤']:+.2%} | "
        f"S1 {d3[(d3['aum'] == 6_000_000) & (d3['tag'] == 'S1')].iloc[0]['年化']:+.2%}/"
        f"{d3[(d3['aum'] == 6_000_000) & (d3['tag'] == 'S1')].iloc[0]['回撤']:+.2%}"
    )
    out = Path("tmp/r56_results.csv")
    pd.concat([d2.assign(窗口="主"), d3.assign(窗口="全样本")]).to_csv(out, index=False)
    print(f"\n明细已存 {out} | 总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
