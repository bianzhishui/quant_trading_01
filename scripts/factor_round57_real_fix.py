#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 57: 修 真实价 因子前向填充 bug 后的验证 —— 按 docs/factor_round57_real_fix_plan.md §3。

W1 修复精确性: 改动 ⊂ {t < 该股索引内首条因子记录日} + t≥fr 逐位相同 + 比率分布
W2 切换日不再有假跳跃: fr 当日 |Δreal| ≤ 11% 占比 ≥ 99%（**判据本身有误, 仅报告**:
   fr 当日即除权日, 10送10 真实价腰斩属正常; 真实收益 = 前复权 close 比值, 与修复无关)
W3 数据质量: 非因子变动日 |Δreal| > 12% 占比 ≤ 0.1%
W4 入池与年代结论重算: 等权 P0/A1 全样本 + 三段(2022-26 必须与 R55 一致)
W5 主窗口回归: 2021-01-04→2026-09-28 × {S0,S1} × 8 账户 与 R56(≈R53) 记录值一致
W6 全样本份额级: 600万 S0 回撤 ∈[-55%,-35%] + 逐年 |份额级-等权| ≤5pp + ≥7/8 账户 S1 不劣于 S0

口径: A1 = low_vol_keep 0.70/window 60(走 build_sets 的 low_vol_* 参数, 与生产一致);
      等权参考 = ret_matrix(close) + ew_nav(cost=15bp, 与 R51/R55 一致)。
优化: 单次 load_data 后注入 scenario_ytd_p3.load_data_p3, 并对 build_sets 做记忆化
      (同一 data + 同一参数 → 同一集合; 引擎逻辑未改, R56-V1 已证该路径与生产逐位一致)。
用法: uv run python scripts/factor_round57_real_fix.py
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

KEEP = 0.70
WINDOW = 60
AUMS8 = [30_000, 100_000, 200_000, 300_000, 600_000, 1_000_000, 3_000_000, 6_000_000]
MAIN = ("2021-01-04", "2026-09-28")
FULL = ("2014-02-10", "2026-09-28")
SUB_PRICE = (3.0, 4.0)
N_YEARS = 3
EW_COST = 0.0015
SEGS = {
    "全样本(索引起~2026-09-28)": (None, "2026-09-28"),
    "2014-17": ("2014-01-01", "2017-12-31"),
    "2018-21": ("2018-01-01", "2021-12-31"),
    "2022-26": ("2022-01-01", "2026-12-31"),
}
# R55 §0.3 记录值(同数据版本, 等权) —— W4c 回归锚点
R55_EW_ANCHOR = {
    ("P0", "2022-26"): (0.1443, -0.2500),
    ("A1", "2022-26"): (0.1728, -0.2159),
}
# R53/R56 主窗口记录值(4 位小数: 年化/回撤/持仓率/现金%/费用%)
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


def summarize(nav: pd.Series, rows: list, aum: float) -> dict:
    m = metrics(nav / nav.iloc[0])
    d = pd.DataFrame(rows)
    tgt, hold = float(d["n_target"].mean()), float(d["n_hold"].mean())
    return {
        "年化": m["年化"],
        "回撤": m["最大回撤"],
        "夏普": m["夏普"],
        "累计": float(nav.iloc[-1] / nav.iloc[0] - 1),
        "目标只数": tgt,
        "实际持仓": hold,
        "持仓率": hold / tgt if tgt else np.nan,
        "买不起1手占比": float(d["n_1lot_short"].sum() / max(d["n_target"].sum(), 1)),
        "现金占比": float((d["cash"] / d["post_nav"]).mean()),
        "累计费用%": float(d["fee"].sum() / aum),
        "调仓次数": int(len(d)),
    }


def build_real(data: dict, mode: str) -> pd.DataFrame:
    """mode='old' = 修复前(reindex 后 ffill); 'new' = 修复后(并集 ffill + bfill)。"""
    cfg = get_config()
    close = data["close"]
    fac = pd.read_parquet(cfg.paths.round2 + "/adjust_factor.parquet")
    fac["date"] = pd.to_datetime(fac["date"])
    rf = pd.read_parquet(cfg.paths.round2 + "/raw_close_fallback.parquet")
    rf["date"] = pd.to_datetime(rf["date"])
    rd = pd.read_parquet(cfg.paths.round2 + "/raw_close_delisted.parquet")
    rd["date"] = pd.to_datetime(rd["date"])
    real = close.copy()
    for code in close.columns:
        f = fac[fac["code"] == code]
        if len(f):
            s = f.set_index("date")["foreAdjustFactor"]
            s = s[~s.index.duplicated()].sort_index()
            if mode == "old":
                fac_ser = s.reindex(close.index).ffill().fillna(1.0)
            else:
                fac_ser = (
                    s.reindex(close.index.union(s.index))
                    .ffill()
                    .reindex(close.index)
                    .bfill()
                    .fillna(1.0)
                )
            real[code] = close[code] / fac_ser
        elif code in set(rf["code"]):
            real[code] = (
                rf[rf["code"] == code]
                .set_index("date")["raw_close"]
                .reindex(close.index, method="ffill")
            )
        elif code in set(rd["code"]):
            real[code] = (
                rd[rd["code"] == code]
                .set_index("date")["raw_close"]
                .reindex(close.index, method="ffill")
            )
        else:
            real[code] = np.nan
    return real


def first_in_index_record(data: dict) -> dict:
    cfg = get_config()
    close = data["close"]
    fac = pd.read_parquet(cfg.paths.round2 + "/adjust_factor.parquet")
    fac["date"] = pd.to_datetime(fac["date"])
    out = {}
    for code, f in fac.groupby("code"):
        s = f.set_index("date")["foreAdjustFactor"].sort_index()
        s = s[~s.index.duplicated()]
        s = s[s.index >= close.index[0]]
        if len(s) and code in close.columns:
            out[code] = s.index[0]
    return out


def seg_metrics(nav: pd.Series, start: str | None, end: str) -> dict:
    seg = nav.loc[start:end] if start else nav.loc[:end]
    m = metrics(seg / seg.iloc[0])
    m["累计"] = float(seg.iloc[-1] / seg.iloc[0] - 1)
    return m


def main() -> int:
    load_config(None)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    t0 = time.time()
    print("== Round 57: 真实价 因子前向填充 bug 修复验证 ==")
    data = r41.load_data()
    close = data["close"]
    real_new = data["real"]
    real_old = build_real(data, "old")
    fr = first_in_index_record(data)
    print(
        f"数据就绪 {time.time() - t0:.0f}s | close {close.shape} | 有索引内因子记录 {len(fr)} 只"
    )

    # ---------- W1 修复精确性 ----------
    print("\n=== W1 修复精确性 ===")
    a_new, a_old = real_new.to_numpy(dtype=float), real_old.to_numpy(dtype=float)
    changed = ~np.isclose(a_new, a_old, rtol=0, atol=1e-9, equal_nan=True)
    pre = np.zeros_like(changed)
    cols = {c: i for i, c in enumerate(close.columns)}
    for code, d0 in fr.items():
        pre[close.index < d0, cols[code]] = True
    beyond = int((changed & ~pre).sum())
    n_changed = int(changed.sum())
    print(
        f"  改动 stock-days: {n_changed:,} / {changed.size:,} ({n_changed / changed.size:.2%})"
    )
    print(
        f"  W1a 改动 ⊂ {{t < 索引内首条因子记录日}}: {'✅' if beyond == 0 else '❌'}（越界 {beyond}）"
    )
    ge = np.zeros_like(changed)
    for code, d0 in fr.items():
        ge[close.index >= d0, cols[code]] = True
    dmax = float(np.nanmax(np.abs(np.where(ge, a_new - a_old, 0.0))))
    print(
        f"  W1b t≥fr 逐位相同: {'✅' if dmax == 0 else '❌'}（最大绝对差 {dmax:.3e}）"
    )
    ratio = (a_new[changed] / a_old[changed]).astype(float)
    yr_idx = close.index.year.to_numpy()
    post16 = changed & (yr_idx[:, None] >= 2016)
    ratio16 = (a_new[post16] / a_old[post16]).astype(float)
    q = np.percentile(ratio[np.isfinite(ratio)], [10, 50, 90])
    q16 = np.percentile(ratio16[np.isfinite(ratio16)], [10, 50, 90])
    print(
        f"  W1c 比率=1/factor: 全体 p10/p50/p90 = {q[0]:.3f}/{q[1]:.3f}/{q[2]:.3f} | "
        f"2016 后 {int(post16.sum()):,} 个 p10/p50/p90 = {q16[0]:.3f}/{q16[1]:.3f}/{q16[2]:.3f}"
    )

    # ---------- W2 切换日不再有假跳跃 ----------
    print(
        "\n=== W2 索引内首条因子记录日 (fr) 的当日 |Δreal| ===  [判据设计有误, 仅报告]"
    )
    rn, ro = real_new.pct_change(), real_old.pct_change()
    dn, do = [], []
    for code, d0 in fr.items():
        pos = int(close.index.searchsorted(d0))
        if 1 <= pos < len(close.index):
            dt = close.index[pos]  # fr 非交易日 → 取其后首个交易日
            a = rn.at[dt, code] if dt in rn.index else np.nan
            b = ro.at[dt, code] if dt in ro.index else np.nan
            if np.isfinite(a):
                dn.append(abs(a))
            if np.isfinite(b):
                do.append(abs(b))
    dn, do = np.array(dn), np.array(do)
    ok = float((dn <= 0.11).mean())
    print(
        f"  修复后 |Δ|≤11% 占比 {ok:.2%}（{len(dn)} 只）→ W2 {'✅' if ok >= 0.99 else '❌'}（判据 ≥99%）"
    )
    print(
        f"  修复前同口径 |Δ|≤11% 占比 {float((do <= 0.11).mean()):.2%}（对照, 应显著更低）"
    )
    print(
        "  [说明] fr 当日即除权日: 10送10 的真实价当日腰斩属正常（真实收益 = 前复权 close 比值，\n"
        "         与修复无关）→ |Δreal|≤11% 不能判「假跳跃」；该判据作废，修复有效性由 W1/W3/W6 承载"
    )

    # ---------- W3 数据质量 ----------
    print("\n=== W3 非因子变动日 |Δreal| > 12% 占比 ===")
    cfg = get_config()
    fac = pd.read_parquet(cfg.paths.round2 + "/adjust_factor.parquet")
    fac["date"] = pd.to_datetime(fac["date"])
    w3_ok = False
    for name, rr in (("修复前", ro), ("修复后", rn)):
        fpanel = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for code, _d0 in fr.items():
            s = (
                fac[fac["code"] == code]
                .set_index("date")["foreAdjustFactor"]
                .sort_index()
                .reindex(close.index.union(fac[fac["code"] == code]["date"]))
                .ffill()
                .reindex(close.index)
                .bfill()
                .fillna(1.0)
            )
            fpanel[code] = s
        chg = (fpanel != fpanel.shift(1)).to_numpy()
        vals = rr.to_numpy(dtype=float)
        mask = (~chg) & np.isfinite(vals)
        share = float((np.abs(vals[mask]) > 0.12).sum() / mask.sum())
        print(f"  {name}: {share:.4%}（判据 ≤0.1%）")
        if name == "修复后":
            w3_ok = share <= 0.001
    print(f"  W3 {'✅' if w3_ok else '❌'}")

    # ---------- W4 入池与年代结论重算 ----------
    print("\n=== W4 等权口径: 入池变化 + 年代重算 ===")
    data_old = dict(data)
    data_old["real"] = real_old
    _cache: dict = {}
    orig_build = r41.build_sets

    def cached_build(d, *a, **kw):
        key = (kw.get("low_vol_keep"), id(d))
        if key not in _cache:
            _cache[key] = orig_build(d, *a, **kw)
        return _cache[key]

    ret = r41.ret_matrix(close, data["out_date"], "zero")
    outs = {}
    for tag, dd in (("新(修复后)", data), ("旧(修复前)", data_old)):
        for keep, lab in ((None, "P0"), (KEEP, "A1")):
            _, B, _, _, _ = cached_build(
                dd, None, sub_price=SUB_PRICE, n_years=N_YEARS, low_vol_keep=keep
            )
            nav = r41.ew_nav(ret, B, EW_COST)
            outs[(tag, lab)] = (nav, B)
    print("  逐月池规模(2013-06~2016-12, 信号月):")
    Bn_p0, Bo_p0 = outs[("新(修复后)", "P0")][1], outs[("旧(修复前)", "P0")][1]
    common = sorted(set(Bn_p0) & set(Bo_p0))
    rows = []
    for dt in common:
        if not (pd.Timestamp("2013-06-01") <= dt <= pd.Timestamp("2016-12-31")):
            continue
        n, o = Bn_p0[dt], Bo_p0[dt]
        rows.append(
            {
                "执行日": dt.date(),
                "旧": len(o),
                "新": len(n),
                "新增": len(n - o),
                "剔除": len(o - n),
            }
        )
    df_pool = pd.DataFrame(rows)
    print(
        f"    {len(df_pool)} 个月 | 池规模 旧均值 {df_pool['旧'].mean():.1f} 新均值 {df_pool['新'].mean():.1f}"
    )
    print(
        f"    变动最大月: 新增 {int(df_pool['新增'].max())} / 剔除 {int(df_pool['剔除'].max())} | "
        f"合计新增 {int(df_pool['新增'].sum())} 剔次 / 剔除 {int(df_pool['剔除'].sum())} 剔次"
    )
    print("\n  年代指标(等权, 含 15bp 成本):")
    print(f"  {'口径':<10}{'段':<24}{'年化':>9}{'回撤':>9}{'累计':>10}")
    res = {}
    for lab in ("P0", "A1"):
        for tag in ("新(修复后)", "旧(修复前)"):
            nav = outs[(tag, lab)][0]
            for sname, (s, e) in SEGS.items():
                m = seg_metrics(nav, s, e)
                res[(tag, lab, sname)] = m
                print(
                    f"  {tag[:2] + '-' + lab:<10}{sname:<24}{m['年化']:>+9.2%}"
                    f"{m['最大回撤']:>+9.2%}{m['累计']:>+10.2%}"
                )
    w4c = []
    for (lab, sname), (an, ddn) in R55_EW_ANCHOR.items():
        m = res[("新(修复后)", lab, sname)]
        ok4 = abs(m["年化"] - an) <= 0.001 and abs(m["最大回撤"] - ddn) <= 0.001
        w4c.append(ok4)
        print(
            f"  W4c {lab} {sname}: 重算 {m['年化']:+.2%}/{m['最大回撤']:+.2%} vs R55 记录 "
            f"{an:+.2%}/{ddn:+.2%} → {'✅' if ok4 else '❌'}"
        )
    w4c_ok = all(w4c)

    # ---------- W5/W6 份额级 ----------
    print("\n=== W5 主窗口份额级回归 (2021-01-04→2026-09-28) ===")
    # 注入已加载数据(引擎逻辑未改; R56-V1 已证该路径与生产账本逐位一致)
    sys.modules["scripts.p3.scenario_ytd_p3"].load_data_p3 = lambda: data
    summary_hdr = (
        f"  {'账户':>6} | {'变体':>4} | {'年化':>8} | {'记录':>8} | {'Δ':>8} | "
        f"{'回撤':>8} | {'记录':>8} | {'持仓率':>7} | {'现金%':>7} | {'费用%':>7}"
    )

    def run_window(start: str, end: str, aums: list, keep: float | None) -> dict:
        detail: list = []
        navs = run_scenario_p3(
            start,
            end,
            out_prefix=None,
            verbose=False,
            aums=aums,
            low_vol_keep=keep,
            low_vol_window=WINDOW,
            detail=detail,
        )
        out = {}
        for a in aums:
            tag = f"aum{int(a / 1e4)}w"
            out[a] = (navs[tag], [r for r in detail if r["aum"] == a])
        return out

    print(summary_hdr)
    s_main = {
        None: run_window(*MAIN, AUMS8, None),
        KEEP: run_window(*MAIN, AUMS8, KEEP),
    }
    w5_ok, w5_dmax = True, 0.0
    for keep, lab in ((None, "S0"), (KEEP, "S1")):
        for aum in AUMS8:
            m = summarize(*s_main[keep][aum], aum)
            rec = R53_MAIN[(aum, lab)]
            d = max(
                abs(m["年化"] - rec[0]),
                abs(m["回撤"] - rec[1]),
                abs(m["持仓率"] - rec[2]),
            )
            w5_dmax = max(w5_dmax, d)
            if d > 1e-4:
                w5_ok = False
            print(
                f"  {int(aum / 1e4):>4}万 | {lab:>4} | {m['年化']:>+8.2%} | {rec[0]:>+8.2%} | "
                f"{m['年化'] - rec[0]:>+8.2%} | {m['回撤']:>+8.2%} | {rec[1]:>+8.2%} | "
                f"{m['持仓率']:>7.3f} | {m['现金占比']:>7.1%} | {m['累计费用%']:>7.2%}"
            )
    print(
        f"  W5 {'✅' if w5_ok else '❌'}（与 R53/R56 记录值最大偏差 {w5_dmax:.2e}, 判据 ≤1e-4）"
    )

    print("\n=== W6 全样本份额级 (2014-02-10→2026-09-28) ===")
    s_full = {
        None: run_window(*FULL, AUMS8, None),
        KEEP: run_window(*FULL, AUMS8, KEEP),
    }
    ew_full = r41.ew_nav(ret, Bn_p0, EW_COST)
    print(
        f"  {'账户':>6} | {'变体':>4} | {'年化':>8} | {'回撤':>8} | {'夏普':>5} | {'目标/实际':>10} | "
        f"{'持仓率':>7} | {'买不起1手':>9} | {'现金%':>7} | {'费用%':>7}"
    )
    mfull = {}
    for keep, lab in ((None, "S0"), (KEEP, "S1")):
        for aum in AUMS8:
            m = summarize(*s_full[keep][aum], aum)
            mfull[(aum, lab)] = m
            print(
                f"  {int(aum / 1e4):>4}万 | {lab:>4} | {m['年化']:>+8.2%} | {m['回撤']:>+8.2%} | "
                f"{m['夏普']:>5.2f} | {m['目标只数']:>4.1f}/{m['实际持仓']:>4.1f} | "
                f"{m['持仓率']:>7.1%} | {m['买不起1手占比']:>9.2%} | {m['现金占比']:>7.1%} | "
                f"{m['累计费用%']:>7.2%}"
            )
    dd_tgt = mfull[(6_000_000, "S0")]["回撤"]
    w6a = -0.55 <= dd_tgt <= -0.35
    print(
        f"  W6a 600万 S0 全样本回撤 {dd_tgt:+.2%} ∈[-55%,-35%]: {'✅' if w6a else '❌'}"
    )
    nav_sh = s_full[None][6_000_000][0]
    ew_a = ew_full.reindex(nav_sh.index).dropna()
    nav_a = nav_sh.reindex(ew_a.index)
    ys, ye = {}, {}
    for y in sorted(set(nav_a.index.year)):
        a, b = nav_a[nav_a.index.year == y], ew_a[ew_a.index.year == y]
        if len(a) > 1:
            ys[y] = a.iloc[-1] / a.iloc[0] - 1
            ye[y] = b.iloc[-1] / b.iloc[0] - 1
    print(f"\n  {'年':>5} | {'份额级':>9} | {'等权':>9} | {'差':>8}")
    w6b = True
    for y in ys:
        gap = abs(ys[y] - ye[y])
        if gap > 0.05:
            w6b = False
        print(f"  {y:>5} | {ys[y]:>+9.2%} | {ye[y]:>+9.2%} | {ys[y] - ye[y]:>+8.2%}")
    print(f"  W6b 逐年 |份额级−等权| ≤5pp: {'✅' if w6b else '❌'}")
    n_ok = 0
    for aum in AUMS8:
        s0, s1 = mfull[(aum, "S0")], mfull[(aum, "S1")]
        if s1["年化"] >= s0["年化"] and s1["回撤"] >= s0["回撤"]:
            n_ok += 1
    print(
        f"  W6c S1 不劣于 S0(年化与非浅回撤同时) 账户数 {n_ok}/8（判据 ≥7）: {'✅' if n_ok >= 7 else '❌'}"
    )

    print("\n=== 汇总（预注册判据）===")
    print(
        f"  W1a {'✅' if beyond == 0 else '❌'} | W1b {'✅' if dmax == 0 else '❌'} | W2 作废(设计有误)"
        f" | W3 {'✅' if w3_ok else '❌'} | W4c {'✅' if w4c_ok else '❌'}"
        f" | W5 {'✅' if w5_ok else '❌'} | W6a {'✅' if w6a else '❌'} | W6b {'✅' if w6b else '❌'}"
        f" | W6c {'✅' if n_ok >= 7 else '❌'}"
    )
    pd.DataFrame(
        [
            {
                "账户": int(a / 1e4),
                "变体": lab,
                **{k: v for k, v in mfull[(a, lab)].items()},
            }
            for lab in ("S0", "S1")
            for a in AUMS8
        ]
    ).to_csv("tmp/r57_results.csv", index=False, encoding="utf-8-sig")
    print(f"\n明细已存 tmp/r57_results.csv | 总耗时 {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
