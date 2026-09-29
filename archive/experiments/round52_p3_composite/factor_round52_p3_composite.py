#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 52 P3 池内多因子合成打分 —— 按 docs/factor_round52_p3_composite_plan.md。

合成规则(冻结): 池内百分位(低值优先, NaN 记最差) → 等权平均 → 取前 KEEP 比例 → 选中者等权。
变体(8 个一次跑完):
  Z0 基准 / Z1 低波+低PB(主判) / Z2 低波+低IVOL+低PB / Z3 低波+低MAX+低PB / Z4 四因子 /
  Z5 Z1取50% / A1 单因子低波(必须超越的门槛) / X0 中性截断(集中度对照)
主判验证段 2021-2026, 成本 15/45/60bp; 判据见 plan §3(含"不劣于 A1")。
用法: uv run python scripts/factor_round52_p3_composite.py
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
from quant_trading_01.data_io import load_full_daily  # noqa: E402
from quant_trading_01.dividend_factor import metrics  # noqa: E402
from scripts.factor_round41_low_price import (  # noqa: E402
    build_sets,
    load_data,
    ret_matrix,
)

VAL = ("2021-01-01", "2026-12-31")
P3KW = dict(sub_price=(3.0, 4.0), n_years=3)
C15, C45, C60 = 0.0015, 0.0045, 0.0060
KEEP = 0.70
IDX_CSV = "data/idx000852_daily_20140101_20260924.csv"
P0_R50 = {"年化": 0.182, "夏普": 0.91, "回撤": -0.250}


# ---------- 数据 / 因子(与 R51 同式) ----------


def load_extra() -> dict:
    cfg = get_config()
    full = load_full_daily(columns=["date", "code", "pbMRQ"])
    full["date"] = pd.to_datetime(full["date"])
    full = full[full["date"] >= pd.Timestamp(cfg.r5.start)]
    return {"pb": full.pivot(index="date", columns="code", values="pbMRQ").sort_index()}


def index_ret(index: pd.DatetimeIndex) -> pd.Series:
    d = pd.read_csv(IDX_CSV, parse_dates=["date"]).set_index("date")["close"]
    return d.sort_index().pct_change().reindex(index).ffill()


def factor_panels(data: dict, extra: dict, rm: pd.Series) -> dict:
    """日频因子面板(全部以 T 为滚动终点); 四因子方向统一为"低值优先"。"""
    r = data["close"].pct_change()
    rm = rm.reindex(r.index).ffill()
    ri_mean, rm_mean = r.rolling(60).mean(), rm.rolling(60).mean()
    ri_var = r.pow(2).rolling(60).mean() - ri_mean.pow(2)
    rm_var = rm.pow(2).rolling(60).mean() - rm_mean.pow(2)
    cov = r.mul(rm, axis=0).rolling(60).mean() - ri_mean.mul(rm_mean, axis=0)
    # rm_var 为按日 Series → 必须按行对齐(axis=0)
    ivol = (ri_var - cov.pow(2).div(rm_var, axis=0)).clip(lower=0).pow(0.5)
    return {
        "vol60": r.rolling(60).std(),
        "ivol60": ivol,
        "max20": r.rolling(20).max(),
        "pb": extra["pb"].reindex(index=r.index, columns=r.columns),
    }


# ---------- 合成打分 ----------


def pct_low(x: pd.Series) -> pd.Series:
    """低值优先的池内百分位(0-1, 越大越好); 缺失/NaN 记 0(最差)。"""
    return x.rank(ascending=False, pct=True).fillna(0.0)


def select(sets: dict, panels: dict, factors: list, keep: float) -> dict:
    """{信号日: 选中集合} —— 等权百分位合成分降序取前 keep 比例(空信号日=空仓)。

    池 S 是 set, 迭代顺序由 PYTHONHASHSEED 决定; 必须 sorted(S) 固定输入顺序,
    否则平局(NaN 记 0 后并列)会被稳定排序继承为哈希顺序 → 跨进程结果抖动
    (R51 实测全样本年化最大 ~1.3pp, 验证段稳定)。
    """
    rows = {}
    for T, S in sets.items():
        if not S:
            rows[T] = set()
            continue
        cols = sorted(S)
        sc = sum(pct_low(panels[f].loc[T].reindex(cols)) for f in factors)
        order = sc.sort_values(ascending=False, kind="stable").index.tolist()
        rows[T] = set(order[: max(int(np.ceil(len(order) * keep)), 1)])
    return rows


def equal_W(index, cols, rows: dict) -> pd.DataFrame:
    """信号日重设权重, 其余沿用(阶跃); 空信号日=空仓(与 ew_nav 同语义)。"""
    W = pd.DataFrame(np.nan, index=index, columns=cols)
    for T, S in rows.items():
        W.loc[T, :] = 0.0
        if not S:
            continue
        if isinstance(S, dict):
            W.loc[T, list(S.keys())] = list(S.values())
        else:
            W.loc[T, list(S)] = 1.0 / len(S)
    return W.ffill().fillna(0.0)


def w_nav(ret: pd.DataFrame, W: pd.DataFrame, cost: float) -> pd.Series:
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
    return (1 + gross - turn * cost).cumprod()


# ---------- 评估 ----------


def val_m(nav: pd.Series) -> dict:
    seg = nav[VAL[0] : VAL[1]].dropna()
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


def evaluate(navs: dict, hold: list) -> dict:
    m15, m45, m60 = val_m(navs[C15]), val_m(navs[C45]), val_m(navs[C60])
    return {
        "年化": m15["年化"],
        "夏普": m15["夏普"],
        "回撤": m15["最大回撤"],
        "45bp": m45["年化"],
        "60bp": m60["年化"],
        "calmar": m15["年化"] / abs(m15["最大回撤"]) if m15["最大回撤"] else np.nan,
        "全样本": metrics(navs[C15])["年化"],
        "持仓": float(np.mean(hold)) if hold else 0.0,
        "近年持仓": float(np.mean(hold[-24:])) if hold else 0.0,
        "yr": yearly_ret(navs[C15]),
    }


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("== Round 52 P3 池内多因子合成打分 ==", flush=True)
    data = load_data()
    ret = ret_matrix(data["close"], data["out_date"], "zero")
    panels = factor_panels(data, load_extra(), index_ret(data["close"].index))
    _, B, _, _, _ = build_sets(data, None, **P3KW)
    print(
        f"数据就绪 {time.time() - t0:.0f}s | 信号 {len(B)} 个 | "
        f"池均 {np.mean([len(s) for s in B.values() if s]):.0f} 只",
        flush=True,
    )

    variants = [
        ("Z0 基准", "p0", None, KEEP),
        ("X0 中性截断", "x0", None, KEEP),
        ("A1 低波60", "sel", ["vol60"], KEEP),
        ("Z1 低波+低PB", "sel", ["vol60", "pb"], KEEP),
        ("Z2 低波+IVOL+PB", "sel", ["vol60", "ivol60", "pb"], KEEP),
        ("Z3 低波+MAX+PB", "sel", ["vol60", "max20", "pb"], KEEP),
        ("Z4 四因子", "sel", ["vol60", "ivol60", "max20", "pb"], KEEP),
        ("Z5 Z1取50%", "sel", ["vol60", "pb"], 0.50),
    ]
    res, navs_all = {}, {}
    for label, mode, factors, keep in variants:
        if mode == "p0":
            rows = B
        elif mode == "x0":
            rows = {
                T: (
                    set(sorted(S)[: max(int(np.ceil(len(S) * KEEP)), 1)])
                    if S
                    else set()
                )
                for T, S in B.items()
            }
        else:
            rows = select(B, panels, factors, keep)
        W = equal_W(ret.index, ret.columns, rows)
        navs = {c: w_nav(ret, W, c) for c in (C15, C45, C60)}
        navs_all[label] = navs
        res[label] = evaluate(navs, [len(s) for s in rows.values() if s])
        print(f"  {label} 完成 ({time.time() - t0:.0f}s)", flush=True)

    p0, x0, a1 = res["Z0 基准"], res["X0 中性截断"], res["A1 低波60"]

    print("\n=== 验证段 2021-2026（15bp） ===")
    for label, r in res.items():
        print(
            f"  {label:14s} 年化 {r['年化']:+.1%} | 夏普 {r['夏普']:.2f} | 回撤 {r['回撤']:+.1%} | "
            f"45bp {r['45bp']:+.1%} | 60bp {r['60bp']:+.1%} | Calmar {r['calmar']:.2f} | "
            f"持仓 {r['持仓']:.0f}/{r['近年持仓']:.0f} | 全样本 {r['全样本']:+.1%}"
        )
    dev = abs(p0["年化"] - P0_R50["年化"]) + abs(p0["回撤"] - P0_R50["回撤"])
    print(
        f"\n  [自校验] Z0 = {p0['年化']:+.1%}/{p0['夏普']:.2f}/{p0['回撤']:.1%} vs R50 "
        f"{P0_R50['年化']:+.1%}/{P0_R50['夏普']:.2f}/{P0_R50['回撤']:.1%} → "
        f"{'一致 ✓' if dev <= 0.01 else '不一致 ✗ 须排查'}"
    )

    def dd_gain(r: dict) -> float:
        return r["回撤"] - p0["回撤"]  # 正 = 更浅

    print("\n=== 判定（plan §3；主判 = Z1） ===")
    for label in (
        "Z1 低波+低PB",
        "Z2 低波+IVOL+PB",
        "Z3 低波+MAX+PB",
        "Z4 四因子",
        "Z5 Z1取50%",
    ):
        r = res[label]
        c1 = dd_gain(r) >= 0.03
        c2 = r["年化"] >= p0["年化"] + 0.02 or r["夏普"] >= p0["夏普"] + 0.10
        c3 = r["45bp"] >= p0["45bp"]
        c4 = r["年化"] >= a1["年化"] - 0.005 and r["回撤"] >= a1["回撤"] - 0.01
        wins = sum(1 for y in r["yr"] if y in p0["yr"] and r["yr"][y] >= p0["yr"][y])
        c5 = wins >= len(r["yr"]) / 2
        c6 = dd_gain(r) > max(dd_gain(x0), 0.0) or r["年化"] > x0["年化"]
        extra = label == "Z5 Z1取50%"
        c7 = r["近年持仓"] >= 30 or not extra
        ok = all([c1, c2, c3, c4, c5, c6, c7])
        print(
            f"  {label:14s} ①回撤改善{dd_gain(r):+.1%}(≥3pp:{c1}) "
            f"②年化{r['年化'] - p0['年化']:+.1%}/夏普{r['夏普'] - p0['夏普']:+.3f}({c2}) "
            f"③45bp{r['45bp'] - p0['45bp']:+.1%}({c3}) "
            f"④vs A1 年化{r['年化'] - a1['年化']:+.1%}/回撤{r['回撤'] - a1['回撤']:+.1%}({c4}) "
            f"⑤年胜{wins}/{len(r['yr'])}({c5}) ⑥超X0({c6})"
            f"{f' ⑦持仓≥30({c7})' if extra else ''} => {'通过' if ok else '未达标'}"
        )

    print("\n=== 分段 年化/回撤（15bp） ===")
    for label in (
        "Z0 基准",
        "X0 中性截断",
        "A1 低波60",
        "Z1 低波+低PB",
        "Z3 低波+MAX+PB",
    ):
        cells = []
        for name, (s, e) in get_config().r5.eras.to_dict().items():
            seg = navs_all[label][C15][s:e].dropna()
            m = (
                metrics(seg / seg.iloc[0])
                if len(seg) > 50
                else {"年化": np.nan, "最大回撤": np.nan}
            )
            cells.append(f"{name} {m['年化']:+.1%}/{m['最大回撤']:.1%}")
        print(f"  {label:14s} " + " | ".join(cells))

    keys = ["Z0 基准", "A1 低波60", "Z1 低波+低PB", "Z3 低波+MAX+PB"]
    print("\n=== 分年度收益（%） ===")
    print("  年份 | " + " | ".join(f"{k.split()[0]:>7s}" for k in keys))
    for y in sorted(p0["yr"]):
        print(
            f"  {y} | "
            + " | ".join(f"{res[k]['yr'].get(y, float('nan')):+7.1%}" for k in keys)
        )
    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
