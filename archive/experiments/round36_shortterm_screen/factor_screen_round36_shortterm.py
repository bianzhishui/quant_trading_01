#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 36 周频短线因子批量筛选（5 日持有，全市场非ST池）—— 严格按
docs/factor_round36_shortterm_screen_plan.md v1.0 实施。

规则(预注册定死):
  池: 信号日T days_count>=375 & tradestatus==1 & isST==0 & 主板全市场(含退市) & T日未涨停
  频率: 每5交易日信号T → T+1收盘买入 → T+6收盘卖出(5日持有, 完全轮换)
  因子: F1短反转5 / F2短反转10 / F3低换手5 / F4低成交额5 / F5低波动21 /
        F6短动量5(反向对照) / F7换手突变
  组合: 池内 rank 等分5组, 多头=Q1(方向端)等权, 基准=同池等权, 成本15bp/单边
  判定: ①|t|>=2 ②Q1最高(低)且Q5另一端 ③扣15bp超额>=3pp ④三分段2段为正
  同源守卫: F3/F4 与 Amihud21 截面|rho|>0.6 → 正交残差 IC(对Amihud21回归取残差)

用法: uv run python research/factor_screen_round36_shortterm.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# matplotlib 配置/缓存目录 → 项目内可写位置
os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parent.parent / ".mplconfig")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sps

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.config import get_config  # noqa: E402
from research.data_io import load_full_daily  # noqa: E402
from research.dividend_factor import metrics  # noqa: E402
from research.reversal_factor import build_pool, ew_nav  # noqa: E402

WEEK = 5  # 5 交易日 = 一周


def _cfg():
    return get_config()


def load_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """全市场(主板2787只, 含退市)面板: close/turn/amount/tst/isst (周频信号窗口)。"""
    cfg = _cfg()
    start = cfg.strategy.start
    d = load_full_daily()
    d["date"] = pd.to_datetime(d["date"])

    def _pivot(col: str) -> pd.DataFrame:
        x = d.pivot(index="date", columns="code", values=col).sort_index()
        return x.loc[start:]

    close = _pivot("close")
    turn = _pivot("turn")
    amount = _pivot("amount")
    tst = _pivot("tradestatus")
    isst = _pivot("isST")
    return close, turn, amount, tst, isst


def weekly_signal_days(idx: pd.DatetimeIndex, warmup: int = 0) -> pd.DatetimeIndex:
    """每 5 个交易日取一个信号日(对齐周频), 从 warmup 个交易日之后开始。"""
    pos = np.arange(len(idx))
    return idx[(pos % WEEK == WEEK - 1) & (pos >= warmup)]


def amihud21(close: pd.DataFrame, amount: pd.DataFrame) -> pd.DataFrame:
    """Amihud 21 日均(生产同款, 用于同源守卫)。"""
    ret = close.pct_change()
    cfg = _cfg()
    return (
        ((ret.abs() / amount) * cfg.strategy.r5.amihud_scale)
        .rolling(21, min_periods=15)
        .mean()
    )


def factor_panels(
    close: pd.DataFrame, turn: pd.DataFrame, amount: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """7 个因子宽表面板(信号日取值)。"""
    ret1 = close.pct_change()
    f = {
        "F1短反转5": close / close.shift(5) - 1.0,
        "F2短反转10": close / close.shift(10) - 1.0,
        "F3低换手5": turn.rolling(5).mean(),
        "F4低成交额5": amount.rolling(5).mean(),
        "F5低波动21": ret1.rolling(21).std(),
        "F6短动量5": close / close.shift(5) - 1.0,  # 与 F1 同值(方向对照)
        "F7换手突变": turn / turn.rolling(5).mean().shift(5) - 1.0,
    }
    return f


def nw_t(ic: pd.Series, lag: int = 4) -> float:
    """Newey-West HAC t 值(周频相邻 IC 共用市场β, 简单滞后校正; 窗口本身不重叠)。"""
    x = ic.values - ic.mean()
    n = len(x)
    if n < 2 or ic.std(ddof=1) == 0:
        return float("nan")
    s0 = np.mean(x**2)
    gam = 0.0
    for lag_i in range(1, min(lag + 1, n)):
        gam += (1 - lag_i / (lag + 1)) * np.mean(x[lag_i:] * x[:-lag_i])
    var = (s0 + 2 * gam) / n
    if var <= 0:
        return float("nan")
    return float(ic.mean() / np.sqrt(var))


def main() -> None:
    cfg = _cfg()
    n_q = cfg.strategy.n_q
    cost_base = cfg.costs.cost_base
    cost_sweep = cfg.costs.cost_sweep
    eras = cfg.strategy.eras.to_dict()
    out = Path(cfg.paths.output)
    out.mkdir(exist_ok=True)

    print("== Round 36 周频短线因子批量筛选 (预注册 v1.0) ==")
    close, turn, amount, tst, isst = load_panels()
    print(
        f"数据: {close.shape[0]} 交易日 × {close.shape[1]} 只, "
        f"{close.index[0].date()} ~ {close.index[-1].date()}"
    )

    factors = factor_panels(close, turn, amount)
    amih = amihud21(close, amount)
    pool = build_pool(close, tst, isst)
    ret_qfq = close.pct_change()

    idx = close.index
    sig_days = weekly_signal_days(idx, warmup=30)
    # 需 T+1 执行 且 T+6 卖出都落在样本内
    sig_days = [t for t in sig_days if idx.get_loc(t) + 6 < len(idx)]
    print(
        f"周频信号日: {len(sig_days)} 期 ({sig_days[0].date()} ~ {sig_days[-1].date()})"
    )

    rows = []
    for name, fac in factors.items():
        direction = "low" if name != "F6短动量5" else "high"
        q_sets: list[dict] = [dict() for _ in range(n_q)]
        bench_sets: dict = {}
        ics: dict = {}
        pool_sizes, q_sizes = [], []
        amih_corr, orth_ics = [], []

        for k, T in enumerate(sig_days):
            e = pool.loc[T]
            f = fac.loc[T][e].dropna()
            if len(f) < 50:
                continue
            exec_day = idx[idx.get_loc(T) + 1]  # T+1 收盘买入
            rk = f.rank(method="first")
            if direction == "high":
                rk = -rk  # 方向端归一: F6 取最高组为 Q1
            q = pd.qcut(rk, n_q, labels=False)
            for g in range(n_q):
                q_sets[g][exec_day] = set(f.index[q == g])
            bench_sets[exec_day] = set(f.index)
            pool_sizes.append(len(f))
            q_sizes.append(len(f) / n_q)

            # 未来 5 日收益: T+1 买 → T+6 卖
            sell_day = idx[idx.get_loc(T) + 6]
            fwd = close.loc[sell_day] / close.loc[exec_day] - 1.0
            m = f.index.intersection(fwd.dropna().index)
            if len(m) >= 50:
                ics[T] = sps.spearmanr(f[m], fwd[m])[0]

            # 同源守卫: F3/F4 与 Amihud21 截面相关 + 正交残差 IC
            if name in ("F3低换手5", "F4低成交额5"):
                a = amih.loc[T][m].dropna()
                if len(a) >= 50:
                    common = f[m].index.intersection(a.index)
                    if len(common) >= 50:
                        rho = sps.spearmanr(f[common], a[common])[0]
                        amih_corr.append(rho)
                        # 正交残差: rank(f) ~ rank(amihud) OLS 残差 再对 fwd 算 IC
                        xr = f[common].rank().values
                        yr = a[common].rank().values
                        z = fwd[common].rank().values
                        A = np.column_stack([np.ones(len(xr)), yr])
                        beta, *_ = np.linalg.lstsq(A, xr, rcond=None)
                        resid = xr - A @ beta
                        if resid.std() > 0 and z.std() > 0:
                            orth_ics.append(np.corrcoef(resid, z - z.mean())[0, 1])

        ic = pd.Series(ics, name="rank_ic").sort_index()
        if len(ic) == 0:
            print(f"\n[{name}] 无有效 IC 期, 跳过")
            continue
        ic_mean, ic_std = ic.mean(), ic.std(ddof=1)
        ic_t = nw_t(ic)
        icir = ic_mean / ic_std if ic_std > 0 else float("nan")

        navs, turns = {}, {}
        for g in range(n_q):
            navs[f"Q{g + 1}"], turns[f"Q{g + 1}"] = ew_nav(
                ret_qfq, q_sets[g], cost_base
            )
        navs["基准(等权全池)"], turns["基准"] = ew_nav(ret_qfq, bench_sets, cost_base)
        q1_25, _ = ew_nav(ret_qfq, q_sets[0], cost_sweep[0])
        q1_35, _ = ew_nav(ret_qfq, q_sets[0], cost_sweep[1])

        anns = {k: metrics(v)["年化"] for k, v in navs.items()}
        excess15 = anns["Q1"] - anns["基准(等权全池)"]
        excess25 = metrics(q1_25)["年化"] - anns["基准(等权全池)"]
        excess35 = metrics(q1_35)["年化"] - anns["基准(等权全池)"]
        group_ann = [anns[f"Q{g + 1}"] for g in range(n_q)]
        mono_rho = sps.spearmanr(range(1, n_q + 1), group_ann)[0]

        era_excess = {}
        for era, (s, e) in eras.items():
            a = navs["Q1"][s:e]
            b = navs["基准(等权全池)"][s:e]
            ma = metrics(a / a.dropna().iloc[0])["年化"]
            mb = metrics(b / b.dropna().iloc[0])["年化"]
            era_excess[era] = ma - mb

        c1 = abs(ic_t) >= 2.0
        c2 = (group_ann[0] == max(group_ann)) and (group_ann[-1] == min(group_ann))
        c3 = excess15 >= 0.03
        c4 = sum(v > 0 for v in era_excess.values()) >= 2
        n_pass = sum([c1, c2, c3, c4])
        verdict = {4: "通过", 3: "部分通过"}.get(n_pass, "未通过")

        # 同源守卫判定
        homo_note = ""
        if name in ("F3低换手5", "F4低成交额5") and amih_corr:
            rho_m = float(np.mean(amih_corr))
            orth_ic_m = float(np.mean(orth_ics)) if orth_ics else float("nan")
            if abs(rho_m) > 0.6:
                orth_note = f"正交残差IC {orth_ic_m:+.4f}"
                if abs(orth_ic_m) < 0.02:
                    verdict = "未通过(同源)"
                    orth_note += " → 同源不新增 alpha"
                else:
                    orth_note += (
                        " → 显著, 与生产Amihud短频共生, 需组合验证守门(R22/R30教训)"
                    )
                homo_note = f" | Amihud相关{rho_m:+.2f} {orth_note}"
            else:
                homo_note = f" | Amihud相关{rho_m:+.2f}(<0.6 无同源触发)"

        rows.append(
            {
                "因子": name,
                "方向": direction,
                "IC均值": round(ic_mean, 4),
                "t(NeweyWest)": round(ic_t, 2) if not np.isnan(ic_t) else None,
                "ICIR": round(icir, 2) if not np.isnan(icir) else None,
                "IC正占比": round((ic > 0).mean(), 2),
                "Q1年化": round(anns["Q1"], 4),
                "Q5年化": round(anns["Q5"], 4),
                "基准年化": round(anns["基准(等权全池)"], 4),
                "超额15bp": round(excess15, 4),
                "超额25bp": round(excess25, 4),
                "超额35bp": round(excess35, 4),
                "年换手": round(turns["Q1"], 1),
                "组序Spearman": round(mono_rho, 2),
                "段14-17": round(era_excess["2014-2017"], 4),
                "段18-21": round(era_excess["2018-2021"], 4),
                "段22-26": round(era_excess["2022-2026"], 4),
                "判定": verdict,
            }
        )
        print(
            f"\n[{name}] ({direction})  IC={ic_mean:+.4f} t={ic_t:+.2f} "
            f"ICIR={icir:+.2f} 正占比={(ic > 0).mean():.0%} | "
            f"Q1 {anns['Q1']:+.1%} / Q5 {anns['Q5']:+.1%} / 基准 {anns['基准(等权全池)']:+.1%}"
            f" | 超额 15bp {excess15:+.1%} 25bp {excess25:+.1%} 35bp {excess35:+.1%}"
            f" | 换手 {turns['Q1']:.1f} | 段 {[f'{v:+.1%}' for v in era_excess.values()]}"
            f" | {verdict}{homo_note}"
        )
        # 存净值供后续检查
        pd.DataFrame(navs).to_csv(out / f"round36_{name}_navs.csv")
        ic.to_csv(out / f"round36_{name}_ic.csv", header=True)

    summary = pd.DataFrame(rows)
    summary.to_csv(out / "round36_shortterm_summary.csv", index=False)
    print("\n== 判定总表 ==")
    print(summary.to_string(index=False))
    print(f"\nCSV: {out}/round36_shortterm_summary.csv (+ 各因子 navs/ic)")


if __name__ == "__main__":
    main()
