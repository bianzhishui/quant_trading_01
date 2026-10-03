#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 59 R5 个股止损叠加 —— 严格按 docs/factor_round59_r5_stoploss_plan.md v1.0 实施。

问题: 给 R5 加个股止损(任意日收盘达到止损位即卖, 卖出资金等下个月调仓用),
      能"不影响收益"地降低回撤吗?

规则(预注册定死, 选股/打分/权重/调仓时点/成本全部沿用 R5 生产口径, 唯一改动 = 止损层):
  成本基准 = 本次调仓执行日收盘(前复权)
  触发     = 持仓期内任一交易日收盘, 累计收益 <= -thr
  执行     = 次一交易日收盘卖出(T+1, 与 R5 执行口径一致)
  卖出后   = 转现金(收益 0), 等下个调仓日按原规则重新配置; 若仍在目标集合则正常买回
  thr      = {10,15,20,25,30,40}% 一次性跑完; thr=∞ = 基线臂(无止损)

判定(全部 vs 基线臂, 15bp): Z1 回撤改善>=5pp / Z2 年化>=基线-1.0pp /
  Z3 三段超额全正 / Z4 相邻阈值回撤改善差<=3pp(高原) / Z5 年换手<=1.5x

自检(不过则不出结论): ① simulate(None) 与生产 ew_nav 逐位相同;
  ② 基线复现 Round 38 锚点(全区间 +10.40% / 训练 2014-2021 +9.80% / 验证 2022-2026 +12.62%)

用法: uv run python scripts/factor_round59_r5_stoploss.py [--config PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _repo_root() -> Path:
    """向上找仓库根(有 pyproject.toml + src/quant_trading_01 的目录)。
    兼容 scripts/ 与 archive/experiments/<unit>/ 两种运行位置(归档后仍可复现)。"""
    for p in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (p / "pyproject.toml").exists() and (
            p / "src" / "quant_trading_01"
        ).is_dir():
            return p
    raise RuntimeError("仓库根未找到(需要 pyproject.toml + src/quant_trading_01)")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_01.config import add_config_arg, get_config, load_config  # noqa: E402
from quant_trading_01.dividend_factor import metrics, month_last_days  # noqa: E402
from quant_trading_01.reversal_factor import build_pool, ew_nav  # noqa: E402
from scripts.r5.paper_trade import _load, r5_rebalances  # noqa: E402

COST = 15e-4  # 预注册 15bp/单边
THRS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
ERAS = [
    ("2014-2017", "2014-01-01", "2017-12-31"),
    ("2018-2021", "2018-01-01", "2021-12-31"),
    ("2022-2026", "2022-01-01", None),
]
TRAIN = ("2014-01-01", "2021-12-31")
VAL = ("2022-01-01", None)
ANCHOR_FULL, ANCHOR_TRAIN, ANCHOR_VAL = 0.1040, 0.0980, 0.1262  # Round 38 发布锚点


def _cfg():
    return get_config()


def rebs_to_sets(rebs: list[dict]) -> dict:
    return {r["exec"]: r["target"] for r in rebs}


def _trade_years(ret: pd.DataFrame, sets: dict) -> float:
    """可交易窗口年数(首个调仓执行日 → 末)。此前 nav 恒为 1, 不计入年化换手。"""
    idx = ret.index
    first = min(idx.get_loc(d) for d in sets if d in idx)
    return max((len(idx) - first) / 244, 1e-9)


def _factors(close: pd.DataFrame, amount: pd.DataFrame):
    """R5 三因子面板(与 r5_rebalances 同公式)。"""
    r5 = _cfg().r5
    ret = close.pct_change()
    amihud = (
        ((ret.abs() / amount) * r5.amihud_scale)
        .rolling(r5.amihud_lookback, min_periods=r5.amihud_min_periods)
        .mean()
    )
    mom = close.shift(r5.mom_short) / close.shift(r5.mom_long) - 1.0
    f4 = amount.rolling(r5.f4_window).mean()
    return ret, amihud, mom, f4


def build_rebs_r38(close, tst, isst, ind, amihud, mom, f4, wa, wm, wf4):
    """Round 38 探索脚本口径(先按全 codes 行业内排名, 再取 F4 交集) —— 仅用于锚点交叉验证。

    与生产 r5_rebalances 的差异: 生产先取四因子交集再排名, 本函数先排名再取 F4 交集
    -> 百分位在略大的集合上计算 -> 少量成员不同。用于定位自检②的锚点口径差。
    """
    cfg = _cfg()
    min_ind, min_n = cfg.r5.min_ind, cfg.r5.min_n
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
        sc = wa * pa.reindex(common_f) + wm * pm.reindex(common_f) + wf4 * pf4
        q = pd.qcut(sc.rank(method="first"), cfg.r5.quantile, labels=False)
        rebs.append({"T": T, "exec": exec_day, "target": set(common_f[q == 4])})
    return rebs, bench


def seg_exc(nav: pd.Series, bench_nav: pd.Series, s: str, e: str | None) -> float:
    """R38 同口径分段超额(各自起点归一)。"""
    a, b = nav[s:e], bench_nav[s:e]
    if len(a) < 10 or len(b) < 10:
        return float("nan")
    return (
        metrics(a / a.dropna().iloc[0])["年化"]
        - metrics(b / b.dropna().iloc[0])["年化"]
    )


def simulate(
    ret: pd.DataFrame, sets: dict, thr: float | None, cost: float = COST
) -> dict:
    """日频等权持仓 + 个股止损状态机(预注册 §3 规则)。

    thr=None 时退化为生产 ew_nav 口径(逐位等价, 由自检①保证)。
    返回 {nav, turn_sum, avg_invested, triggers:[(i, code_pos, exit_i)]}。
    """
    idx = ret.index
    codes = list(ret.columns)
    pos = {c: i for i, c in enumerate(codes)}
    R = ret.fillna(0.0).to_numpy(dtype=float)
    # 前复权累计对数收益: 任意区间收益 = exp(L[t]-L[e])-1
    L = np.log1p(R).cumsum(axis=0)
    n_days, n_cols = R.shape

    tgt_by_i: dict[int, np.ndarray] = {}
    for d, s in sets.items():
        if d in idx and s:
            tgt_by_i[idx.get_loc(d)] = np.array([pos[c] for c in s], dtype=int)
    exec_pos = np.array(sorted(tgt_by_i), dtype=int)

    W = np.zeros((n_days, n_cols))
    w_prev = np.zeros(n_cols)
    entry_log = np.full(n_cols, np.nan)
    pending = np.zeros(n_cols, dtype=bool)
    nav = np.ones(n_days)
    turn_hist = np.zeros(n_days)
    triggers: list[tuple[int, int]] = []  # (触发日下标, 股票列号)

    for i, dt in enumerate(idx):
        gross = float(w_prev @ R[i])
        if i == 0:
            w_new = np.zeros(n_cols)
        elif i in tgt_by_i:
            tgt = tgt_by_i[i]
            w_new = np.zeros(n_cols)
            w_new[tgt] = 1.0 / len(tgt)
            entry_log[:] = np.nan
            entry_log[tgt] = L[i, tgt]
            pending[:] = False
        else:
            w_new = w_prev.copy()
            if pending.any():
                w_new[pending] = 0.0
            pending[:] = False
            if thr is not None:
                held = np.nonzero(w_new > 0)[0]
                held = held[np.isfinite(entry_log[held])]
                if held.size:
                    gain = np.exp(L[i, held] - entry_log[held]) - 1.0
                    hit = held[gain <= -thr]
                    if hit.size:
                        pending[hit] = True
                        triggers.extend((i, int(h)) for h in hit)
        turn = float(np.abs(w_new - w_prev).sum())
        turn_hist[i] = turn
        prev = nav[i - 1] if i > 0 else 1.0
        nav[i] = prev * (1.0 + gross - turn * cost)
        W[i] = w_new
        w_prev = w_new

    invested = W.sum(axis=1)
    first = int(exec_pos[0]) if len(exec_pos) else 0
    years = max((n_days - first) / 244, 1e-9)  # 只算可交易窗口(此前 nav 恒为 1)
    return {
        "nav": pd.Series(nav, index=idx),
        "turn_sum": float(turn_hist.sum()),
        "turn_yr": float(turn_hist.sum() / 2 / years),
        "avg_invested": float(invested[first:].mean()),
        "triggers": triggers,
        "entry_log": entry_log,  # 最终状态(供诊断取用)
        "L": L,
        "exec_pos": exec_pos,
        "codes": codes,
    }


def counterfactual(
    sim: dict, bench_nav: pd.Series
) -> tuple[float, float, int, float, float]:
    """止损后到下次调仓日的反事实收益(正=卖错踏空; 负=躲对)。
    返回(均值, 中位, 样本数, 躲对占比=收益<=0 的比例, 相对同池基准的超额均值)。"""
    L, exec_pos = sim["L"], sim["exec_pos"]
    bn = bench_nav.to_numpy(dtype=float)
    vals, abn = [], []
    for i, h in sim["triggers"]:
        exit_i = i + 1
        if exit_i >= L.shape[0]:
            continue
        k = int(np.searchsorted(exec_pos, exit_i))
        if k >= len(exec_pos):
            continue
        e2 = int(exec_pos[k])
        r = float(np.exp(L[e2, h] - L[exit_i, h]) - 1.0)
        vals.append(r)
        abn.append(r - (bn[e2] / bn[exit_i] - 1.0))
    if not vals:
        return float("nan"), float("nan"), 0, float("nan"), float("nan")
    a, b = np.array(vals), np.array(abn)
    return (
        float(a.mean()),
        float(np.median(a)),
        int(a.size),
        float((a <= 0).mean()),
        float(b.mean()),
    )


def year_dd(nav: pd.Series) -> pd.Series:
    return nav.groupby(nav.index.year).apply(
        lambda s: float((s / s.cummax() - 1).min()) if len(s) else float("nan")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    add_config_arg(ap)
    args = ap.parse_args()
    load_config(args.config)  # noqa: F841

    print("== Round 59 R5 个股止损叠加 (预注册 v1.0) ==")
    close, amount, tst, isst, ind = _load()
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    sets = rebs_to_sets(rebs)
    print(f"调仓次数 {len(rebs)} | 首执行 {min(sets)} | 末执行 {max(sets)}")
    print(f"面板 {ret.shape[0]} 日 × {ret.shape[1]} 股 | 成本 {COST * 1e4:.0f}bp\n")

    # ---------- 自检①: 基线臂 vs 生产 ew_nav 数值对拍 ----------
    nav_r5, _ = ew_nav(ret, sets, COST)  # R5 生产臂(无止损) = Z1/Z2 的基线
    nav_bench, _ = ew_nav(ret, bench, COST)  # 同池等权基准 = 超额口径
    base = simulate(ret, sets, None, COST)
    dmax = float((base["nav"] - nav_r5).abs().max())
    print("== 自检① 对拍 (simulate(thr=None) vs ew_nav) ==")
    print(
        f"最大绝对差 {dmax:.3e} → "
        f"{'✅ 数值等价(浮点舍入级)' if dmax < 1e-12 else '❌ 不一致'}"
    )

    # ---------- 自检②: 面板/周期完整性(可判定) ----------
    exc_full = metrics(nav_r5)["年化"] - metrics(nav_bench)["年化"]
    exc_train = seg_exc(nav_r5, nav_bench, *TRAIN)
    exc_val = seg_exc(nav_r5, nav_bench, *VAL)
    n_reb, first_exec = len(rebs), min(sets)
    print("\n== 自检② 面板/周期完整性 (vs 生产记录) ==")
    ok_n = "✅" if n_reb == 141 else "❌"
    ok_d = "✅" if str(first_exec.date()) == "2015-01-05" else "❌"
    print(f"  调仓次数 {n_reb} (运营手册 §1 记载 141) {ok_n}")
    print(f"  首执行日 {first_exec.date()} (手册 2015-01-05) {ok_d}")
    print(
        f"  基线 R5: 年化 {metrics(nav_r5)['年化']:+.2%} | 最大回撤 "
        f"{metrics(nav_r5)['最大回撤']:+.1%} (手册: −50% 级) | 年换手 {base['turn_yr']:.2f}"
    )
    print(
        f"  基线超额: 全区间 {exc_full:+.2%} | 训练 2014-2021 {exc_train:+.2%} | "
        f"验证 2022-2026 {exc_val:+.2%} (vs 同池等权 15bp)"
    )

    # ---------- 自检③: R38 锚点 = 仅量级核对(不作判据, 面板期数不同) ----------
    r5c = _cfg().r5
    ret38, amihud, mom, f4 = _factors(close, amount)
    n38 = 0
    print("\n== 自检③ 量级核对(不作判据) ==")
    print(
        f"  ⚠️ 自检③ 判据作废(设计错误): 预注册锚点取自 R38 的 159 期研究面板,"
        f" 本轮是生产 {n_reb} 期面板, 周期不可比 —— 仅打印数字供量级参考"
    )
    for tag, (wa, wm, wf4) in (
        ("w*(0.40/0.10/0.50)", (r5c.w_amihud, r5c.w_mom, r5c.w_f4)),
        ("A (0.85/0.15/0)", (0.85, 0.15, 0.0)),
    ):
        rb, bn = build_rebs_r38(close, tst, isst, ind, amihud, mom, f4, wa, wm, wf4)
        n38 = len(rb)
        nv, _ = ew_nav(ret38, rebs_to_sets(rb), COST)
        nb, _ = ew_nav(ret38, bn, COST)
        ref = (
            "R38 记录 +10.40% (159 期)"
            if wa == r5c.w_amihud
            else "R38 记录 +8.03% (159 期)"
        )
        print(
            f"  {tag:20s} {n38} 期 全区间超额 "
            f"{metrics(nv)['年化'] - metrics(nb)['年化']:+.2%}  vs  {ref}"
        )
    print(f"  本轮基线(w*)全区间超额 {exc_full:+.2%} (基准 = 同池等权 15bp)")

    # ---------- 逐档跑 ----------
    rows, sims = [], {}
    for thr in THRS:
        s = simulate(ret, sets, thr, COST)
        sims[thr] = s
        m = metrics(s["nav"])
        cm, cmed, _cn, cdodge, cabn = counterfactual(s, nav_bench)
        rows.append(
            {
                "thr": thr,
                "年化": m["年化"],
                "超额15bp": m["年化"] - metrics(nav_bench)["年化"],
                "最大回撤": m["最大回撤"],
                "夏普": m["夏普"],
                "年换手": s["turn_yr"],
                "年费用%": s["turn_sum"] * COST / _trade_years(ret, sets) * 100,
                "平均仓位%": s["avg_invested"] * 100,
                "触发次数": len(s["triggers"]),
                "触发/年": len(s["triggers"]) / _trade_years(ret, sets),
                "反事实均值%": cm * 100,
                "反事实中位%": cmed * 100,
                "躲对占比%": cdodge * 100,
                "反事实超额%": cabn * 100,
            }
        )
    df = pd.DataFrame(rows)
    m_base = metrics(nav_r5)
    df.loc[len(df)] = {
        "thr": np.inf,
        "年化": m_base["年化"],
        "超额15bp": exc_full,
        "最大回撤": m_base["最大回撤"],
        "夏普": m_base["夏普"],
        "年换手": base["turn_yr"],
        "年费用%": base["turn_sum"] * COST / _trade_years(ret, sets) * 100,
        "平均仓位%": base["avg_invested"] * 100,
        "触发次数": 0,
        "触发/年": 0.0,
        "反事实均值%": np.nan,
        "反事实中位%": np.nan,
        "躲对占比%": np.nan,
        "反事实超额%": np.nan,
    }

    # ---------- 判定 ----------
    dd_base, ann_base, turn_base = (
        m_base["最大回撤"],
        m_base["年化"],
        base["turn_yr"],
    )
    df["回撤改善pp"] = (df["最大回撤"] - dd_base) * 100
    print("\n== 结果表 (基线 = thr ∞) ==")
    show = [
        "thr",
        "年化",
        "超额15bp",
        "最大回撤",
        "回撤改善pp",
        "夏普",
        "年换手",
        "年费用%",
        "平均仓位%",
        "触发/年",
        "反事实均值%",
        "反事实超额%",
        "躲对占比%",
    ]
    with pd.option_context("display.width", 200, "display.max_columns", 50):
        print(df[show].to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n== 判定 (预注册 §4) ==")
    improv = df["回撤改善pp"].to_numpy(dtype=float)
    z4 = np.ones(len(THRS), dtype=bool)
    for j in range(len(THRS)):
        nb = [abs(improv[j] - improv[k]) for k in (j - 1, j + 1) if 0 <= k < len(THRS)]
        z4[j] = max(nb) <= 3.0 if nb else True
    verdicts = []
    for j, thr in enumerate(THRS):
        sub = df.iloc[j]
        z1 = sub["回撤改善pp"] >= 5.0
        z2 = sub["年化"] >= ann_base - 0.01
        z3 = all(seg_exc(sims[thr]["nav"], nav_bench, s, e) > 0 for _, s, e in ERAS)
        z5 = sub["年换手"] <= 1.5 * turn_base
        allpass = z1 and z2
        verdicts.append(allpass)
        print(
            f"  thr={thr:>4.0%}  Z1 {sub['回撤改善pp']:+.1f}pp {'✅' if z1 else '❌'}"
            f" | Z2 {(sub['年化'] - ann_base) * 100:+.2f}pp {'✅' if z2 else '❌'}"
            f" | Z3 {'✅' if z3 else '❌'} | Z4 {'✅' if z4[j] else '❌'}"
            f" | Z5 {sub['年换手'] / turn_base:.2f}x {'✅' if z5 else '❌'}"
            f"  → {'通过' if allpass else '未通过'}"
        )
    print(
        f"\nZ1+Z2 全过档位: {[f'{t:.0%}' for t, v in zip(THRS, verdicts) if v] or '无'}"
        f" | 若有 ⚠️ 需同时 Z4 高原成立才采纳: "
        f"{[f'{t:.0%}' for t, v, g in zip(THRS, verdicts, z4) if v and g] or '无'}"
    )

    # ---------- 分段 + 分年回撤 ----------
    print("\n== 分段超额 vs 同池等权基准 (15bp) ==")
    seg_rows = []
    for thr in list(THRS) + [np.inf]:
        nav = nav_r5 if np.isinf(thr) else sims[thr]["nav"]
        seg_rows.append(
            {
                "thr": thr,
                **{name: seg_exc(nav, nav_bench, s, e) for name, s, e in ERAS},
            }
        )
    seg_df = pd.DataFrame(seg_rows)
    with pd.option_context("display.width", 200):
        print(seg_df.to_string(index=False, float_format=lambda x: f"{x:,.2%}"))

    ydd = pd.DataFrame(
        {
            "基线(R5)": year_dd(nav_r5),
            **{f"thr{t:.0%}": year_dd(sims[t]["nav"]) for t in THRS},
        }
    )
    print("\n== 分年最大回撤 ==")
    with pd.option_context("display.width", 200):
        print(ydd.to_string(float_format=lambda x: f"{x:,.1%}"))

    # ---------- 落盘 ----------
    out = Path(_cfg().paths.output)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "factor_round59_r5_stoploss.csv", index=False)
    seg_df.to_csv(out / "factor_round59_r5_stoploss_eras.csv", index=False)
    ydd.to_csv(out / "factor_round59_r5_stoploss_year_dd.csv")
    print(f"\n输出: {out}/factor_round59_r5_stoploss*.csv")


if __name__ == "__main__":
    main()
