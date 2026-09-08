#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 8 实盘化验证 —— 严格按 docs/factor_round8_live_validation_plan.md v1.0 实施。

1a. 流动性依赖成本: c_i = 15bp + s×pct_amihud_i, s ∈ {20,40,60} + flat 50/70
1b. 可交易性审计: pos_frac=(AUM/N)/ADV, AUM=1000万/5000万; T+1 涨跌停阻塞统计
1c. 模拟盘起点: 最新信号持仓清单 CSV
自检: s=0 无阻塞应复现 Round 7 (+4.6pp)。
用法: uv run python research/factor_round8_live_validation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

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


def load_full():
    d = pd.read_parquet(ROOT / "data" / "fundamental" / "full_daily.parquet")
    d["date"] = pd.to_datetime(d["date"])

    def piv(c):
        return d.pivot(index="date", columns="code", values=c).sort_index().loc[START:]

    return piv("close"), piv("amount"), piv("tradestatus"), piv("isST")


def main() -> None:
    print("== Round 8 实盘化验证 (预注册 v1.0) ==")
    close, amount, tst, isst = load_full()
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    ind = pd.read_parquet(R2 / "industry_full.parquet").set_index("code")["industry"]
    ind = ind.reindex(close.columns).dropna()

    amihud = (
        ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    )
    mom = close.shift(21) / close.shift(250) - 1.0
    adv = amount.rolling(21).mean()

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]

    # ---- 预计算每月信号: target set / exec_day / 池 / amihud pct / adv ----
    rebs = []  # 每次调仓信息
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
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        target = set(codes[q == 4])
        rebs.append(
            {
                "T": T,
                "exec": exec_day,
                "target": target,
                "pct_amihud": a.reindex(codes).rank(pct=True),
                "adv": adv.loc[T],
                "amihud": a,
                "mom": m,
            }
        )
    print(f"调仓期数 {len(rebs)}, 中性化池月均~2279 只")

    nav_bench, _ = ew_nav(ret, bench_sets, BASE)
    ann_bench = metrics(nav_bench)["年化"]

    # ---- 模拟器(普通循环) ----
    def run(
        s: float,
        flat: float | None = None,
        block: bool = False,
        collect_audit: bool = False,
    ):
        w = pd.Series(0.0, index=ret.columns)
        navs = np.ones(len(idx))
        n_block_enter = n_block_exit = 0
        audit_rows = []
        reb_map = {rb["exec"]: rb for rb in rebs}
        for i, dt in enumerate(idx):
            rb = reb_map.get(dt)
            if rb is not None:
                target = rb["target"]
                r_exec = ret.loc[dt]
                blocked_entry = blocked_exit = set()
                if block:
                    blocked_entry = {
                        c for c in target if c in r_exec.index and r_exec[c] >= LIMIT
                    }
                    held = set(w[w > 0].index)
                    blocked_exit = {
                        c
                        for c in (held - target)
                        if c in r_exec.index and r_exec[c] <= -LIMIT
                    }
                    n_block_enter += len(blocked_entry)
                    n_block_exit += len(blocked_exit)
                target = set(target) - blocked_entry
                n_new = len(target)
                B = sum(w[c] for c in blocked_exit)
                new_w = pd.Series(0.0, index=ret.columns)
                if n_new:
                    ew = (1 - B) / n_new
                    for c in target:
                        new_w[c] = ew
                for c in blocked_exit:
                    new_w[c] = w[c]
                chg = (new_w - w).abs()
                if flat is not None:
                    cost_vec = pd.Series(flat, index=ret.columns)
                else:
                    pct = rb["pct_amihud"]
                    cost_vec = pd.Series(BASE, index=ret.columns)
                    cost_vec.loc[pct.index] = BASE + s * pct.values
                reb_cost = float((chg * cost_vec).sum())
                # 口径对齐 ew_nav: (1) 调仓日当日收益按旧权重, 新权重次日生效;
                # (2) 成本按净值比例计(放复利因子内, 随账户净值等比增长)——真实交易口径
                navs[i] = navs[i - 1] * (1 + float((w * r_exec).sum()) - reb_cost)
                w = new_w
                if collect_audit:
                    for c in target:
                        ad = rb["adv"].get(c, np.nan)
                        if pd.notna(ad) and ad > 0:
                            audit_rows.append(
                                {
                                    "date": dt,
                                    "code": c,
                                    "ADV": ad,
                                    "N": n_new,
                                    "amihud_pct": rb["pct_amihud"].get(c, np.nan),
                                }
                            )
            else:
                r_row = ret.loc[dt]
                navs[i] = navs[i - 1] * (1 + float((w * r_row).sum()))
        nav = pd.Series(navs, index=idx)
        return nav, n_block_enter, n_block_exit, audit_rows

    # ---- 各臂 ----
    results = {}
    nav_s0, *_ = run(0.0)
    excess_s0 = metrics(nav_s0)["年化"] - ann_bench
    print(f"\n自检 s=0 无阻塞: 超额 {excess_s0:+.1%} (Round 7 应为 +4.6%)")

    for s in [0, 20, 40, 60]:
        nav, *_ = run(s * 1e-4)
        results[f"s={s}bp"] = metrics(nav)["年化"] - ann_bench
    for f in [50, 70]:
        nav, *_ = run(0.0, flat=f * 1e-4)
        results[f"flat{f}bp"] = metrics(nav)["年化"] - ann_bench
    nav_blk, n_be, n_bx, _ = run(0.0, block=True)
    excess_blk = metrics(nav_blk)["年化"] - ann_bench
    # E4: 阻塞损失
    e4 = excess_s0 - excess_blk

    # E3 审计
    _, _, _, audit = run(0.0, collect_audit=True)
    aud = pd.DataFrame(audit)
    print(f"\n== 成本敏感度 (超额, 基准 {ann_bench:+.1%}) ==")
    for k, v in results.items():
        print(f"  {k}: {v:+.2%}")
    print(
        f"  s=0 阻塞版: {excess_blk:+.2%} (阻塞损失 {e4:+.2%}) | "
        f"买不进 {n_be} 次, 卖不出 {n_bx} 次"
    )

    # E3
    def pos_frac_stats(aum: float):
        aud2 = aud.copy()
        aud2["pos"] = aum / aud2["N"]
        aud2["pos_frac"] = aud2["pos"] / aud2["ADV"]
        pf = aud2["pos_frac"]
        return (pf.median(), pf.quantile(0.95), (pf > 0.05).mean(), (pf > 0.10).mean())

    rows_e3 = {}
    for aum in [10e6, 50e6]:
        p50, p95, gt5, gt10 = pos_frac_stats(aum)
        rows_e3[f"AUM={aum / 1e6:.0f}百万"] = dict(p50=p50, p95=p95, gt5=gt5, gt10=gt10)
        print(
            f"  AUM={aum / 1e6:.0f}百万: pos_frac p50 {p50:.2%} p95 {p95:.2%} "
            f">5%占 {gt5:.1%} >10%占 {gt10:.1%}"
        )

    # E1/E2/E3/E4
    e1 = results["s=40bp"] >= 0.02
    e2 = results["flat70bp"] > 0
    e3 = rows_e3["AUM=10百万"]["gt10"] < 0.10
    e4_ok = e4 < 0.01
    n_pass = sum([e1, e2, e3, e4_ok])
    verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
    print("\n== 判定 ==")
    print(f"  E1 s=40bp 超额≥+2pp: {results['s=40bp']:+.2%} → {e1}")
    print(f"  E2 flat70bp 超额>0: {results['flat70bp']:+.2%} → {e2}")
    print(f"  E3 AUM1000万 >10%占<10%: {rows_e3['AUM=10百万']['gt10']:.1%} → {e3}")
    print(f"  E4 阻塞损失<1pp: {e4:+.2%} → {e4_ok}")
    print(f"  → Round 8 判定: {verdict}({n_pass}/4)")

    # ---- R8c 模拟盘起点 ----
    last = rebs[-1]
    rows_live = []
    for c in sorted(last["target"]):
        rows_live.append(
            {
                "code": c,
                "行业": ind.get(c, ""),
                "权重": 1.0 / len(last["target"]),
                "Amihud": round(float(last["amihud"].get(c, np.nan)), 6),
                "动量": round(float(last["mom"].get(c, np.nan)), 4),
                "Amihud百分位": round(float(last["pct_amihud"].get(c, np.nan)), 3),
            }
        )
    live = pd.DataFrame(rows_live).sort_values("Amihud百分位", ascending=False)
    live_out = OUT / "factor_round8_holdings_2026-09-03.csv"
    live.to_csv(live_out, index=False)
    print(f"\n== 模拟盘起点 ({last['T'].date()} 信号, {last['exec'].date()} 执行) ==")
    print(f"持仓 {len(live)} 只 | 已存 {live_out.name}")
    print(
        "Amihud百分位>0.8 的冷门股占比: "
        f"{(live['Amihud百分位'] > 0.8).mean():.0%} (成本意识: 这些股执行成本高)"
    )

    pd.DataFrame(
        {
            "臂": list(results) + ["s=0阻塞"],
            "超额": list(results.values()) + [excess_blk],
        }
    ).to_csv(OUT / "factor_round8_summary.csv", index=False)
    fig, ax = plt.subplots(figsize=(11.5, 6))
    for s in [0, 20, 40, 60]:
        nav, *_ = run(s * 1e-4)
        ax.plot(nav / nav_bench, lw=1.2, label=f"s={s}bp")
    ax.plot(nav_blk / nav_bench, lw=1.4, ls="--", color="k", label="s=0 + 涨跌停阻塞")
    for y in ("2018-01-01", "2022-01-01"):
        ax.axvline(pd.Timestamp(y), color="gray", ls="--", lw=0.8)
    ax.axhline(1.0, color="gray", lw=0.8)
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_title("Round 8 实盘化验证: 相对基准净值 (不同成本模型)")
    fig.tight_layout()
    fig.savefig(OUT / "factor_round8.png", dpi=130)
    print("\nCSV: output/factor_round8_summary.csv | 图: output/factor_round8.png")


if __name__ == "__main__":
    main()
