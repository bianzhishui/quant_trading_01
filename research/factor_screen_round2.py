#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 2 因子批量筛选 —— 严格按 docs/factor_screen_round2_plan.md v1.0 实施。

统一回测 9 个因子（7 新增 + 反转 + 中期动量）+ 全因子相关矩阵。
新增因子数据来自 data/round2/（baostock turn/amount/peTTM, ROE, 两融, 北向）
+ dividends.parquet（股息连续性）。小市值：数据不可得，暂缓（见方案 §2）。

每因子: 预注册方向 → 月度 RankIC + 五分组(扣15bp) + 分年代 → 四层判定。
用法: uv run python research/factor_screen_round2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sps

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import load_all, month_last_days, metrics
from research.reversal_factor import ERAS, N_Q, build_pool, ew_nav

COST = 15e-4
COST_SWEEP = [25e-4, 35e-4]
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
MIN_N = 50            # 一般因子最小截面
MIN_N_SMALL = 30      # 两融/北向（覆盖受限）

# 方向: +1 = 因子值高→看好(多头=Q5); -1 = 值低→看好(多头=Q1)
FACTORS: dict[str, tuple[int, int]] = {
    "反转": (-1, MIN_N), "中期动量": (+1, MIN_N),      # 已测, 纳入统一矩阵
    "低换手率": (-1, MIN_N), "Amihud": (+1, MIN_N),
    "EP": (+1, MIN_N), "股息连续性": (+1, MIN_N),
    "两融变化": (-1, MIN_N_SMALL), "北向净买入": (+1, MIN_N_SMALL),
    "ROE": (+1, MIN_N),
}


def load_ext_panels() -> dict[str, pd.DataFrame]:
    """从 data/round2 读长表 → 宽表(date × code)。返回 None 表示数据缺失。"""
    out: dict[str, pd.DataFrame | None] = {}
    if (R2 / "daily_ext.parquet").exists():
        d = pd.read_parquet(R2 / "daily_ext.parquet")
        d["date"] = pd.to_datetime(d["date"])
        for col in ["turn", "amount", "peTTM"]:
            sub = d[["date", "code", col]].dropna(subset=[col])
            w = sub.pivot(index="date", columns="code", values=col).sort_index()
            out[col] = w
    if (R2 / "roe.parquet").exists():
        r = pd.read_parquet(R2 / "roe.parquet")
        r["report_date"] = pd.to_datetime(r["report_date"])
        out["roe"] = r
    if (R2 / "margin.parquet").exists():
        m = pd.read_parquet(R2 / "margin.parquet")
        m["date"] = pd.to_datetime(m["date"])
        out["margin"] = m.pivot(index="date", columns="code", values="margin_bal").sort_index()
    if (R2 / "hsgt.parquet").exists():
        h = pd.read_parquet(R2 / "hsgt.parquet")
        h["date"] = pd.to_datetime(h["date"])
        out["hsgt"] = h.pivot(index="date", columns="code", values="hold_ratio").sort_index()
    return out


def build_factors(close: pd.DataFrame, pb: pd.DataFrame, div_mat: pd.DataFrame,
                  ext: dict) -> dict[str, pd.DataFrame]:
    """返回 {因子名: 宽表}（因子缺失返回空 DataFrame）。"""
    ret1 = close.pct_change()
    f: dict[str, pd.DataFrame] = {}

    f["反转"] = close / close.shift(21) - 1.0
    f["中期动量"] = close.shift(21) / close.shift(250) - 1.0

    if "turn" in ext:
        f["低换手率"] = ext["turn"].rolling(21, min_periods=15).mean()
    if "amount" in ext:
        am = (ret1.abs() / ext["amount"]) * 1e6
        f["Amihud"] = am.rolling(21, min_periods=15).mean()
    if "peTTM" in ext:
        f["EP"] = 1.0 / ext["peTTM"].where(ext["peTTM"] > 0)

    # 股息连续性: 近5个完整日历年(截至T-1年)分红>0年数
    if div_mat is not None and not div_mat.empty:
        years = sorted(div_mat.columns)
        cont = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
        for T in close.index:
            Y = T.year
            cols = [y for y in years if Y - 5 <= y <= Y - 1]
            if not cols:
                continue
            cont.loc[T] = (div_mat.reindex(columns=cols).gt(0)).sum(axis=1).reindex(cont.columns)
        f["股息连续性"] = cont

    # ROE: 报告期末 + 120 天后才可用 → ffill
    if "roe" in ext:
        r = ext["roe"]
        r = r.copy()
        r["avail"] = r["report_date"] + pd.Timedelta(days=120)
        roe_ts = pd.DataFrame(index=pd.DatetimeIndex(sorted(set(close.index) | set(r["avail"]))),
                              columns=close.columns, dtype=float)
        for code in close.columns:
            sub = r[r["code"] == code]
            if len(sub):
                roe_ts.loc[sub["avail"].values, code] = sub["roe"].values
        f["ROE"] = roe_ts.ffill().reindex(close.index)

    # 两融变化: 月末环比（两融为月末采样）
    if "margin" in ext:
        m = ext["margin"].reindex(columns=close.columns)
        m = m.reindex(close.index).ffill()
        f["两融变化"] = m.pct_change()

    # 北向: 21 日持股占比变化
    if "hsgt" in ext:
        h = ext["hsgt"].reindex(columns=close.columns)
        h = h.reindex(close.index).ffill()
        f["北向净买入"] = h.pct_change(21)

    return f


def main() -> None:
    print("== Round 2 因子批量筛选 (预注册 v1.0): 9 因子 ==")
    close, real, pb, tst, isst, names, div_mat = load_all()
    print(f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
          f"{close.index[0].date()} ~ {close.index[-1].date()}")
    ext = load_ext_panels()
    for k in ["turn", "amount", "peTTM", "roe", "margin", "hsgt"]:
        if k in ext:
            n = ext[k].shape[1] if hasattr(ext[k], "shape") else len(ext[k])
            print(f"  round2/{k}: {n} 列可用")
        else:
            print(f"  round2/{k}: 缺失")

    pool = build_pool(close, tst, isst)
    ret_qfq = close.pct_change()
    factors = build_factors(close, pb, div_mat, ext)

    idx = close.index
    sig_days = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]

    # ---- 逐月: 各因子分组集合 + IC; 基准; 相关矩阵累积 ----
    q_sets = {name: [dict() for _ in range(N_Q)] for name in FACTORS}
    bench_sets: dict = {}
    ics: dict[str, dict] = {name: {} for name in FACTORS}
    n_eff: dict[str, int] = {name: 0 for name in FACTORS}   # 有有效截面的期数
    corr_sum = pd.DataFrame(0.0, index=list(FACTORS), columns=list(FACTORS))
    corr_cnt = pd.DataFrame(0.0, index=list(FACTORS), columns=list(FACTORS))

    for k, T in enumerate(sig_days):
        e = pool.loc[T]
        T2 = sig_days[k + 1] if k + 1 < len(sig_days) else None
        exec_day = idx[idx.get_loc(T) + 1]
        fwd = (close.loc[T2] / close.loc[T] - 1.0) if T2 is not None else None

        # 相关矩阵(两两共同有效截面 ≥30 才计入)
        vals = {name: f.loc[T].reindex(e[e].index).dropna()
                for name, f in factors.items() if name in factors and not f.empty}
        names_avail = [n for n, s in vals.items() if len(s) >= MIN_N_SMALL]
        if len(names_avail) >= 2:
            sub = pd.DataFrame({n: vals[n] for n in names_avail})
            cm = sub.corr(method="spearman")
            for a in names_avail:
                for b in names_avail:
                    if a != b and not pd.isna(cm.at[a, b]):
                        corr_sum.at[a, b] += cm.at[a, b]
                        corr_cnt.at[a, b] += 1

        bench_codes = e[e].index
        if len(bench_codes) >= MIN_N:
            bench_sets[exec_day] = set(bench_codes)
        for name, (direction, min_n) in FACTORS.items():
            fv = factors[name].loc[T][e].dropna()
            if len(fv) < min_n:
                continue
            n_eff[name] += 1
            rk = fv.rank(method="first")
            q = pd.qcut(rk, N_Q, labels=False)
            for g in range(N_Q):
                q_sets[name][g][exec_day] = set(fv.index[q == g])
            if fwd is not None:
                m = fv.index.intersection(fwd.dropna().index)
                if len(m) >= min_n:
                    ics[name][T] = sps.spearmanr(fv[m], fwd[m])[0]

    corr_cs = corr_sum.div(corr_cnt.replace(0, np.nan)).fillna(0.0)
    ic_df = pd.DataFrame(ics).sort_index()
    ic_df = ic_df[[c for c in FACTORS if c in ic_df.columns]]
    corr_ic = ic_df.corr()

    # ---- 回测 ----
    nav_bench, _ = ew_nav(ret_qfq, bench_sets, COST)
    ann_bench = metrics(nav_bench)["年化"]
    rows, long_navs = {}, {}
    n_periods = len(sig_days)
    print(f"\n调仓期数 {len(bench_sets)}, 基准年化 {ann_bench:+.1%}")
    for name, (direction, min_n) in FACTORS.items():
        eff_ratio = n_eff[name] / n_periods
        if eff_ratio < 0.6:
            rows[name] = {"判定": f"数据不足({n_eff[name]}/{n_periods})", "有效截面期数": n_eff[name]}
            print(f"\n■ {name}: 数据不足 {n_eff[name]}/{n_periods}")
            continue
        g_navs = [ew_nav(ret_qfq, q_sets[name][g], COST)[0] for g in range(N_Q)]
        anns = [metrics(v)["年化"] for v in g_navs]
        li = N_Q - 1 if direction == +1 else 0
        si = N_Q - 1 - li
        long_nav, turn = ew_nav(ret_qfq, q_sets[name][li], COST)
        long_navs[name] = long_nav
        long25, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[0])
        long35, _ = ew_nav(ret_qfq, q_sets[name][li], COST_SWEEP[1])
        ic = ic_df[name].dropna()
        ic_mean, ic_t = ic.mean(), ic.mean() / ic.std() * np.sqrt(len(ic)) if len(ic) > 1 else np.nan
        sign_ok = (ic_mean > 0) == (direction == +1)
        era_exc = {}
        for era, (s, e_) in ERAS.items():
            a, b = long_nav[s:e_], nav_bench[s:e_]
            era_exc[era] = metrics(a / a.dropna().iloc[0])["年化"] - \
                           metrics(b / b.dropna().iloc[0])["年化"]
        c1 = sign_ok and abs(ic_mean) >= 0.03 and abs(ic_t) >= 2
        c2 = (anns[li] == max(anns)) and (anns[si] == min(anns))
        c3 = metrics(long_nav)["年化"] - ann_bench >= 0.01
        c4 = sum(v > 0 for v in era_exc.values()) >= 2
        n_pass = sum([c1, c2, c3, c4])
        verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")
        rows[name] = {
            "方向": direction, "IC均值": round(ic_mean, 4), "IC_t": round(ic_t, 2),
            "多头年化15bp": round(metrics(long_nav)["年化"], 4),
            "超额15bp": round(metrics(long_nav)["年化"] - ann_bench, 4),
            "超额25bp": round(metrics(long25)["年化"] - ann_bench, 4),
            "超额35bp": round(metrics(long35)["年化"] - ann_bench, 4),
            "多头年换手": round(turn, 1), "空头年化": round(anns[si], 4),
            "多空毛": round(metrics(long_nav / g_navs[si])["年化"], 4),
            **{f"超额{era}": round(v, 4) for era, v in era_exc.items()},
            "①IC": c1, "②单调": c2, "③可交易": c3, "④稳定": c4,
            "判定": f"{verdict}({n_pass}/4)",
        }
        print(f"\n■ {name} (方向{'高好' if direction == +1 else '低好'}) 判定: {verdict}")
        print("  分组年化: " + "  ".join(
            f"Q{g+1}{ '*' if g == li else ''}:{anns[g]:+.1%}" for g in range(N_Q)))
        print(f"  IC {ic_mean:+.4f}(t={ic_t:+.2f}) | 超额 15bp:{rows[name]['超额15bp']:+.1%} "
              f"25bp:{rows[name]['超额25bp']:+.1%} 35bp:{rows[name]['超额35bp']:+.1%} | 换手 {turn:.1f}")
        print("  分段超额: " + "  ".join(f"{era}:{v:+.1%}" for era, v in era_exc.items()))

    print(f"\n== 因子值截面相关(月均 Spearman) ==")
    print(corr_cs.round(2).to_string())
    print("\n== IC 序列相关 ==")
    print(corr_ic.round(2).to_string())

    OUT.mkdir(exist_ok=True)
    pd.DataFrame(rows).T.to_csv(OUT / "factor_screen_round2_summary.csv")
    corr_cs.round(4).to_csv(OUT / "factor_corr_crosssec_round2.csv")
    corr_ic.round(4).to_csv(OUT / "factor_corr_ic_round2.csv")
    print(f"\nCSV 已保存: factor_screen_round2_summary / factor_corr_*_round2")


if __name__ == "__main__":
    main()
