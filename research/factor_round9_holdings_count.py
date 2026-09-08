#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 9 持仓数量敏感度 —— 严格按 docs/factor_round9_holdings_count_plan.md v1.0。

同一全市场 R5 合成分, 改选股截断: 前 20/10/5/2% (等权, 保守口径, 比例成本)。
+ 手数可行性(A股 1手=100股) 与最低 AUM 估计。
用法: uv run python research/factor_round9_holdings_count.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days, metrics
from research.reversal_factor import build_pool, ew_nav

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
BASE = 15e-4
MIN_N = 50
MIN_IND = 5
START = "2013-06-01"
LIMIT = 0.098
CUTS = [0.20, 0.10, 0.05, 0.02]


def main() -> None:
    print("== Round 9 持仓数量敏感度 (预注册 v1.0) ==")
    d = pd.read_parquet(ROOT / "data" / "fundamental" / "full_daily.parquet")
    d["date"] = pd.to_datetime(d["date"])

    def piv(c):
        return d.pivot(index="date", columns="code", values=c).sort_index().loc[START:]

    close, amount, tst, isst = (
        piv("close"),
        piv("amount"),
        piv("tradestatus"),
        piv("isST"),
    )
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    ind = pd.read_parquet(R2 / "industry_full.parquet").set_index("code")["industry"]
    ind = ind.reindex(close.columns).dropna()
    amihud = (
        ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    )
    mom = close.shift(21) / close.shift(250) - 1.0

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    rebs = []  # {T, exec, sc(series over pool), codes(neutralizable)}
    bench_sets = {}
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
            bench_sets[exec_day] = set(codes)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = (pa + pm) / 2
        rebs.append(
            {
                "T": T,
                "exec": exec_day,
                "sc": sc,
                "pct_amihud": a.reindex(codes).rank(pct=True),
            }
        )
    print(f"调仓期数 {len(rebs)}")

    nav_bench, _ = ew_nav(ret, bench_sets, BASE)
    ann_bench = metrics(nav_bench)["年化"]
    reb_map = {rb["exec"]: rb for rb in rebs}

    def run(cut: float):
        w = pd.Series(0.0, index=ret.columns)
        navs = np.ones(len(idx))
        n_list, cold_frac = [], []
        for i, dt in enumerate(idx):
            rb = reb_map.get(dt)
            if rb is not None:
                sc = rb["sc"]
                th = sc.quantile(1 - cut)
                target = set(sc[sc >= th].index)
                n = len(target)
                new_w = pd.Series(0.0, index=ret.columns)
                if n:
                    new_w[list(target)] = 1.0 / n
                chg = (new_w - w).abs()
                cost_vec = pd.Series(BASE, index=ret.columns)
                pct = rb["pct_amihud"]
                cost_vec.loc[pct.index] = BASE + 40e-4 * pct.values  # s=40bp 口径
                reb_cost = float((chg * cost_vec).sum())
                navs[i] = navs[i - 1] * (1 + float((w * ret.loc[dt]).sum()) - reb_cost)
                w = new_w
                n_list.append(n)
                cold_frac.append(float((pct[list(target)] > 0.8).mean()) if n else 0.0)
            else:
                navs[i] = navs[i - 1] * (1 + float((w * ret.loc[dt]).sum()))
        nav = pd.Series(navs, index=idx)
        m = metrics(nav)
        excess15 = m["年化"] - ann_bench
        # 换手(单边, 用权重变动总量/年)
        tot_turn = 0.0
        w = pd.Series(0.0, index=ret.columns)
        for i, dt in enumerate(idx):
            rb = reb_map.get(dt)
            if rb is not None:
                sc = rb["sc"]
                th = sc.quantile(1 - cut)
                target = set(sc[sc >= th].index)
                new_w = pd.Series(0.0, index=ret.columns)
                if len(target):
                    new_w[list(target)] = 1.0 / len(target)
                tot_turn += float((new_w - w).abs().sum())
                w = new_w
        years = len(nav) / 244
        return {
            "N": np.mean(n_list),
            "超额@15bp": excess15,
            "超额@s40": None,
            "夏普": m["夏普"],
            "回撤": m["最大回撤"],
            "换手": tot_turn / 2 / years,
            "冷门>0.8占比": np.mean(cold_frac),
            "nav": nav,
        }

    # 额外跑 15bp 口径的 excess (s=0)
    def run15(cut: float):
        w = pd.Series(0.0, index=ret.columns)
        navs = np.ones(len(idx))
        for i, dt in enumerate(idx):
            rb = reb_map.get(dt)
            if rb is not None:
                sc = rb["sc"]
                th = sc.quantile(1 - cut)
                target = set(sc[sc >= th].index)
                new_w = pd.Series(0.0, index=ret.columns)
                if len(target):
                    new_w[list(target)] = 1.0 / len(target)
                chg = (new_w - w).abs()
                navs[i] = navs[i - 1] * (
                    1 + float((w * ret.loc[dt]).sum()) - float((chg * BASE).sum())
                )
                w = new_w
            else:
                navs[i] = navs[i - 1] * (1 + float((w * ret.loc[dt]).sum()))
        nav = pd.Series(navs, index=idx)
        return metrics(nav)["年化"] - ann_bench

    rows = []
    for cut in CUTS:
        r = run(cut)
        r["超额@15bp"] = run15(cut)
        rows.append(r)
    df = pd.DataFrame(rows)
    df.insert(0, "截断", [f"前{int(p * 100)}%" for p in CUTS])
    df["超额@s40"] = df["超额@15bp"] - (
        df["超额@15bp"] - 0
    )  # 占位, 实际用 run 的 s40 差值
    print(
        df[
            ["截断", "N", "超额@15bp", "夏普", "回撤", "换手", "冷门>0.8占比"]
        ].to_string(index=False)
    )

    # s=40 超额(重跑, 记到表)
    s40 = {}
    for cut in CUTS:
        r = run(cut)
        # run 里已经是 s40 成本, 但 excess 是相对 bench(15bp)算的 —— 需用 s40 nav 重算
        nav = r.pop("nav")
        s40[f"前{int(cut * 100)}%"] = metrics(nav)["年化"] - ann_bench
    df["超额@s40"] = df["截断"].map(s40)
    print("\n超额@s40:")
    print(df[["截断", "超额@s40"]].to_string(index=False))
    df.to_csv(OUT / "factor_round9_summary.csv", index=False)

    # ---- 手数可行性: 用最新一个月持仓 + 全期均价 ----
    # 价格代理 = qfq close; 1手=100股; 最低 AUM = p95价格 × 100 × N
    last_sc = rebs[-1]["sc"]
    px = close.loc[rebs[-1]["T"]]
    for cut in CUTS:
        th = last_sc.quantile(1 - cut)
        target = last_sc[last_sc >= th].index
        prices = px.reindex(target).dropna()
        p95 = prices.quantile(0.95)
        min_aum = p95 * 100 * len(prices)  # p95 价格位持仓 ≥1手
        print(
            f"  前{int(cut * 100)}%: N={len(prices)} 只, 价格 p95 ≈ {p95:.0f} 元, "
            f"最低 AUM(p95位≥1手) ≈ {min_aum / 1e4:.0f} 万"
        )

    # ---- 判定 ----
    base = df[df["截断"] == "前20%"].iloc[0]
    j1 = (
        df[(df["截断"].isin(["前10%", "前5%"]))]["超额@15bp"].min() >= base["超额@15bp"]
    )
    j2 = df[df["截断"] == "前5%"]["回撤"].iloc[0] <= base["回撤"] + 0.05
    j3 = df[df["截断"] == "前5%"]["换手"].iloc[0] <= base["换手"] + 2
    j4 = df[df["截断"] == "前5%"]["超额@s40"].iloc[0] >= base["超额@s40"] - 0.01
    n_pass = sum([j1, j2, j3, j4])
    print("\n== 判定 ==")
    print(f"  J1 前10%/前5% 超额@15bp≥基线: {j1}")
    print(f"  J2 前5% 回撤≤基线+5pp: {j2}")
    print(f"  J3 前5% 换手≤基线+2: {j3}")
    print(f"  J4 前5% 超额@s40≥基线-1pp: {j4}")
    print(f"  → 判定: {n_pass}/4")


if __name__ == "__main__":
    main()
