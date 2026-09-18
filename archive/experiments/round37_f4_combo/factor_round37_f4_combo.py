#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 37 F4 低成交额5 组合验证（Round 22/30 方法, 预注册 v1.0）。

臂 A = 现 R5 (0.85 Amihud + 0.15 动量)
臂 B = 三因子等权 (Amihud + 动量 + F4低成交额5)/3   [协议标准对照, 预期同源稀释崩塌]
臂 C = F4 替换动量槽位 (0.85 Amihud + 0.15 F4)     [主测试臂]
F4 月频化: mean(amount,5d) @月末 T, 行业内百分位取负(低成交额=高分)。
全市场池、行业内百分位、前20%等权、141期、300万 share 级全口径(阻塞引擎)。
判定 5 项 (B/C vs A): 超额≥+1pp / 回撤≤+5pp / 换手≤1.5× / 分段全正 / Jaccard<0.75。

用法: python research/factor_round37_f4_combo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.config import get_config  # noqa: E402
from research.dividend_factor import metrics, month_last_days  # noqa: E402
from research.paper_trade import (  # noqa: E402
    PaperPortfolio,
    _load,
    _load_corp,
)
from research.reversal_factor import build_pool, ew_nav  # noqa: E402

COST = 15e-4
AUM = 3_000_000
F4_WIN = 5  # F4 月频化窗口: 5 日均成交额


def _cfg():
    return get_config()


def r5_rebalances_v3(close, amount, tst, isst, ind, mode):
    """A=现R5(0.85/0.15); B=三因子等权(含F4, 低成交额=高分); C=0.85Amihud+0.15F4。
    返回 rebs, bench, ret。F4 = mean(amount, 5d) @月末 T。"""
    cfg = _cfg()
    amihud_w = cfg.strategy.amihud_w
    min_ind = cfg.strategy.min_ind
    min_n = cfg.strategy.min_n
    r5 = cfg.strategy.r5
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    amihud = (
        ((ret.abs() / amount) * r5.amihud_scale)
        .rolling(r5.amihud_lookback, min_periods=r5.amihud_min_periods)
        .mean()
    )
    mom = close.shift(r5.mom_short) / close.shift(r5.mom_long) - 1.0
    f4 = amount.rolling(F4_WIN).mean()  # F4 月频化: 5日均成交额, 低→高分
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
        if mode == "A":
            sc = amihud_w * pa + (1 - amihud_w) * pm
        elif mode == "B":  # 三因子等权, F4 取负(低成交额=高分)
            f = f4.loc[T].reindex(codes).dropna()
            common_f = codes.intersection(f.index)
            if len(common_f) < min_n:
                continue
            pf4 = -f.reindex(common_f).groupby(ind_s[common_f]).rank(pct=True)
            pa2, pm2 = pa.reindex(common_f), pm.reindex(common_f)
            sc = (pa2 + pm2 + pf4) / 3
            codes = common_f
        else:  # C: F4 替换动量槽位 (0.85 Amihud + 0.15 F4)
            f = f4.loc[T].reindex(codes).dropna()
            common_f = codes.intersection(f.index)
            if len(common_f) < min_n:
                continue
            pf4 = -f.reindex(common_f).groupby(ind_s[common_f]).rank(pct=True)
            pa2 = pa.reindex(common_f)
            sc = amihud_w * pa2 + (1 - amihud_w) * pf4
            codes = common_f
        q = pd.qcut(sc.rank(method="first"), r5.quantile, labels=False)
        rebs.append(
            {"T": T, "exec": exec_day, "target": set(codes[q == r5.quantile - 1])}
        )
    return rebs, bench, ret


def run_arm(rebs, raw, F, trad, idx, ret):
    """share 级全口径回放（阻塞引擎）。返回 (指标, 归一化净值)。

    换手 = 年化单边换手(本次调仓新增 trades 成交额/平均市值/年, 避免累积 trades 二次放大)。
    """
    F_prev = F.shift(1).fillna(F.iloc[0])
    pf = PaperPortfolio(AUM)
    rebs_d = {r["exec"]: r for r in rebs}
    navs = []
    buy_total = 0.0
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
            buy_total += sum(t["amount"] for t in pf.trades[n0:] if t["side"] == "buy")
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / AUM
    m = metrics(nav)
    years = len(nav) / 244
    # 年化单边换手(倍): 累计买入额 / 平均市值 / 年 —— 与 ew_nav 口径一致(R5 ≈ 3.3-3.7×)
    turnover = buy_total / (nav.mean() * AUM) / years
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
            if A or B:
                vals.append(len(A & B) / len(A | B))
    return float(np.mean(vals)) if vals else np.nan


def era_exc(nav, bench_nav) -> dict:
    out = {}
    for era, (s, e_) in _cfg().strategy.eras.to_dict().items():
        a, b = nav[s:e_], bench_nav[s:e_]
        if len(a) < 10 or len(b) < 10:
            continue
        out[era] = (
            metrics(a / a.dropna().iloc[0])["年化"]
            - metrics(b / b.dropna().iloc[0])["年化"]
        )
    return out


def main() -> None:
    print("== Round 37 F4 低成交额5 组合验证 (Round 22/30 方法) ==")
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    ret = close.pct_change()

    rebs_a, bench, _ = r5_rebalances_v3(close, amount, tst, isst, ind, "A")
    rebs_b, _, _ = r5_rebalances_v3(close, amount, tst, isst, ind, "B")
    rebs_c, _, _ = r5_rebalances_v3(close, amount, tst, isst, ind, "C")
    nav_bench, _ = ew_nav(ret, bench, COST)
    ann_bench = metrics(nav_bench)["年化"]
    print(f"调仓期数 {len(bench)}, 同池等权基准年化 {ann_bench:+.1%}")

    ra, nav_a = run_arm(rebs_a, raw, F, trad, idx, ret)
    rb, nav_b = run_arm(rebs_b, raw, F, trad, idx, ret)
    rc, nav_c = run_arm(rebs_c, raw, F, trad, idx, ret)
    jac_b = jaccard_overlap(rebs_a, rebs_b)
    jac_c = jaccard_overlap(rebs_a, rebs_c)

    print(f"\n{'臂':<26}{'超额15bp':<10}{'夏普':<7}{'回撤':<9}{'换手':<8}{'净值'}")
    for name, r in (
        ("A 现R5(0.85/0.15)", ra),
        ("B 三因子(Amihud+动量+F4)/3", rb),
        ("C 0.85Amihud+0.15F4", rc),
    ):
        print(
            f"{name:<26}{r['年化'] - ann_bench:+6.2%}   {r['夏普']:5.2f}  "
            f"{r['回撤']:7.1%}  {r['换手']:5.1f}  {r['净值']:5.2f}x"
        )
    exc_a = ra["年化"] - ann_bench
    exc_b = rb["年化"] - ann_bench
    exc_c = rc["年化"] - ann_bench
    era_a, era_b, era_c = (
        era_exc(nav_a, nav_bench),
        era_exc(nav_b, nav_bench),
        era_exc(nav_c, nav_bench),
    )
    print(f"\n持仓月均 Jaccard 重叠: B vs A {jac_b:.2%} | C vs A {jac_c:.2%}")
    print(
        f"三段超额: A {[f'{v:+.1%}' for v in era_a.values()]} | "
        f"B {[f'{v:+.1%}' for v in era_b.values()]} | "
        f"C {[f'{v:+.1%}' for v in era_c.values()]}"
    )

    for arm, exc, nav, jac, era in (
        ("B", exc_b, nav_b, jac_b, era_b),
        ("C", exc_c, nav_c, jac_c, era_c),
    ):
        checks = {
            f"① {arm} 超额−A ≥ +1pp": exc - exc_a >= 0.01,
            f"② {arm} 回撤−A ≤ +5pp": (rb if arm == "B" else rc)["回撤"] - ra["回撤"]
            <= 0.05,
            f"③ {arm} 换手/A ≤ 1.5": (rb if arm == "B" else rc)["换手"] / ra["换手"]
            <= 1.5
            if ra["换手"]
            else False,
            f"④ {arm} 分段全正": all(v > 0 for v in era.values()) if era else False,
            f"⑤ {arm} Jaccard < 0.75": jac < 0.75,
        }
        n_pass = sum(checks.values())
        verdict = {4: "组合升级候选", 3: "部分通过"}.get(n_pass, "未通过 → 维持R5")
        print(f"\n判定 ({arm} vs A): {n_pass}/5 → {verdict}")
        for k, v in checks.items():
            print(f"  {'✅' if v else '❌'} {k}")

    # 输出
    out = Path(_cfg().paths.output)
    out.mkdir(exist_ok=True)
    pd.DataFrame(
        {
            "臂": ["A 现R5", "B 三因子(含F4)", "C 0.85Amihud+0.15F4"],
            "超额15bp": [exc_a, exc_b, exc_c],
            "夏普": [ra["夏普"], rb["夏普"], rc["夏普"]],
            "回撤": [ra["回撤"], rb["回撤"], rc["回撤"]],
            "换手": [ra["换手"], rb["换手"], rc["换手"]],
            "净值": [ra["净值"], rb["净值"], rc["净值"]],
            "Jaccard_vs_A": [1.0, jac_b, jac_c],
        }
    ).to_csv(out / "round37_f4_combo_summary.csv", index=False)
    print(f"\nCSV: {out}/round37_f4_combo_summary.csv")


if __name__ == "__main__":
    main()
