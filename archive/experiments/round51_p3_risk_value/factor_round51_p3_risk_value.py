#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 51 P3 风险维度与未用维度因子验证 —— 按 docs/factor_round51_p3_risk_value_plan.md。

变体(预注册定死, 12 个一次跑完不试参):
  P0 基准(3.0-4.0 等权月频) / X0 中性截断对照(按 code 序保留 70%)
  A1 低波60 / A2 低特质波动率IVOL60(中证1000残差) / A3 MAX20(低) / A4 下行半方差120(低)
  B1 低PB / B2 低换手60 / B3 低PE
  C1 盈利含金量(扣非/净利润) / C2 低应计((eps-ocf_ps)/bps) / C3 波动率倒数加权(不剔标的)
  C4 波动率目标仓位(k=clip(20%/组合60日年化波动, 0.5, 1.0))
截断口径: 保留因子最优 70%; 判据: 见 plan §3; 主判验证段 2021-2026, 成本 15/45/60bp。
用法: uv run python scripts/factor_round51_p3_risk_value.py
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
IDX_CSV = "data/idx000852_daily_20140101_20260924.csv"  # 中证1000, 覆盖至 2026-09-23
TARGET_VOL, K_LO, K_HI = 0.20, 0.5, 1.0
P0_R50 = {"年化": 0.182, "夏普": 0.91, "回撤": -0.250}  # R50 同口径自校验基准


# ---------- 数据 ----------


def load_extra() -> dict:
    """turn/pb/pe 日频面板 + net_profit/eps/bps 年报面板(不改生产 load_data, 避免生产内存增长)。"""
    cfg = get_config()
    full = load_full_daily(columns=["date", "code", "turn", "pbMRQ", "peTTM"])
    full["date"] = pd.to_datetime(full["date"])
    full = full[full["date"] >= pd.Timestamp(cfg.r5.start)]
    out = {}
    for src, name in (("turn", "turn"), ("pbMRQ", "pb"), ("peTTM", "pe")):
        out[name] = full.pivot(index="date", columns="code", values=src).sort_index()
    fq = pd.read_parquet(cfg.paths.round2 + "/financial_quality.parquet")
    fq["report_date"] = pd.to_datetime(fq["report_date"])
    ann = fq[fq["report_date"].dt.month == 12].sort_values("report_date")
    for col in ("net_profit", "eps", "bps"):
        out["a_" + col] = ann.pivot_table(
            index="report_date", columns="code", values=col
        )
    return out


def index_ret(index: pd.DatetimeIndex) -> pd.Series:
    """中证1000 日收益(对齐交易日历)。"""
    d = pd.read_csv(IDX_CSV, parse_dates=["date"]).set_index("date")["close"]
    r = d.sort_index().pct_change()
    return r.reindex(index).ffill()


def factor_panels(data: dict, extra: dict, rm: pd.Series) -> dict:
    """日频因子面板(全部以 T 为滚动终点, 无前视)。"""
    r = data["close"].pct_change()
    rm = rm.reindex(r.index).ffill()
    ri_mean, rm_mean = r.rolling(60).mean(), rm.rolling(60).mean()
    ri_var = r.pow(2).rolling(60).mean() - ri_mean.pow(2)
    rm_var = rm.pow(2).rolling(60).mean() - rm_mean.pow(2)
    cov = r.mul(rm, axis=0).rolling(60).mean() - ri_mean.mul(rm_mean, axis=0)
    # rm_var 是按日的 Series → 必须按行(axis=0)对齐, 否则会错误地按列广播成全 NaN
    ivol = (ri_var - cov.pow(2).div(rm_var, axis=0)).clip(lower=0).pow(0.5)
    turn = extra["turn"].reindex(index=r.index, columns=r.columns)
    return {
        "vol60": r.rolling(60).std(),
        "max20": r.rolling(20).max(),
        "semi120": r.clip(upper=0).pow(2).rolling(120).mean().pow(0.5),
        "ivol60": ivol,
        "turn60": turn.rolling(60).mean(),
        "pb": extra["pb"].reindex(index=r.index, columns=r.columns),
        "pe": extra["pe"].reindex(index=r.index, columns=r.columns),
    }


def last_visible(panel: pd.DataFrame, T: pd.Timestamp, lag: int) -> pd.Series | None:
    """T 时点可见的最近一期年报(披露滞后 lag 天)。"""
    ok = panel.index[panel.index + pd.Timedelta(days=lag) <= T]
    return panel.loc[ok[-1]] if len(ok) else None


# ---------- 权重构造 ----------


def rank_keep(S: set, vals: pd.Series, ascending: bool) -> set:
    """按因子排序保留最优 KEEP 比例; NaN 记最差。"""
    s = pd.Series(vals).reindex(list(S))
    s = s.replace([np.inf, -np.inf], np.nan)
    s = s.fillna(np.inf if ascending else -np.inf)
    order = s.sort_values(ascending=ascending).index.tolist()
    n = max(int(np.ceil(len(order) * KEEP)), 1)
    return set(order[:n])


def equal_W(index, cols, rows: dict) -> pd.DataFrame:
    """rows: {信号日: set(等权) 或 dict(自定义权重)}。"""
    # 与 ew_nav 同语义: 信号日重设权重, 其余交易日沿用上次权重(阶跃); 空信号日 = 空仓(现金)
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
    """自定义权重逐日净值(ew_nav 为等权特例); 权重和<1 的余额视作现金(0 收益)。"""
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
    return (1 + gross - turn * cost).cumprod()


def build_rows(
    sets: dict, data: dict, panels: dict, extra: dict, lag: int, kind: str
) -> dict:
    """生成 {信号日: 权重 dict} —— 截断类给等权集合, C3 给 1/vol 权重。"""
    rows = {}
    for T, S in sets.items():
        if not S:
            rows[T] = set()  # 空信号日 = 空仓(与 ew_nav 一致)
            continue
        if kind == "x0":
            rows[T] = set(sorted(S)[: max(int(np.ceil(len(S) * KEEP)), 1)])
        elif kind == "c3":
            v = panels["vol60"].loc[T].reindex(list(S))
            inv = 1.0 / v.replace(0.0, np.nan)
            inv = inv.fillna(inv.median() if inv.notna().any() else 1.0)
            rows[T] = (inv / inv.sum()).to_dict()
        else:
            vals = _factor_at(kind, data, panels, extra, T, lag)
            rows[T] = rank_keep(S, vals, _asc(kind)) if vals is not None else set(S)
    return rows


def _asc(kind: str) -> bool:
    """True = 取因子值小者(低波/低MAX/低PB/低换手/低PE/低应计)。"""
    return kind != "c1"


def _factor_at(
    kind: str, data: dict, panels: dict, extra: dict, T: pd.Timestamp, lag: int
):
    if kind in panels:
        return panels[kind].loc[T]
    if kind == "c1":  # 盈利含金量 = 扣非/净利润(net_profit<=0 记 -1 最差)
        ded = last_visible(data["ded"], T, lag)
        npf = last_visible(extra["a_net_profit"], T, lag)
        if ded is None or npf is None:
            return None
        npf = npf.reindex(ded.index)
        score = ded / npf.where(npf > 0)
        return score.where(npf > 0, -1.0).clip(-1.0, 3.0)
    if kind == "c2":  # 低应计 = (eps - ocf_ps)/bps
        vis_e = last_visible(extra["a_eps"], T, lag)
        vis_b = last_visible(extra["a_bps"], T, lag)
        vis_c = last_visible(data["ocf"], T, lag)
        if vis_e is None or vis_b is None or vis_c is None:
            return None
        idx = vis_e.index
        bp = vis_b.reindex(idx)
        acc = (vis_e - vis_c.reindex(idx)) / bp.where(bp > 0)
        return acc.where(bp > 0, np.inf)
    return None


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


def calmar(m: dict) -> float:
    return m["年化"] / abs(m["最大回撤"]) if m["最大回撤"] else np.nan


def evaluate(navs: dict, hold: list) -> dict:
    m15, m45, m60 = val_m(navs[C15]), val_m(navs[C45]), val_m(navs[C60])
    return {
        "年化": m15["年化"],
        "夏普": m15["夏普"],
        "回撤": m15["最大回撤"],
        "45bp": m45["年化"],
        "60bp": m60["年化"],
        "calmar": calmar(m15),
        "全样本": metrics(navs[C15])["年化"],
        "持仓": float(np.mean(hold)) if hold else 0.0,
        "近年持仓": float(np.mean(hold[-24:])) if hold else 0.0,
        "yr": yearly_ret(navs[C15]),
    }


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("== Round 51 P3 风险/未用维度因子验证 ==", flush=True)
    data = load_data()
    extra = load_extra()
    ret = ret_matrix(data["close"], data["out_date"], "zero")
    panels = factor_panels(data, extra, index_ret(data["close"].index))
    A, B, C, _, _ = build_sets(data, None, **P3KW)
    lag = get_config().p3.disclose_lag
    print(
        f"数据就绪 {time.time() - t0:.0f}s | 信号 {len(B)} 个 | 池均 {np.mean([len(s) for s in B.values() if s]):.0f} 只",
        flush=True,
    )

    variants = [
        ("P0 基准", "p0"),
        ("X0 中性截断", "x0"),
        ("A1 低波60", "vol60"),
        ("A2 低IVOL60", "ivol60"),
        ("A3 低MAX20", "max20"),
        ("A4 低半方差120", "semi120"),
        ("B1 低PB", "pb"),
        ("B2 低换手60", "turn60"),
        ("B3 低PE", "pe"),
        ("C1 盈利含金量", "c1"),
        ("C2 低应计", "c2"),
        ("C3 波动率倒数加权", "c3"),
    ]
    res, navs_all, navs_p0 = {}, {}, None
    for label, kind in variants:
        rows = B if kind == "p0" else build_rows(B, data, panels, extra, lag, kind)
        W = equal_W(ret.index, ret.columns, rows)
        navs = {c: w_nav(ret, W, c) for c in (C15, C45, C60)}
        navs_all[label] = navs
        if kind == "p0":
            navs_p0 = navs
        hold = [len(s) for s in rows.values() if s]
        res[label] = evaluate(navs, hold)
        print(f"  {label} 完成 ({time.time() - t0:.0f}s)", flush=True)

    # C4 波动率目标仓位(依赖 P0 组合历史波动, 用 T 及之前数据)
    kv = (
        TARGET_VOL / (navs_p0[C15].pct_change().rolling(60).std() * np.sqrt(244))
    ).clip(K_LO, K_HI)
    rows_c4 = {
        T: (
            {}
            if not S
            else {c: (K_HI if pd.isna(kv.loc[T]) else kv.loc[T]) / len(S) for c in S}
        )
        for T, S in B.items()
    }
    W4 = equal_W(ret.index, ret.columns, rows_c4)
    navs_c4 = {c: w_nav(ret, W4, c) for c in (C15, C45, C60)}
    res["C4 波动率目标仓位"] = evaluate(navs_c4, [len(s) for s in B.values() if s])
    navs_all["C4 波动率目标仓位"] = navs_c4
    print(
        f"  C4 波动率目标仓位 完成 ({time.time() - t0:.0f}s), 平均仓位 {kv.mean():.1%}",
        flush=True,
    )

    # ---- 打印 ----
    p0, x0 = res["P0 基准"], res["X0 中性截断"]
    print("\n=== 验证段 2021-2026（15bp，P0 自校验：R50 = 18.2%/0.91/−25.0%） ===")
    for label, r in res.items():
        print(
            f"  {label:12s} 年化 {r['年化']:+.1%} | 夏普 {r['夏普']:.2f} | 回撤 {r['回撤']:.1%} | "
            f"45bp {r['45bp']:+.1%} | 60bp {r['60bp']:+.1%} | Calmar {r['calmar']:.2f} | "
            f"持仓 {r['持仓']:.0f}/{r['近年持仓']:.0f} | 全样本 {r['全样本']:+.1%}"
        )

    def dd_gain(r: dict) -> float:
        return r["回撤"] - p0["回撤"]  # 正 = 回撤更浅(改善)

    # P0 自校验: 必须复现 R50 同口径基准, 否则说明本轮 w_nav 实现有误
    dev = abs(p0["年化"] - P0_R50["年化"]) + abs(p0["回撤"] - P0_R50["回撤"])
    print(
        f"\n  [自校验] P0 = {p0['年化']:+.1%}/{p0['夏普']:.2f}/{p0['回撤']:.1%} vs "
        f"R50 {P0_R50['年化']:+.1%}/{P0_R50['夏普']:.2f}/{P0_R50['回撤']:.1%} → "
        f"{'一致 ✓' if dev <= 0.01 else '不一致 ✗ 结果不可信, 须排查'}"
    )

    print("\n=== 判定（plan §3） ===")
    for label, r in res.items():
        if label in ("P0 基准", "X0 中性截断"):
            continue
        if label.startswith("A"):
            ok = (
                dd_gain(r) >= 0.03
                and r["年化"] >= p0["年化"] - 0.01
                and r["45bp"] >= p0["45bp"] - 0.01
            )
            det = f"①回撤改善{dd_gain(r):+.1%}(需≥+3pp) ②年化{r['年化'] - p0['年化']:+.1%}(需≥-1pp) ③45bp{r['45bp'] - p0['45bp']:+.1%}(需≥-1pp)"
        elif label == "C3 波动率倒数加权":
            ok = (
                dd_gain(r) >= 0.03
                and r["年化"] >= p0["年化"]
                and r["45bp"] >= p0["45bp"]
            )
            det = f"①回撤改善{dd_gain(r):+.1%}(需≥+3pp) ②年化{r['年化'] - p0['年化']:+.1%}(需≥0) ③45bp{r['45bp'] - p0['45bp']:+.1%}(需≥0)"
        elif label == "C4 波动率目标仓位":
            ok = (
                dd_gain(r) >= 0.03
                and r["年化"] >= p0["年化"] - 0.01
                and r["45bp"] >= p0["45bp"] - 0.01
            )
            det = f"①回撤改善{dd_gain(r):+.1%}(需≥+3pp) ②年化{r['年化'] - p0['年化']:+.1%}(需≥-1pp) ③45bp{r['45bp'] - p0['45bp']:+.1%}(需≥-1pp)"
        else:  # B / C1 / C2
            wins = sum(
                1 for y in r["yr"] if y in p0["yr"] and r["yr"][y] >= p0["yr"][y]
            )
            ok = (
                (r["年化"] >= p0["年化"] + 0.02 or r["夏普"] >= p0["夏普"] + 0.10)
                # 回撤为负值: "不恶化" = 不比 P0 深 1pp 以上(plan 文字写反, 见 §0 更正记录)
                and r["回撤"] >= p0["回撤"] - 0.01
                and r["45bp"] >= p0["45bp"]
                and wins >= len(r["yr"]) / 2
            )
            det = (
                f"①年化{r['年化'] - p0['年化']:+.1%}/夏普{r['夏普'] - p0['夏普']:+.3f} "
                f"②回撤{r['回撤'] - p0['回撤']:+.1%}(需≥-1pp) ③45bp{r['45bp'] - p0['45bp']:+.1%}(需≥0) "
                f"④年胜{wins}/{len(r['yr'])}"
            )
        # X0 对照: 因子改善是否超过纯集中度效应
        beat_x0 = dd_gain(r) > max(dd_gain(x0), 0.0) or r["年化"] > x0["年化"]
        print(
            f"  {label:12s} {det} => {'通过' if ok else '未达标'}"
            f"{'（但未超过 X0 集中度对照）' if ok and not beat_x0 else ''}"
        )

    print(
        f"\n  X0 对照: 年化 {x0['年化']:+.1%}(vs P0 {x0['年化'] - p0['年化']:+.1%}) | "
        f"回撤 {x0['回撤']:.1%}(改善 {dd_gain(x0):+.1%}) | 夏普 {x0['夏普']:.2f} | 持仓 {x0['持仓']:.0f}"
    )
    # ---- 稳定性证据: 三段年化/回撤 + 分年度 ----
    print("\n=== 分段 年化/回撤（15bp, 配置 eras） ===")
    for label, navs in navs_all.items():
        cells = []
        for name, (s, e) in get_config().r5.eras.to_dict().items():
            seg = navs[C15][s:e].dropna()
            m = (
                metrics(seg / seg.iloc[0])
                if len(seg) > 50
                else {"年化": np.nan, "最大回撤": np.nan}
            )
            cells.append(f"{name} {m['年化']:+.1%}/{m['最大回撤']:.1%}")
        print(f"  {label:12s} " + " | ".join(cells))

    print("\n=== 分年度收益（%） ===")
    keys = [
        "P0 基准",
        "X0 中性截断",
        "A1 低波60",
        "A2 低IVOL60",
        "A3 低MAX20",
        "B1 低PB",
    ]
    print("  年份 | " + " | ".join(f"{k.split()[0]:>7s}" for k in keys))
    for y in sorted(p0["yr"]):
        cells = " | ".join(f"{res[k]['yr'].get(y, float('nan')):+7.1%}" for k in keys)
        print(f"  {y} | {cells}")

    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
