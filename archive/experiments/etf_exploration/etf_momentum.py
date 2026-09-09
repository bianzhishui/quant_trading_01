#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""ETF 动量轮动策略回测 —— 严格按 docs/etf_momentum_plan.md v1.0 预注册方案实施。

规则(定死, 不许改):
  池: 510300/510500/159915/513100/518880/511010 (低相关六资产)
  信号: 过去20交易日收益率; 每月最后一个交易日收盘计算, 次月首个交易日开盘执行
  持有: 动量最强 K=2 只等权
  变体: V1 裸截面动量 / V2 +绝对动量门槛(动量<=0的份额→国债) /
        V3 +年线过滤(低于250日线不入选, 份额→国债)
  成本: 单边5bp(基准)/10bp(第④层压测)

判定标准(预注册):
  ② 显著性: 月收益-等权全池 p<0.05 (Welch t + 置换)
  ③ 稳定性: 2013-17 / 2018-21 / 2022-26 每段 夏普>0.3 且跑赢等权
  ④ 可交易: 扣10bp单边后 年超额>=3% 且 年换手<=12次
  保留段 2022-2026 只揭榜一次; 失败则归档, 禁止回头调参。

用法: uv run python research/etf_momentum.py
"""

from __future__ import annotations

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
from src.data_loader import _fetch_fund_sina

POOL = {
    "510300": "沪深300",
    "510500": "中证500",
    "159915": "创业板",
    "513100": "纳指",
    "518880": "黄金",
    "511010": "国债",
}
BOND = "511010"
MOM_WIN, K = 20, 2
ERAS = {
    "2013-2017": ("2013-01-01", "2017-12-31"),
    "2018-2021": ("2018-01-01", "2021-12-31"),
    "2022-2026": ("2022-01-01", None),
}  # 第三段=保留段
HOLDOUT_START = "2022-01-01"


# ---------------- 数据 ----------------
def load_pool() -> pd.DataFrame:
    closes = {}
    for code, name in POOL.items():
        df = _fetch_fund_sina(code, "20100101", "20260831")
        closes[code] = df["close"]
        print(f"  {code} {name}: {len(df)}行 至 {df.index[-1].date()}")
    px = pd.DataFrame(closes).dropna()
    print(f"公共交易日: {len(px)}  {px.index[0].date()} ~ {px.index[-1].date()}")
    return px


# ---------------- 信号与权重 ----------------
def momentum_weights(
    px: pd.DataFrame, variant: int, mom_win: int = MOM_WIN, k: int = K
) -> pd.DataFrame:
    """按变体生成日频权重矩阵。权重在信号日次一生效(=次月首个交易日开盘执行)。"""
    mom = px.pct_change(mom_win)
    ma250 = px.rolling(250).mean()
    cols = list(px.columns)

    months = pd.Series(px.index.to_period("M"), index=px.index)
    is_signal_day = months.shift(-1) != months  # 每月最后一个交易日

    warmup = mom_win if variant < 3 else 250  # V3 需要年线就绪
    W = pd.DataFrame(0.0, index=px.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    pending = None

    for i, dt in enumerate(px.index):
        if pending is not None:  # 信号在次一生效
            w, pending = pending, None
        if is_signal_day.iloc[i] and i >= warmup and mom.iloc[i].notna().all():
            m = mom.iloc[i]
            elig = list(cols)
            if variant >= 2:  # 绝对动量门槛
                elig = [c for c in elig if m[c] > 0]
            if variant == 3:  # 年线过滤
                elig = [c for c in elig if px[c].iloc[i] > ma250[c].iloc[i]]
            ranked = sorted(elig, key=lambda c: m[c], reverse=True)
            picks = ranked[:k]
            new_w = pd.Series(0.0, index=cols)
            for c in picks:
                new_w[c] = 1.0 / k
            short = k - len(picks)  # 缺额 → 国债
            if short > 0:
                if BOND in cols:
                    new_w[BOND] += short / k
                # leave-one-out 剔除国债时, 缺额留现金(权重0)
            pending = new_w
        W.iloc[i] = w
    return W


def backtest(
    px: pd.DataFrame, W: pd.DataFrame, cost_one_way: float
) -> tuple[pd.Series, float]:
    ret = px.pct_change().fillna(0.0)
    strat = (W * ret).sum(axis=1)
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    net = strat - turn * cost_one_way
    years = len(px) / 244
    return (1 + net).cumprod(), float(turn.sum() / 2 / years)


def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    ret = nav.pct_change().dropna()
    if len(nav) < 50 or ret.std() == 0:
        return {
            "年化": np.nan,
            "波动": np.nan,
            "夏普": np.nan,
            "最大回撤": np.nan,
            "总收益": np.nan,
        }
    years = len(nav) / 244
    return {
        "总收益": nav.iloc[-1] - 1,
        "年化": nav.iloc[-1] ** (1 / years) - 1,
        "波动": ret.std() * np.sqrt(244),
        "夏普": ret.mean() / ret.std() * np.sqrt(244),
        "最大回撤": float((nav / nav.cummax() - 1).min()),
    }


def monthly(nav: pd.Series) -> pd.Series:
    m = nav.groupby(nav.index.to_period("M")).last()
    return m.pct_change().dropna()


# ---------------- 四层验证 ----------------
def layer2(strat_m: pd.Series, ew_m: pd.Series) -> tuple[float, float]:
    """月收益差: Welch t + 置换检验。"""
    diff = (strat_m - ew_m).dropna()
    t, p_welch = stats.ttest_1samp(diff, 0)
    rng = np.random.default_rng(11)
    arr = diff.to_numpy()
    obs = arr.mean()
    perm = np.array(
        [rng.choice([1, -1], len(arr)).dot(arr) / len(arr) for _ in range(10000)]
    )
    p_perm = (np.abs(perm) >= abs(obs)).mean()
    return float(p_welch), float(p_perm)


def era_table(nav: pd.Series, ew_nav: pd.Series) -> list[dict]:
    rows = []
    for name, (s, e) in ERAS.items():
        a = nav[s:e] / nav[s:e].dropna().iloc[0]
        b = ew_nav[s:e] / ew_nav[s:e].dropna().iloc[0]
        if len(a) < 80:
            continue
        ma, mb = metrics(a), metrics(b)
        rows.append(
            {
                "年代": name,
                "年化": ma["年化"],
                "夏普": ma["夏普"],
                "回撤": ma["最大回撤"],
                "等权年化": mb["年化"],
                "跑赢等权": ma["年化"] > mb["年化"],
                "夏普>0.3": ma["夏普"] > 0.3,
            }
        )
    return rows


def main() -> None:
    print("== ETF 动量轮动回测 (预注册 v1.0) ==")
    px = load_pool()
    ret = px.pct_change()
    ew_nav = (1 + ret.mean(axis=1)).cumprod()  # 等权全池基准
    hs_nav = px["510300"] / px["510300"].iloc[0]

    variants = {"V1 裸动量": 1, "V2 +绝对动量": 2, "V3 +年线过滤": 3}
    navs, summary = {}, []
    for label, v in variants.items():
        W = momentum_weights(px, v)
        nav, turn5 = backtest(px, W, 5e-4)
        _, turn10 = backtest(px, W, 1e-3)
        navs[label] = nav

        m = metrics(nav)
        m_ew = metrics(ew_nav)
        # 第④层: 10bp 成本下重跑
        nav10, _ = backtest(px, W, 1e-3)
        m10 = metrics(nav10)
        pw, pp = layer2(monthly(nav), monthly(ew_nav))
        eras = era_table(nav, ew_nav)
        stable = all(r["跑赢等权"] and r["夏普>0.3"] for r in eras)
        excess10 = m10["年化"] - m_ew["年化"]
        tradable = excess10 >= 0.03 and turn10 <= 12

        summary.append(
            {
                "变体": label,
                "年化": m["年化"],
                "夏普": m["夏普"],
                "回撤": m["最大回撤"],
                "等权年化": m_ew["年化"],
                "②p值(置换)": pp,
                "③每段稳": stable,
                "④10bp年超额": excess10,
                "④年换手": turn10,
                "④可交易": tradable,
            }
        )

        print(f"\n■ {label}  (年换手 {turn5:.1f}@5bp / {turn10:.1f}@10bp)")
        print("  分年代稳定性(第③层):")
        for r in eras:
            print(
                f"   {r['年代']}: 年化 {r['年化']:+.1%} 夏普 {r['夏普']:.2f} "
                f"回撤 {r['回撤']:.1%} | 等权 {r['等权年化']:+.1%} | "
                f"跑赢等权 {r['跑赢等权']} 夏普>0.3 {r['夏普>0.3']}"
            )
        # 附加观察: 动量崩溃月
        for p, v in monthly(nav).items():
            if str(p) in {"2020-03", "2024-01"}:
                print(f"   [观察] {p} 月收益: {v:+.1%}")

    sm = pd.DataFrame(summary)
    print("\n== 汇总 (全历史, 5bp) ==")
    print(sm.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    # ---- 鲁棒性邻域: V2 在 {10,20,60}x{K=1,2,3} ----
    print("\n== 鲁棒性检查 (V2, 全历史, 5bp) ==")
    grid = []
    for mw in [10, 20, 60]:
        for k in [1, 2, 3]:
            W = momentum_weights(px, 2, mom_win=mw, k=k)
            nav, _ = backtest(px, W, 5e-4)
            m = metrics(nav)
            grid.append({"动量窗": mw, "K": k, "年化": m["年化"], "夏普": m["夏普"]})
    print(pd.DataFrame(grid).to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    # ---- Leave-one-out: V2 逐个剔除资产 ----
    print("\n== Leave-one-out (V2) ==")
    for drop in list(POOL):
        sub = px[[c for c in px.columns if c != drop]]
        W = momentum_weights(sub, 2)
        nav, _ = backtest(sub, W, 5e-4)
        m = metrics(nav)
        print(
            f"  剔除 {POOL[drop]:<6}: 年化 {m['年化']:+.1%} 夏普 {m['夏普']:.2f} 回撤 {m['最大回撤']:.1%}"
        )

    # ---- 图 ----
    fig, ax = plt.subplots(figsize=(11.5, 6))
    for label, nav in navs.items():
        ax.plot(nav, lw=1.4, label=label)
    ax.plot(ew_nav, lw=1, alpha=0.8, label="等权全池")
    ax.plot(hs_nav, lw=1, alpha=0.6, label="沪深300")
    ax.axvline(pd.Timestamp(HOLDOUT_START), color="gray", ls="--", lw=1)
    ax.text(
        pd.Timestamp(HOLDOUT_START),
        ax.get_ylim()[1] * 0.9,
        " 保留段起点(只揭榜一次)",
        fontsize=9,
        color="gray",
    )
    ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_title("ETF 动量轮动三变体 (对数净值, 含成本5bp)")
    out = Path(__file__).resolve().parent.parent / "output" / "etf_momentum.png"
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"\n图已保存: {out}")


if __name__ == "__main__":
    main()
