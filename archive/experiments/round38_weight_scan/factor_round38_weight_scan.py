#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 38 三因子权重最优配比扫描（Amihud × 动量 × F4）—— 严格按
docs/factor_round38_weight_scan_plan.md v1.0 实施（P1/P2/P3 合并复现脚本）。

P1 ew_nav 全网格粗扫(35点) → P2 share 级复核候选点 → P3 样本外验证(R28 协议)。
判定: ①w_train*网格内部 ②验证段≥A+1pp ③全区间≥A ④双侧高原<0.5pp。

用法: uv run python research/factor_round38_weight_scan.py [--share]
  --share: 额外跑 share 级复核关键点(慢, 每点~15分钟); 缺省只跑 ew_nav 粗扫+样本外。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.config import get_config  # noqa: E402
from research.dividend_factor import metrics, month_last_days  # noqa: E402
from research.paper_trade import PaperPortfolio, _load, _load_corp  # noqa: E402
from research.reversal_factor import build_pool, ew_nav  # noqa: E402

COST = 15e-4
AUM = 3_000_000
F4_WIN = 5


def _cfg():
    return get_config()


def load_factors():
    close, amount, tst, isst, ind = _load()
    ret = close.pct_change()
    r5 = _cfg().strategy.r5
    amihud = (
        ((ret.abs() / amount) * r5.amihud_scale)
        .rolling(r5.amihud_lookback, min_periods=r5.amihud_min_periods)
        .mean()
    )
    mom = close.shift(r5.mom_short) / close.shift(r5.mom_long) - 1.0
    f4 = amount.rolling(F4_WIN).mean()
    return close, amount, tst, isst, ind, ret, amihud, mom, f4


def build_rebs(close, tst, isst, ind, amihud, mom, f4, wa, wm, wf4):
    """打分 rebs + bench。返回 (rebs, bench)。"""
    cfg = _cfg()
    min_ind, min_n = cfg.strategy.min_ind, cfg.strategy.min_n
    pool = build_pool(close, tst, isst)
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
        keep = ind_s.value_counts()[ind_s.value_counts() >= min_ind].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < min_n:
            continue
        if k + 1 < len(sig_days):
            bench[exec_day] = set(codes)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        f = f4.loc[T].reindex(codes).dropna()
        common_f = codes.intersection(f.index)
        if len(common_f) < min_n:
            continue
        pf4 = -f.reindex(common_f).groupby(ind_s[common_f]).rank(pct=True)
        pa2, pm2 = pa.reindex(common_f), pm.reindex(common_f)
        sc = wa * pa2 + wm * pm2 + wf4 * pf4
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        rebs.append({"T": T, "exec": exec_day, "target": set(common_f[q == 4])})
    return rebs, bench


def seg_exc(nav, bench_nav, s, e):
    a, b = nav[s:e], bench_nav[s:e]
    if len(a) < 10 or len(b) < 10:
        return np.nan
    return (
        metrics(a / a.dropna().iloc[0])["年化"]
        - metrics(b / b.dropna().iloc[0])["年化"]
    )


def grid_points():
    grid = []
    for wm in [0.05, 0.10, 0.15, 0.20, 0.25]:
        for wf4 in [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55]:
            wa = round(1 - wm - wf4, 2)
            if wa >= 0.15:
                grid.append((wa, wm, wf4))
    return grid


def rebs_to_sets(rebs: list[dict]) -> dict:
    """rebs(list[dict]) → {exec: target set}（ew_nav 输入格式）。"""
    return {r["exec"]: r["target"] for r in rebs}


def main() -> None:
    share_flag = "--share" in sys.argv
    print("== Round 38 三因子权重最优配比扫描 (预注册 v1.0) ==")
    close, amount, tst, isst, ind, ret, amihud, mom, f4 = load_factors()
    idx = close.index
    TRAIN_S, TRAIN_E = "2014-01-01", "2021-12-31"
    VAL_S, VAL_E = "2022-01-01", None

    # ---- P1/P3: ew_nav 全网格 + 样本外 ----
    rebs_a, bench_a = build_rebs(
        close, tst, isst, ind, amihud, mom, f4, 0.85, 0.15, 0.0
    )
    q1_a = rebs_to_sets(rebs_a)
    nav_a, _ = ew_nav(ret, q1_a, COST)
    nav_b, _ = ew_nav(ret, bench_a, COST)
    exc_a = metrics(nav_a)["年化"] - metrics(nav_b)["年化"]
    exc_a_val = seg_exc(nav_a, nav_b, VAL_S, VAL_E)
    print(f"A 基线: 全区间 {exc_a:+.2%} | 验证段 {exc_a_val:+.2%}")

    grid = grid_points()
    rows = []
    for wa, wm, wf4 in grid:
        rebs_q, bench = build_rebs(close, tst, isst, ind, amihud, mom, f4, wa, wm, wf4)
        q1 = rebs_to_sets(rebs_q)
        nav_q, _ = ew_nav(ret, q1, COST)
        nav_bb, _ = ew_nav(ret, bench, COST)
        full = metrics(nav_q)["年化"] - metrics(nav_bb)["年化"]
        tr = seg_exc(nav_q, nav_bb, TRAIN_S, TRAIN_E)
        tv = seg_exc(nav_q, nav_bb, VAL_S, VAL_E)
        rows.append((wa, wm, wf4, full, tr, tv))
    df = pd.DataFrame(rows, columns=["wa", "wm", "wf4", "全区间", "训练段", "验证段"])
    print(
        f"\nP1 网格 {len(df)} 点: 全区间 {df['全区间'].min():+.2%}~{df['全区间'].max():+.2%} "
        f"(全部 > A {exc_a:+.2%})"
    )

    df_train = df.sort_values("训练段", ascending=False)
    best = df_train.iloc[0]
    wa, wm, wf4 = best["wa"], best["wm"], best["wf4"]
    print(
        f"\nP3 样本外: w_train* = A{wa:.2f}/M{wm:.2f}/F4{wf4:.2f} | "
        f"训练 {best['训练段']:+.2%} | 验证 {best['验证段']:+.2%} (vs A {best['验证段'] - exc_a_val:+.2%}pp) | "
        f"全区间 {best['全区间']:+.2%}"
    )

    # 双侧高原 (R27 修正判据): 训练段 top3 邻域
    print("双侧高原 (训练段 top3 邻域全区间波动):")
    for _, r in df_train.head(3).iterrows():
        nbr = []
        for d in [
            (0.05, -0.05),
            (-0.05, 0.05),
            (0.05, 0.0),
            (-0.05, 0.0),
            (0.0, 0.05),
            (0.0, -0.05),
        ]:
            cand = (
                round(r["wa"] + d[0], 2),
                round(r["wm"] + d[1], 2),
                round(r["wf4"] - d[0] - d[1], 2),
            )
            hit = df[(df.wa == cand[0]) & (df.wm == cand[1]) & (df.wf4 == cand[2])]
            if len(hit):
                nbr.append(hit.iloc[0]["全区间"])
        if nbr:
            spread = max(nbr) - min(nbr)
            print(
                f"  A{r['wa']:.2f}/M{r['wm']:.2f}/F4{r['wf4']:.2f}: "
                f"{min(nbr):+.2%}~{max(nbr):+.2%} 波动 {spread:.2%} "
                f"{'✅<0.5pp' if spread < 0.005 else '❌≥0.5pp'}"
            )

    # ---- P2: share 级复核 (可选) ----
    if share_flag:
        raw, F = _load_corp(close)
        trad = tst.apply(pd.to_numeric, errors="coerce") == 1
        cands = {
            "W1": (0.50, 0.05, 0.45),
            "w_train*": (0.40, 0.10, 0.50),
            "D": (0.45, 0.15, 0.40),
        }
        print("\nP2 share 级复核:")
        for name, (wa, wm, wf4) in cands.items():
            rebs, bench = build_rebs(
                close, tst, isst, ind, amihud, mom, f4, wa, wm, wf4
            )
            nav_bench, _ = ew_nav(ret, bench, COST)
            ann_bench = metrics(nav_bench)["年化"]
            F_prev = F.shift(1).fillna(F.iloc[0])
            pf = PaperPortfolio(AUM)
            rebs_d = {r["exec"]: r for r in rebs}
            navs, buy_total = [], 0.0
            for i, dt in enumerate(idx):
                prices = raw.loc[dt]
                fn, fp = F.loc[dt], F_prev.loc[dt]
                for c in list(pf.shares.keys()):
                    if fn[c] != fp[c]:
                        pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
                rb = rebs_d.get(dt)
                if rb is not None:
                    n0 = len(pf.trades)
                    pf.rebalance(rb["target"], prices, trad.loc[dt], ret.loc[dt])
                    buy_total += sum(
                        t["amount"] for t in pf.trades[n0:] if t["side"] == "buy"
                    )
                navs.append(pf.value(prices))
            nav = pd.Series(navs, index=idx) / AUM
            m = metrics(nav)
            years = len(nav) / 244
            turn = buy_total / (nav.mean() * AUM) / years
            print(
                f"  {name:<8} A{wa:.2f}/M{wm:.2f}/F4{wf4:.2f}: 超额 {m['年化'] - ann_bench:+6.2%} | "
                f"夏普 {m['夏普']:.2f} | 回撤 {m['最大回撤']:.1%} | 换手 {turn:.1f}"
            )

    out = Path(_cfg().paths.output)
    out.mkdir(exist_ok=True)
    df.to_csv(out / "round38_weight_scan_summary.csv", index=False)
    print(f"\nCSV: {out}/round38_weight_scan_summary.csv")


if __name__ == "__main__":
    main()
