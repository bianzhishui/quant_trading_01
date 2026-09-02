#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""高股息因子四组对照实验 —— 严格按 docs/dividend_factor_plan.md v1.0 实施。

四组:
  A 筛选 ∩ 名称含{爱,我,中,华} | 月度完全等权
  B 仅筛选                     | 月度完全等权     (基线)
  C 同 B                       | 成本压测 15/25/35/45bp
  D 同 B                       | 漂移式资金分配(原帖机制: 新钱等权买新标的, 旧仓不动)

核心归因读数: 名称过滤贡献 = A年化−B年化;  漂移贡献 = D年化−B年化
判定标准(预注册): ② B组月超额p<0.05  ③ B组三段每段夏普>0.3且跑赢沪深300
                  ④ C组45bp档年超额>=3%   (失败则如实归档, 禁止调参重跑)

用法: uv run python research/dividend_factor.py
"""
from __future__ import annotations

import math
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

FDIR = Path(__file__).resolve().parent.parent / "data" / "fundamental"
LOVE = "爱我中华"
BASE_COST = 15e-4                 # 基础全成本 15bp/单边
C_SWEEP = [15e-4, 25e-4, 35e-4, 45e-4]
ERAS = {"2014-2017": ("2014-01-01", "2017-12-31"),
        "2018-2021": ("2018-01-01", "2021-12-31"),
        "2022-2026": ("2022-01-01", None)}
START = "2013-06-01"              # 数据起点(2014-01首调仓, 375日计数用全历史)


def load_all() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    d = pd.read_parquet(FDIR / "daily.parquet")

    def _pivot(col: str) -> pd.DataFrame:
        x = d.pivot(index="date", columns="code", values=col).sort_index()
        x.index = pd.to_datetime(x.index)
        return x.loc[START:]

    close = _pivot("close")
    pb = _pivot("pbMRQ")
    tst = _pivot("tradestatus")
    isst = _pivot("isST")
    close = close.loc[START:]
    pb, tst, isst = pb.loc[START:], tst.loc[START:], isst.loc[START:]

    # 真实价 = 前复权价 / foreAdjustFactor(事件前向填充, 首事件前=1)
    f = pd.read_parquet(FDIR / "adjust_factor.parquet")
    real = close.copy()
    for code in close.columns:
        ev = f[f["code"] == code]
        if len(ev) == 0:
            continue
        s = ev.set_index(pd.to_datetime(ev["dividOperateDate"]))["foreAdjustFactor"]
        s = s[~s.index.duplicated()].sort_index()
        fac = s.reindex(close.index.union(s.index)).ffill().reindex(close.index)
        real[code] = close[code] / fac.fillna(1.0)

    uni = pd.read_parquet(FDIR / "universe.parquet").set_index("code")
    names = uni["name"].to_dict()
    div = pd.read_parquet(FDIR / "dividends.parquet")
    div_mat = div.pivot_table(index="code", columns="year",
                              values="cash_ps_total", fill_value=0.0)
    return close, real, pb, tst, isst, names, div_mat


def month_last_days(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    months = pd.Series(idx.to_period("M"), index=idx)
    return idx[months.shift(-1) != months]


def pick_sets(close, real, pb, tst, isst, names, div_mat) -> tuple[dict, dict]:
    """每月末信号日 → (B入选集合, A入选集合)。"""
    days_count = close.notna().cumsum()
    board_ok = pd.Series({c: not (c.startswith("bj.") or c[3:6] in {"300", "688"})
                          for c in close.columns})
    name_ok = pd.Series({c: any(ch in (names.get(c) or "") for ch in LOVE)
                         for c in close.columns})
    sig_days = month_last_days(close.index)
    B_sets, A_sets, exec_map = {}, {}, {}
    idx = close.index
    for T in sig_days:
        i = idx.get_loc(T)
        if i + 1 >= len(idx):
            break
        exec_day = idx[i + 1]                       # 次月首个交易日开盘执行
        elig = (days_count.loc[T] >= 375) & (tst.loc[T] == "1") & \
               (isst.loc[T] == "0") & board_ok & (pb.loc[T] > 0) & \
               (pb.loc[T] < 1) & real.loc[T].notna() & close.loc[T].notna()
        elig_codes = list(elig[elig].index)
        if not elig_codes:
            B_sets[exec_day] = set(); A_sets[exec_day] = set()
            exec_map[exec_day] = set()
            continue
        Y = T.year
        cols = [y for y in (Y - 3, Y - 2, Y - 1) if y in div_mat.columns]
        div3y = div_mat.reindex(elig_codes).reindex(columns=cols, fill_value=0.0).sum(axis=1)
        dy = div3y / real.loc[T][elig_codes]
        n50 = max(1, math.ceil(len(dy) / 2))
        B = set(dy.nlargest(n50).index)
        A = {c for c in B if name_ok[c]}
        B_sets[exec_day], A_sets[exec_day] = B, A
        exec_map[exec_day] = B
    return (B_sets, A_sets, exec_map)


def equal_weight_nav(px_ret: pd.DataFrame, sets: dict) -> tuple[pd.Series, float]:
    """月度完全等权: 执行日新权重生效(含踢出旧持仓), 持续到下次调仓。"""
    cols = px_ret.columns
    W = pd.DataFrame(0.0, index=px_ret.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    pending = None
    for i, dt in enumerate(px_ret.index):
        if pending is not None:                      # 信号次月首日生效
            w, pending = pending, None
        if dt in sets:                               # sets 的键就是执行日
            S = sets[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                w[list(S)] = 1.0 / len(S)
        W.iloc[i] = w
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * px_ret.fillna(0.0)).sum(axis=1)
    nav = (1 + gross - turn * BASE_COST).cumprod()
    years = len(nav) / 244
    return nav, float(turn.sum() / 2 / years)


def drift_nav(px_ret: pd.DataFrame, sets: dict, cost: float) -> tuple[pd.Series, dict]:
    """D组: 漂移式资金分配(新钱等权买新标的, 旧仓不动, 无上限)。"""
    vals: dict[str, float] = {}
    cash = 1.0
    nav, max_w, top3s, turnover = [], 0.0, [], 0.0
    r = px_ret.fillna(0.0)
    for dt in px_ret.index:
        for c in vals:                                 # 当日收益先作用于持仓
            vals[c] *= (1 + r.at[dt, c])
        if dt in sets:
            S = sets[dt]
            sold = sum(vals.pop(c, 0.0) for c in list(vals) if c not in S)
            new = [c for c in S if c not in vals]
            bought = 0.0
            if new:
                per = (cash + sold) / (len(new) * (1 + cost))
                for c in new:
                    vals[c] = per
                bought = per * len(new)
            cash = cash + sold - bought - (sold + bought) * cost
            turnover += sold + bought
        pv = cash + sum(vals.values())
        nav.append(pv)
        if vals and pv > 0:
            ws = sorted((v / pv for v in vals.values()), reverse=True)
            max_w = max(max_w, ws[0])
            if str(dt)[:7] != str(px_ret.index[max(px_ret.index.get_loc(dt) - 1, 0)])[:7]:
                top3s.append(sum(ws[:3]))
    nav = pd.Series(nav, index=px_ret.index)
    years = len(nav) / 244
    return nav, {"年换手": float(turnover / 2 / years), "最大单票权重": max_w,
                 "月末前三大均值": float(np.mean(top3s)) if top3s else 0.0}


def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    ret = nav.pct_change().dropna()
    if len(nav) < 50 or ret.std() == 0:
        return {"年化": np.nan, "夏普": np.nan, "最大回撤": np.nan, "总收益": np.nan}
    years = len(nav) / 244
    return {"总收益": nav.iloc[-1] - 1, "年化": nav.iloc[-1] ** (1 / years) - 1,
            "波动": ret.std() * np.sqrt(244),
            "夏普": ret.mean() / ret.std() * np.sqrt(244),
            "最大回撤": float((nav / nav.cummax() - 1).min())}


def monthly(nav: pd.Series) -> pd.Series:
    m = nav.groupby(nav.index.to_period("M")).last()
    return m.pct_change().dropna()


def main() -> None:
    print("== 高股息因子四组对照实验 (预注册 v1.0) ==")
    close, real, pb, tst, isst, names, div_mat = load_all()
    print(f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
          f"{close.index[0].date()} ~ {close.index[-1].date()}")

    # 前复权→真实价 校验(茅台除息日 2024-06-19 应为 ~1501)
    if "sh.600519" in real.columns:
        print(f"校验 茅台 2024-06-18 真实价: {real.at[pd.Timestamp('2024-06-18'),'sh.600519']:.1f} (预期≈1521.5)")

    ret_qfq = close.pct_change()                     # 组合收益用前复权(含分红近似)
    B_sets, A_sets, exec_map = pick_sets(close, real, pb, tst, isst, names, div_mat)
    sizes = [len(s) for s in B_sets.values() if s]
    print(f"月度入选数(B): 中位 {int(np.median(sizes))}, 范围 {min(sizes)}~{max(sizes)}; "
          f"A组月均 {np.mean([len(A_sets[k]) for k in A_sets]):.1f} 只\n")

    navB, turnB = equal_weight_nav(ret_qfq, B_sets)
    navA, turnA = equal_weight_nav(ret_qfq, A_sets)
    navD, dstats = drift_nav(ret_qfq, B_sets, BASE_COST)

    bench = load_index_daily("000300", start="20140101", refresh=False)["close"]
    bench = bench.reindex(close.index).ffill()
    bench = bench / bench.dropna().iloc[0]
    ew = (1 + ret_qfq.mean(axis=1)).cumprod()

    mB, mA, mD = metrics(navB), metrics(navA), metrics(navD)
    mBench, mEW = metrics(bench), metrics(ew)

    # ---- ② 显著性 ----
    diff = (monthly(navB) - monthly(bench)).dropna()
    t, p_welch = stats.ttest_1samp(diff, 0)
    rng = np.random.default_rng(5)
    arr = diff.to_numpy()
    p_perm = float((np.abs(rng.choice([1, -1], (10000, len(arr))).dot(arr)) / len(arr)
                    >= abs(arr.mean())).mean())

    # ---- ③ 稳定性 ----
    print("B组分年代稳定性(第③层):")
    stable = True
    for name, (s, e) in ERAS.items():
        a = navB[s:e] / navB[s:e].dropna().iloc[0]
        h = bench[s:e] / bench[s:e].dropna().iloc[0]
        ma, mh = metrics(a), metrics(h)
        ok = ma["夏普"] > 0.3 and ma["年化"] > mh["年化"]
        stable &= ok
        print(f"  {name}: B年化 {ma['年化']:+.1%} 夏普 {ma['夏普']:.2f} | "
              f"沪深300 {mh['年化']:+.1%} | 跑赢: {ma['年化'] > mh['年化']}, 夏普>0.3: {ma['夏普'] > 0.3}")

    # ---- ④ 可交易(C组45bp档): 与B同权重, 全成本改45bp ----
    cols = ret_qfq.columns
    W = pd.DataFrame(0.0, index=ret_qfq.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    pending = None
    for i, dt in enumerate(ret_qfq.index):
        if pending is not None:
            w, pending = pending, None
        if dt in B_sets:
            S = B_sets[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                w[list(S)] = 1.0 / len(S)
        W.iloc[i] = w
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    nav45 = (1 + (W.shift(1).fillna(0.0) * ret_qfq.fillna(0.0)).sum(axis=1)
             - turn * 45e-4).cumprod()
    m45 = metrics(nav45)
    excess45 = m45["年化"] - mBench["年化"]
    print(f"\nC组 45bp全成本: 年化 {m45['年化']:+.1%} (沪深300 {mBench['年化']:+.1%}) "
          f"→ 年超额 {excess45:+.1%}, 达标: {excess45 >= 0.03}")

    # ---- 汇总 ----
    print("\n== 汇总 (15bp 基础成本) ==")
    rows = []
    for label, m, tn in [("A 名称过滤", mA, turnA), ("B 基线", mB, turnB),
                         ("D 漂移式", mD, dstats["年换手"])]:
        rows.append({"组合": label, "年化": m["年化"], "夏普": m["夏普"],
                     "回撤": m["最大回撤"], "年换手": tn})
    rows.append({"组合": "沪深300", "年化": mBench["年化"], "夏普": mBench["夏普"],
                 "回撤": mBench["最大回撤"], "年换手": 0.0})
    rows.append({"组合": "等权全池", "年化": mEW["年化"], "夏普": mEW["夏普"],
                 "回撤": mEW["最大回撤"], "年换手": 0.0})
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    # ---- 归因读数 ----
    name_contrib = mA["年化"] - mB["年化"]
    drift_contrib = mD["年化"] - mB["年化"]
    print(f"\n== 归因读数 ==")
    print(f"名称过滤贡献 (A−B): {name_contrib:+.2%}/年  "
          f"→ {'噪音(|差|<1pp)' if abs(name_contrib) < 0.01 else ('央企代理成立(A>B>3pp)' if name_contrib > 0.03 else '负贡献')}")
    print(f"漂移贡献 (D−B)    : {drift_contrib:+.2%}/年  "
          f"→ {'漂移式集中是主要收益来源(>3pp)' if drift_contrib > 0.03 else '漂移贡献有限'}")
    print(f"D组集中度: 最大单票权重 {dstats['最大单票权重']:.1%}, "
          f"月末前三大均值 {dstats['月末前三大均值']:.1%}, 最大回撤 {mD['最大回撤']:.1%}")
    print(f"\n②显著性: Welch p={p_welch:.4f}, 置换 p={p_perm:.4f} → "
          f"{'通过' if p_perm < 0.05 else '未通过'}")
    print(f"③稳定性: {'通过' if stable else '未通过'}")
    print(f"④可交易: 45bp档年超额 {excess45:+.1%} → {'通过' if excess45 >= 0.03 else '未通过'}")

    # ---- 图 ----
    fig, ax = plt.subplots(figsize=(11.5, 6))
    ax.plot(navB, lw=1.5, label="B 红利基线(等权)")
    ax.plot(navD, lw=1.3, label="D 漂移式(复刻原帖机制)")
    ax.plot(navA, lw=1.1, label="A 名称过滤")
    ax.plot(bench, lw=1, alpha=0.7, label="沪深300")
    ax.plot(ew, lw=1, alpha=0.5, label="等权全池")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.set_yscale("log"); ax.legend(); ax.grid(alpha=0.3)
    ax.set_title("高股息因子四组对照 (对数净值, 15bp基础成本)")
    out = Path(__file__).resolve().parent.parent / "output" / "dividend_factor.png"
    fig.tight_layout(); fig.savefig(out, dpi=130)
    print(f"\n图已保存: {out}")


if __name__ == "__main__":
    main()
