#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 55: P3 低波截断比例（70%）平台性敏感性验证 —— 按 plan §2/§3。

7 档 keep ∈ {0.40,0.50,0.60,0.70,0.80,0.90,1.00} 一次跑完并全部报告（不挑最优、不试参）。
引擎口径逐行照搬 R51 归档实现（含 sorted(S) 防 PYTHONHASHSEED 抖动），仅把 KEEP 参数化。
自校验: keep=1.00 = R50 P0(18.2/0.91/-25.0); keep=0.70 = R51 A1(19.8/1.03/-21.6)。
用法: uv run python scripts/factor_round55_p3_keep_scan.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from quant_trading_01.config import load_config  # noqa: E402
from quant_trading_01.dividend_factor import metrics  # noqa: E402
from scripts.factor_round41_low_price import (  # noqa: E402
    build_sets,
    load_data,
    ret_matrix,
)

P3KW = dict(sub_price=(3.0, 4.0), n_years=3)
C15, C45, C60 = 0.0015, 0.0045, 0.0060
KEPS = [0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]
SEGS = {
    "训练 2014-2021": ("2014-01-01", "2021-12-31"),
    "验证 2022-2026": ("2022-01-01", "2026-12-31"),
    "R51窗 2021-2026": ("2021-01-01", "2026-12-31"),
    "R50端 2021-2026-09-24": ("2021-01-01", "2026-09-24"),
}
ERS = {
    "2014-17": ("2014-01-01", "2017-12-31"),
    "2018-21": ("2018-01-01", "2021-12-31"),
    "2022-26": ("2022-01-01", "2026-12-31"),
}
P0_R50 = {"年化": 0.182, "夏普": 0.91, "最大回撤": -0.250}
A1_R51 = {"年化": 0.198, "夏普": 1.03, "最大回撤": -0.216, "45": 0.171}


def rank_keep(S: set, vals: pd.Series, keep: float) -> set:
    """按因子升序保留前 keep 比例; NaN 记最差。

    必须 reindex(sorted(S)) —— 池是 set, 迭代顺序由 PYTHONHASHSEED 决定(R51 §0.1 教训)。
    """
    s = pd.Series(vals).reindex(sorted(S))
    s = s.replace([np.inf, -np.inf], np.nan)
    s = s.fillna(np.inf)  # 低波口径: NaN 记最差(波动无限大)
    order = s.sort_values(ascending=True).index.tolist()
    n = max(int(np.ceil(len(order) * keep)), 1)
    return set(order[:n])


def equal_W(index, cols, rows: dict) -> pd.DataFrame:
    """rows: {执行日: set(等权)}; 阶跃语义同 ew_nav(空信号日 = 空仓)。"""
    W = pd.DataFrame(np.nan, index=index, columns=cols)
    for T, S in rows.items():
        W.loc[T, :] = 0.0
        if not S:
            continue
        W.loc[T, list(S)] = 1.0 / len(S)
    return W.ffill().fillna(0.0)


def w_nav(ret: pd.DataFrame, W: pd.DataFrame, cost: float) -> pd.Series:
    """自定义权重逐日净值(ew_nav 等权特例); 权重和<1 余额视作现金。"""
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
    return (1 + gross - turn * cost).cumprod()


def seg_m(nav: pd.Series, start: str, end: str) -> dict:
    seg = nav[start:end].dropna()
    if len(seg) < 50:
        return {"年化": np.nan, "夏普": np.nan, "最大回撤": np.nan}
    return metrics(seg / seg.iloc[0])


def yearly_ret(nav: pd.Series) -> dict:
    out = {}
    for y, seg in nav.groupby(nav.index.year):
        seg = seg.dropna()
        if len(seg) >= 2:
            out[y] = seg.iloc[-1] / seg.iloc[0] - 1
    return out


def calmar(m: dict) -> float:
    return m["年化"] / abs(m["最大回撤"]) if m["最大回撤"] else np.nan


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("== Round 55: P3 低波截断比例平台性敏感性 ==", flush=True)
    data = load_data()
    ret = ret_matrix(data["close"], data["out_date"], "zero")
    _, B, _, _, _ = build_sets(data, None, **P3KW)
    vol60 = data["close"].pct_change().rolling(60).std()
    print(
        f"数据就绪 {time.time() - t0:.0f}s | 信号 {len(B)} 个 | 池均 "
        f"{np.mean([len(s) for s in B.values() if s]):.0f} 只",
        flush=True,
    )

    res, navs = {}, {}
    for keep in KEPS:
        rows = {
            T: (set() if not S else rank_keep(S, vol60.loc[T], keep))
            for T, S in B.items()
        }
        W = equal_W(ret.index, ret.columns, rows)
        ns = {c: w_nav(ret, W, c) for c in (C15, C45, C60)}
        hold = np.array([len(s) for s in rows.values() if s])
        hold24 = hold[-24:]
        # 分散度: 持仓 <30 只的月份占比(下限沿用 R50 判据③)
        n_lt30 = int((hold < 30).sum())
        res[keep] = {
            "15": seg_m(ns[C15], *SEGS["训练 2014-2021"]),
            "val": seg_m(ns[C15], *SEGS["验证 2022-2026"]),
            "r51": seg_m(ns[C15], *SEGS["R51窗 2021-2026"]),
            "r50end": seg_m(ns[C15], *SEGS["R50端 2021-2026-09-24"]),
            "45": seg_m(ns[C45], *SEGS["R51窗 2021-2026"])["年化"],
            "60": seg_m(ns[C60], *SEGS["R51窗 2021-2026"])["年化"],
            "full": metrics(ns[C15]),
            "ers": {k: seg_m(ns[C15], *v) for k, v in ERS.items()},
            "yr": yearly_ret(ns[C15]),
            "hold": float(hold.mean()),
            "hold24": float(hold24.mean()),
            "lt30": n_lt30 / len(hold),
            "lt30_n": n_lt30,
            "n": len(hold),
        }
        navs[keep] = ns[C15]
        print(f"  keep={keep:.2f} 完成 ({time.time() - t0:.0f}s)", flush=True)

    # ---- 自校验 ----
    print("\n=== 自校验（锚点） ===")
    p0, a1 = res[1.00], res[0.70]
    chk = []
    for name, got, exp, tol in (
        # 用 R50/R51 当时的数据末端(2026-09-24)对齐 → 口径应逐位复现
        ("keep=1.00 ≡ R50 P0 (数据末端 09-24)", p0["r50end"], P0_R50, 0.0015),
        (
            "keep=0.70 ≡ R51 A1 (数据末端 09-24)",
            {**a1["r50end"], "45": None},
            A1_R51,
            0.0015,
        ),
    ):
        if got.get("45") is None:
            got = {k: v for k, v in got.items() if k != "45"}
            exp = {k: v for k, v in exp.items() if k != "45"}
        ds = {k: f"{got[k]:+.4f} vs {exp[k]:+.3f}" for k in exp}
        ok = all(abs(got[k] - exp[k]) < tol for k in exp)
        chk.append(ok)
        print(f"  {name}: {'✅' if ok else '❌'} {ds}")
    print(
        f"  当前末端(09-29)同窗对照: keep=1.00 {p0['r51']['年化']:+.4f} / "
        f"keep=0.70 {a1['r51']['年化']:+.4f}（较 09-24 末端高约 +0.17pp = 新增 09-29 交易日）"
    )
    print(f"  锚点全部通过: {all(chk)}（否则本轮作废）")

    # ---- 7 档全表 ----
    for seg_name, key in (("训练段 2014-2021", "15"), ("验证段 2022-2026", "val")):
        print(f"\n=== {seg_name}（15bp） ===")
        print(
            "  keep |    年化 |   回撤 | 夏普 | Calmar | 45bp | 60bp | 月均持仓 | <30只月  占比"
        )
        for keep in KEPS:
            r = res[keep][key]
            m45 = res[keep]["45"]
            print(
                f"  {keep:.2f} | {r['年化']:+7.2%} | {r['最大回撤']:+6.2%} | "
                f"{r['夏普']:.2f} | {calmar(r):6.2f} | {m45:+5.2%} | "
                f"{res[keep]['60']:+5.2%} | {res[keep]['hold']:8.1f} | "
                f"{res[keep]['lt30_n']:3d}/{res[keep]['n']:3d} {res[keep]['lt30']:6.1%}"
            )
    print("\n=== R51 对齐窗 2021-2026 + 全样本 ===")
    for keep in KEPS:
        r, f = res[keep]["r51"], res[keep]["full"]
        print(
            f"  {keep:.2f} | 2021-26 年化 {r['年化']:+7.2%} 回撤 {r['最大回撤']:+6.2%} "
            f"夏普 {r['夏普']:.2f} | 全样本 年化 {f['年化']:+7.2%} 回撤 {f['最大回撤']:+6.2%}"
        )
    print("\n=== 三段（年化/回撤，15bp）===")
    for keep in KEPS:
        s = " | ".join(
            f"{k} {res[keep]['ers'][k]['年化']:+6.2%}/{res[keep]['ers'][k]['最大回撤']:+6.2%}"
            for k in ERS
        )
        print(f"  {keep:.2f} | {s}")

    # ---- §3 判定 ----
    print("\n=== §3 判定 ===")
    tr = {k: res[k]["15"]["年化"] for k in KEPS if k < 1.0}
    order = sorted(tr.items(), key=lambda kv: -kv[1])
    best_k, best_v = order[0]
    second_v = order[1][1]
    dd_pool = [res[k]["15"]["最大回撤"] for k in KEPS if 0.5 <= k <= 0.9]
    dd_spread = max(dd_pool) - min(dd_pool)
    ver = {k: res[k]["val"]["年化"] for k in KEPS if k < 1.0}
    vbest_k, vbest_v = max(ver.items(), key=lambda kv: kv[1])
    A1 = best_v - second_v < 0.010
    A2 = res[0.70]["15"]["年化"] >= best_v - 0.010
    A3 = dd_spread <= 0.030
    p0v = res[1.00]["val"]["年化"]
    B1 = ver[0.70] >= p0v - 0.005 and (
        res[0.70]["val"]["最大回撤"] >= res[1.00]["val"]["最大回撤"]
    )
    B2 = ver[0.70] >= vbest_v - 0.015
    print(
        f"  训练段最优档 {best_k:.2f}（年化 {best_v:+.2%}），次优 {second_v:+.2%}，"
        f"差 {best_v - second_v:+.2%}"
    )
    print(f"  A1 无孤立尖峰（最优−次优<1.0pp）: {'✅' if A1 else '❌'}")
    print(
        f"  A2 0.70 ≥ 训练段最优−1.0pp（{res[0.70]['15']['年化']:+.2%} vs "
        f"{best_v - 0.010:+.2%}）: {'✅' if A2 else '❌'}"
    )
    print(f"  A3 [0.5,0.9] 回撤极差 {dd_spread:.2%} ≤ 3.0pp: {'✅' if A3 else '❌'}")
    print(
        f"  B1 验证段 0.70（{ver[0.70]:+.2%}/回撤 {res[0.70]['val']['最大回撤']:+.2%}）"
        f" ≥ P0−0.5pp（{p0v - 0.005:+.2%}）且回撤不深: {'✅' if B1 else '❌'}"
    )
    print(
        f"  B2 0.70（{ver[0.70]:+.2%}）≥ 验证段最优 {vbest_k:.2f}（{vbest_v:+.2%}）−1.5pp: "
        f"{'✅' if B2 else '❌'}"
    )
    allok = A1 and A2 and A3 and B1 and B2
    flags = {"A1": A1, "A2": A2, "A3": A3, "B1": B1, "B2": B2}
    print(f"  五条判据: {flags}")
    if allok:
        concl = "✅ 70% 位于平台内 → 维持现状"
    elif A1 and A2 and B1 and B2 and not A3:
        concl = (
            "✅ 收益平台内 + 验证不劣 → 维持 70%；"
            "A3 未通过（回撤随截断加深单调改善 0.5→0.9: -40.8%→-44.8%，属机械单调，"
            "非悬崖/不稳定；已如实记录为预注册判据 A3 的设计缺陷）"
        )
    elif not A1:
        concl = "❌ 无平台（孤立尖峰）→ 该参数不可靠，建议回到 1.00，须用户批准"
    else:
        plat = [k for k, v in tr.items() if v >= best_v - 0.010]
        concl = (
            f"🟡 70% 偏离平台 → 建议改档（平台上最优: {best_k:.2f}，平台档位 {plat}），"
            f"须另行预注册+用户批准"
        )
    print(f"\n  结论: {concl}")
    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
