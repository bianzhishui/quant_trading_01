#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 30 延伸：股东户数组合验证（Round 22 方法, 预注册）。

臂 A = 现 R5 (0.85 Amihud + 0.15 动量); 臂 B = 三因子等权 (Amihud + 动量 + 股东户数)/3。
全市场池、行业内百分位、前20%等权、141期、300万 share 级全口径(阻塞引擎)。
判定 5 项(B vs A): 超额≥+1pp / 回撤≤+5pp / 换手≤1.5× / 分段全正 / 持仓Jaccard<0.75。

用法: python research/factor_round30_shareholder_combo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days  # noqa: E402
from research.paper_trade import (  # noqa: E402
    AMIHUD_W,
    MIN_IND,
    MIN_N,
    PaperPortfolio,
    _load,
    _load_corp,
    metrics,
)
from research.paper_trade import build_pool  # noqa: E402
from research.reversal_factor import ERAS, ew_nav  # noqa: E402

COST = 15e-4
AUM = 3_000_000
SH_FILE = Path("data/round2/shareholder_count.parquet")


def build_holder_rank(close: pd.DataFrame) -> pd.DataFrame:
    """股东户数增减比例宽表(date×code, 最近已公告环比%), 方向已反转(降=正分)。"""
    ann = pd.read_parquet(SH_FILE)
    ann["公告日期"] = pd.to_datetime(ann["公告日期"])
    ann["code6"] = ann["代码"].astype(str).str.zfill(6)
    ann["code_full"] = np.where(
        ann["code6"].str.startswith(("60", "68")),
        "sh." + ann["code6"],
        "sz." + ann["code6"],
    )
    ann = ann[["code_full", "公告日期", "股东户数-增减比例"]].dropna(
        subset=["股东户数-增减比例"]
    )
    fac = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    for code in close.columns:
        sub = ann[ann["code_full"] == code].sort_values("公告日期")
        if sub.empty:
            continue
        s = sub.set_index("公告日期")["股东户数-增减比例"]
        s = s[~s.index.duplicated(keep="last")].sort_index()
        fac[code] = s.reindex(close.index, method="ffill")
    return fac


def r5_rebalances_v2(close, amount, tst, isst, ind, holder, mode):
    """A=现R5(0.85/0.15); B=三因子等权(含股东户数, 户数降=高分)。返回 rebs, bench, ret。"""
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    amihud = ((ret.abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    mom = close.shift(21) / close.shift(250) - 1.0
    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    rebs, bench = [], {}
    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        exec_day = idx[idx.get_loc(T) + 1]
        a = amihud.loc[T][e].dropna()
        m = mom.loc[T][e].dropna()
        common = a.index.intersection(m.index).intersection(ind.index)
        ind_s = ind.reindex(common)
        keep = ind_s.value_counts()[ind_s.value_counts() >= MIN_IND].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < MIN_N:
            continue
        if k + 1 < len(sig_days):
            bench[exec_day] = set(codes)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        if mode == "A":
            sc = AMIHUD_W * pa + (1 - AMIHUD_W) * pm
        else:  # B: 三因子等权, 股东户数取负(降=高分)
            h = holder.loc[T].reindex(codes).dropna()
            common_h = codes.intersection(h.index)
            if len(common_h) < MIN_N:
                continue
            ph = -h.reindex(common_h).groupby(ind_s[common_h]).rank(pct=True)
            pa2, pm2 = pa.reindex(common_h), pm.reindex(common_h)
            sc = (pa2 + pm2 + ph) / 3
            codes = common_h
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        rebs.append({"T": T, "exec": exec_day, "target": set(codes[q == 4])})
    return rebs, bench, ret


def run_arm(rebs, raw, F, trad, idx, ret):
    """share 级全口径回放（阻塞引擎）。返回 (指标, 归一化净值)。"""
    F_prev = F.shift(1).fillna(F.iloc[0])
    pf = PaperPortfolio(AUM)
    rebs_d = {r["exec"]: r for r in rebs}
    navs = []
    buy_total = sell_total = 0.0
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        fn, fp = F.loc[dt], F_prev.loc[dt]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
        rb = rebs_d.get(dt)
        if rb is not None:
            pf.rebalance(rb["target"], prices, trad.loc[dt], ret.loc[dt])
            buy_total += sum(t["amount"] for t in pf.trades if t["side"] == "buy")
            sell_total += sum(t["amount"] for t in pf.trades if t["side"] == "sell")
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / AUM
    m = metrics(nav)
    years = len(nav) / 244
    turnover = (buy_total + sell_total) / 2 / (nav.mean() * AUM) / years * 100
    return (
        {
            "年化": m["年化"],
            "夏普": m["夏普"],
            "回撤": m["最大回撤"],
            "净值": nav.iloc[-1],
            "换手": turnover,
        },
        nav,
    )


def jaccard_overlap(rebs_a, rebs_b) -> float:
    d = {r["exec"]: r["target"] for r in rebs_a}
    vals = []
    for r in rebs_b:
        if r["exec"] in d:
            A, B = d[r["exec"]], r["target"]
            vals.append(len(A & B) / len(A | B))
    return float(np.mean(vals)) if vals else np.nan


def era_exc(nav, bench_nav) -> dict:
    out = {}
    for era, (s, e_) in ERAS.items():
        a, b = nav[s:e_], bench_nav[s:e_]
        if len(a) < 10 or len(b) < 10:
            continue
        out[era] = (
            metrics(a / a.dropna().iloc[0])["年化"]
            - metrics(b / b.dropna().iloc[0])["年化"]
        )
    return out


def main() -> None:
    print("== Round 30 延伸 股东户数组合验证 (Round 22 方法) ==")
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    ret = close.pct_change()
    holder = build_holder_rank(close)

    rebs_a, bench, _ = r5_rebalances_v2(close, amount, tst, isst, ind, holder, "A")
    rebs_b, _, _ = r5_rebalances_v2(close, amount, tst, isst, ind, holder, "B")
    nav_bench, _ = ew_nav(ret, bench, COST)
    ann_bench = metrics(nav_bench)["年化"]
    print(f"调仓期数 {len(bench)}, 同池等权基准年化 {ann_bench:+.1%}")

    ra, nav_a = run_arm(rebs_a, raw, F, trad, idx, ret)
    rb, nav_b = run_arm(rebs_b, raw, F, trad, idx, ret)
    jac = jaccard_overlap(rebs_a, rebs_b)

    print(f"\n{'臂':<18}{'超额15bp':<10}{'夏普':<7}{'回撤':<9}{'换手':<8}{'净值'}")
    for name, r in (("A 现R5(0.85/0.15)", ra), ("B 三因子(含股东户数)", rb)):
        print(
            f"{name:<18}{r['年化'] - ann_bench:+6.2%}   {r['夏普']:5.2f}  "
            f"{r['回撤']:7.1%}  {r['换手']:5.1f}  {r['净值']:5.2f}x"
        )
    exc_a = ra["年化"] - ann_bench
    exc_b = rb["年化"] - ann_bench
    era_a, era_b = era_exc(nav_a, nav_bench), era_exc(nav_b, nav_bench)
    print(f"\n持仓月均 Jaccard 重叠 (B vs A): {jac:.2%}")

    checks = {
        "① 超额 B-A ≥ +1pp": exc_b - exc_a >= 0.01,
        "② 回撤 B-A ≤ +5pp": rb["回撤"] - ra["回撤"] <= 0.05,
        "③ 换手 B/A ≤ 1.5": rb["换手"] / ra["换手"] <= 1.5 if ra["换手"] else False,
        "④ 分段 B 全正": all(v > 0 for v in era_b.values()) if era_b else False,
        "⑤ Jaccard < 0.75": jac < 0.75,
    }
    print("\n判定 (B vs A):")
    for k, v in checks.items():
        print(f"  {'✅' if v else '❌'} {k}")
    n_pass = sum(checks.values())
    print(
        f"\n{n_pass}/5 → {'组合升级候选(需用户决策是否改生产)' if n_pass >= 4 else '维持 R5, 股东户数不并入(诚实)'}"
    )
    print("分段超额 A: " + " ".join(f"{e}:{v:+.1%}" for e, v in era_a.items()))
    print("分段超额 B: " + " ".join(f"{e}:{v:+.1%}" for e, v in era_b.items()))


if __name__ == "__main__":
    main()
