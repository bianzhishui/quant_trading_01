#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 41 低价股长期持有研究 —— 严格按 docs/factor_round41_low_price_quality_plan.md v1.0 实施。

规则(预注册定死):
  池: 主板(sh.60/sz.00, 含退市) + 上市>=375天 + tradestatus==1
  价格: 真实价(在市=前复权/foreAdjustFactor 或 raw_close_fallback; 退市=raw_close_delisted)
  低价: 真实价<=5(主) 子区间 <=2/2-3/3-5 分开报告
  A组: 低价 + 非ST + 真实价可得, 等权
  B组: A + 质量(近3年报扣非全正[披露滞后120天防前视] + 负债率<70% + 20日均额>=500万 + 近3年有分红)
  C组: 全市场(在市)等权; 基准: 沪深300
  调仓: 月末T信号 -> T+1收盘执行, 月频, 等权; 成本 15bp/45bp
  退市: 持仓中退市股在最后交易日记 -100%(归零); 敏感性: 最后价清算 + 剔除吸收合并退市股
判定(预注册): ①B vs A 年化超额>=3pp ②回撤降幅>=10pp ③三段>=2段B跑赢全市场
              ④B退市暴露显著低于A ⑤45bp下B超额>=1pp
用法: uv run python scripts/factor_round41_low_price.py [--limit N] [--start YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config
from quant_trading_01.data_io import load_full_daily, stock_basic
from quant_trading_01.dividend_factor import month_last_days, metrics

# ---- 冻结(预注册)参数 ----
LOW_PRICE = 5.0
COST_BASE = 0.0015
COST_HIGH = 0.0045


def _cfg():
    return get_config()


def load_data() -> dict:
    """加载全市场数据(含退市), 返回各宽表。"""
    cfg = _cfg()
    full = load_full_daily()
    full["date"] = pd.to_datetime(full["date"])
    close = full.pivot(index="date", columns="code", values="close").sort_index()
    close = close.loc[cfg.r5.start :]
    amount = full.pivot(index="date", columns="code", values="amount").sort_index()
    amount = amount.loc[cfg.r5.start :]
    isst = full.pivot(index="date", columns="code", values="isST").sort_index()
    isst = isst.loc[cfg.r5.start :]
    tst = full.pivot(index="date", columns="code", values="tradestatus").sort_index()
    tst = tst.loc[cfg.r5.start :]

    sb = stock_basic().set_index("code")
    ipo = sb["ipoDate"].astype(str).str.strip()
    ipo[ipo.isin(["", "NaT", "nan", "None"])] = np.nan
    ipo_date = pd.to_datetime(ipo, errors="coerce")
    out = sb["outDate"].astype(str).str.strip()
    out[out.isin(["", "NaT", "nan", "None"])] = np.nan
    out_date = pd.to_datetime(out, errors="coerce")
    board_ok = pd.Series(
        {
            c: not (c.startswith("bj.") or c[3:6] in {"300", "688"})
            for c in close.columns
        }
    )

    # 真实价
    fac = pd.read_parquet(cfg.paths.round2 + "/adjust_factor.parquet")
    fac["date"] = pd.to_datetime(fac["date"])
    rf = pd.read_parquet(cfg.paths.round2 + "/raw_close_fallback.parquet")
    rf["date"] = pd.to_datetime(rf["date"])
    rd = pd.read_parquet(cfg.paths.round2 + "/raw_close_delisted.parquet")
    rd["date"] = pd.to_datetime(rd["date"])

    real = close.copy()
    for code in close.columns:
        f = fac[fac["code"] == code]
        if len(f):
            s = f.set_index("date")["foreAdjustFactor"]
            s = s[~s.index.duplicated()].sort_index()
            fac_ser = s.reindex(close.index).ffill().fillna(1.0)
            real[code] = close[code] / fac_ser
        elif code in set(rf["code"]):
            s = rf[rf["code"] == code].set_index("date")["raw_close"]
            real[code] = s.reindex(close.index, method="ffill")
        elif code in set(rd["code"]):
            s = rd[rd["code"] == code].set_index("date")["raw_close"]
            real[code] = s.reindex(close.index, method="ffill")
        else:
            real[code] = np.nan

    # 财务(12-31年报: 扣非/负债率), T 时点可见 = report_date + 120天 <= T
    fq = pd.read_parquet(cfg.paths.round2 + "/financial_quality.parquet")
    fq["report_date"] = pd.to_datetime(fq["report_date"])
    ann = fq[(fq["report_date"].dt.month == 12)].sort_values("report_date")
    ann["visible"] = ann["report_date"] + pd.Timedelta(days=_cfg().p3.disclose_lag)
    ded = ann.pivot_table(
        index="report_date", columns="code", values="deducted_profit"
    ).reindex(columns=close.columns)
    debt = ann.pivot_table(
        index="report_date", columns="code", values="debt_ratio"
    ).reindex(columns=close.columns)
    roe = ann.pivot_table(index="report_date", columns="code", values="roe").reindex(
        columns=close.columns
    )

    # 分红: T 前有记录(历史任意时点)
    dv = pd.read_parquet(cfg.paths.round2 + "/dividends.parquet")
    dv["date"] = pd.to_datetime(dv["date"])
    div_code = set(dv["code"])

    # 吸收合并退市(敏感性): 扣非为正的退市股近似(plan: 21只)
    return {
        "close": close,
        "amount": amount,
        "isst": isst,
        "tst": tst,
        "real": real,
        "ipo_date": ipo_date,
        "out_date": out_date,
        "board_ok": board_ok,
        "ded": ded,
        "debt": debt,
        "roe": roe,
        "div_code": div_code,
        "dv": dv,
    }


def ret_matrix(close: pd.DataFrame, out_date: pd.Series, mode: str) -> pd.DataFrame:
    """前复权收益矩阵 + 退市处理。mode: zero(归零) / last(最后价清算)。"""
    ret = close.pct_change()
    last_row = close.dropna(how="all").index
    for code in out_date.index:
        d = out_date[code]
        if pd.isna(d) or code not in close.columns:
            continue
        col = close[code].dropna()
        if len(col) == 0:
            continue
        d_last = col.index[-1]
        # 找 d_last 后的下一个全局交易日
        pos = last_row.get_loc(d_last)
        if pos + 1 >= len(last_row):
            continue
        d_out = last_row[pos + 1]
        if mode == "zero":
            ret.loc[d_out, code] = -1.0  # 最后价 -> 0
        else:
            ret.loc[d_out, code] = 0.0  # 最后价清算(之后无损益)
    return ret.fillna(0.0)


def build_sets(
    data: dict,
    limit: int | None = None,
    sub_price: tuple | None = None,
    n_years: int = 1,
    freq: int = 1,
    roe_min: float | None = None,
    dy_min: float | None = None,
    mom_drop: float | None = None,
    top_n: int | None = None,
) -> tuple[dict, dict, dict, list, dict]:
    """逐月信号: A组/B组/C组集合 + 记录(低价数/退市数)。

    n_years: 扣非条件 = 最近 n 个已披露年报均为正(默认 1 = 原口径最近年报;
             严格 3 年 = plan 文字语义)。历史归档(R41/42/43)为 n_years=1,
             较 plan 文字(3年)宽松 —— 已在 R44 复核。
    freq: 重选频率(月数), 默认 1 = 每月; 12/36/60 = 年/3年/5年持有(R45)。
    roe_min/dy_min/mom_drop/top_n: R46 收益更大化探索参数(默认 None = 不启用)。
    """
    close, real = data["close"], data["real"]
    amount, isst, tst = data["amount"], data["isst"], data["tst"]
    ded, debt, roe = data["ded"], data["debt"], data["roe"]
    ipo_date = data["ipo_date"]
    idx = close.index
    sig_days = [
        t
        for t in month_last_days(idx)
        if idx.get_loc(t) + 1 < len(idx)
        and t >= pd.Timestamp("2014-01-01")  # 回测窗口(plan)
    ]
    if limit:
        sig_days = sig_days[:limit]
    if freq > 1:  # R45: 每 freq 个月重选一次
        sig_days = sig_days[::freq]

    A, B, C = {}, {}, {}
    rec = []
    for T in sig_days:
        exec_day = idx[idx.get_loc(T) + 1]
        age_ok = ((pd.Timestamp(T) - ipo_date).dt.days >= _cfg().p3.seasoning).astype(
            bool
        )
        tst_ok = tst.loc[T].astype(str) == "1"
        board = pd.Series(data["board_ok"])
        real_T = real.loc[T]
        # 低价(主口径或子区间)
        if sub_price:
            lo, hi = (
                sub_price  # 区间由调用方决定(如 P3 读配置 price_lo/hi), 无 5 元暗截断
            )
            price_ok = real_T.between(lo, hi, inclusive="left")
        else:
            price_ok = real_T <= LOW_PRICE
        not_st = isst.loc[T].astype(str) != "1"
        elig = (age_ok & tst_ok & board & price_ok & not_st & real_T.notna()).astype(
            bool
        )
        elig_codes = list(elig[elig].index)
        rec.append({"T": T, "low": len(elig_codes)})
        A[exec_day] = set(elig_codes)
        # B: 质量筛选
        B_set = set()
        if elig_codes:
            visible = ded.index[
                ded.index + pd.Timedelta(days=_cfg().p3.disclose_lag) <= T
            ]
            if len(visible):
                last_n = visible[-n_years:]  # 最近 n 个已披露年报
                d_ok = (ded.loc[last_n, elig_codes] > 0).all(axis=0)  # n 年均正
                debt_v = debt.loc[visible[-1], elig_codes]
                amt20 = amount.loc[T - pd.Timedelta(days=40) : T, elig_codes].mean()
                # 近3年分红(除权日 <= T)
                dv = data["dv"]
                has_div = pd.Series(
                    {
                        c: c in data["div_code"]
                        and (
                            dv[(dv["code"] == c) & (dv["date"] <= T)]["date"].nunique()
                            >= 1
                        )
                        for c in elig_codes
                    }
                )
                qual = (
                    d_ok.fillna(False)
                    & (debt_v.fillna(1.0) < _cfg().p3.debt_max)
                    & (amt20.fillna(0) >= _cfg().p3.liq_min)
                    & has_div
                )
                # R46 扩展条件
                if roe_min is not None:
                    roe_v = roe.loc[visible[-1], elig_codes]
                    qual = qual & (roe_v.fillna(-1) > roe_min)
                if dy_min is not None:
                    dy = pd.Series(
                        {
                            c: (
                                dv[(dv["code"] == c) & (dv["date"] <= T)][
                                    "cashBeforeTax"
                                ].sum()
                                / real_T[c]
                                if real_T[c] and real_T[c] > 0
                                else 0.0
                            )
                            for c in elig_codes
                        }
                    )
                    qual = qual & (dy >= dy_min)
                if mom_drop is not None:
                    iloc = close.index.get_loc(T)
                    if iloc >= 126:
                        mom6 = (
                            close.loc[T, elig_codes]
                            / close.iloc[iloc - 126][elig_codes].reindex(elig_codes)
                            - 1.0
                        )
                        qual = qual & (mom6.fillna(1.0) > -mom_drop)
                B_set = set(qual[qual].index)
                if top_n and len(B_set) > top_n:
                    ded_amt = ded.loc[visible[-1], list(B_set)]
                    B_set = set(ded_amt.nlargest(top_n).index)
        B[exec_day] = B_set
        # C: 全市场(在市)等权基准
        c_ok = (tst_ok & board & close.loc[T].notna()).astype(bool)
        C[exec_day] = set(c_ok[c_ok].index)
    return A, B, C, rec, {"ded": ded, "debt": debt}


def ew_nav(ret: pd.DataFrame, sets: dict, cost: float) -> pd.Series:
    """逐日等权持仓模拟(退市收益已在 ret 内)。"""
    cols = ret.columns
    W = pd.DataFrame(0.0, index=ret.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    for dt in ret.index:
        if dt in sets:
            S = sets[dt]
            w = pd.Series(0.0, index=cols)
            if S:
                w[list(S)] = 1.0 / len(S)
        W.iloc[W.index.get_loc(dt)] = w
    turn = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
    nav = (1 + gross - turn * cost).cumprod()
    return nav


def delist_exposure(sets: dict, out_date: pd.Series) -> pd.Series:
    """逐月持仓中退市股数量占比。"""
    rows = []
    for dt, S in sets.items():
        if not S:
            continue
        n_del = sum(1 for c in S if c in out_date.index and not pd.isna(out_date[c]))
        rows.append(
            {"T": dt, "delist_ratio": n_del / len(S), "n_del": n_del, "n": len(S)}
        )
    return pd.DataFrame(rows).set_index("T")


def main() -> None:
    ap = argparse.ArgumentParser(description="Round41 低价股研究")
    ap.add_argument("--config", default=None)
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个月(测试)")
    ap.add_argument("--mode", default="zero", choices=["zero", "last"], help="退市处理")
    ap.add_argument(
        "--exclude-merge",
        action="store_true",
        help="敏感性: 剔除吸收合并退市(扣非为正的退市股)",
    )
    args = ap.parse_args()

    from quant_trading_01.config import load_config

    load_config(args.config)
    t0 = time.time()
    print("加载数据...", flush=True)
    data = load_data()
    print(
        f"数据就绪: {data['close'].shape[0]} 日 × {data['close'].shape[1]} 只, {time.time() - t0:.0f}s",
        flush=True,
    )

    out_date = data["out_date"]
    if args.exclude_merge:
        # 吸收合并退市近似: 退市前3年报扣非全正的退市股(plan 风险1)
        fq = pd.read_parquet(_cfg().paths.round2 + "/financial_quality.parquet")
        fq["report_date"] = pd.to_datetime(fq["report_date"])
        ann = fq[fq["report_date"].dt.month == 12]
        merge_like = set()
        for c in out_date.index:
            a = ann[(ann["code"] == c) & (ann["report_date"] < out_date[c])]
            if len(a) and (a["deducted_profit"].tail(3) > 0).all():
                merge_like.add(c)
        print(f"吸收合并近似退市股(剔除敏感性): {len(merge_like)} 只", flush=True)
        out_date = out_date.drop(index=[c for c in merge_like if c in out_date.index])

    print("构建收益矩阵与月度组合...", flush=True)
    ret = ret_matrix(data["close"], out_date, args.mode)
    A, B, C, rec, _ = build_sets(data, args.limit)

    navA = ew_nav(ret, A, COST_BASE)
    navB = ew_nav(ret, B, COST_BASE)
    navC = ew_nav(ret, C, COST_BASE)
    navB45 = ew_nav(ret, B, COST_HIGH)

    m = {
        k: metrics(v)
        for k, v in [
            ("A无差别低价", navA),
            ("B质量筛选", navB),
            ("C全市场", navC),
            ("B45", navB45),
        ]
    }
    print("\n== 结果(15bp 基础成本) ==")
    for k in ["A无差别低价", "B质量筛选", "C全市场"]:
        print(
            f"  {k}: 年化 {m[k]['年化']:+.1%} 夏普 {m[k]['夏普']:.2f} 回撤 {m[k]['最大回撤']:.1%}"
        )
    print(f"  B(45bp): 年化 {m['B45']['年化']:+.1%}")

    exc = m["B质量筛选"]["年化"] - m["A无差别低价"]["年化"]
    dd_imp = m["A无差别低价"]["最大回撤"] - m["B质量筛选"]["最大回撤"]
    print("\n== 判定 ==")
    print(f"  ① B-A 年化超额: {exc:+.1%} (>=3pp: {exc >= 0.03})")
    print(f"  ② 回撤降幅: {dd_imp:+.1%} (>=10pp: {dd_imp >= 0.10})")
    # 分年代
    eras = _cfg().r5.eras.to_dict()
    stable = 0
    for name, (s, e) in eras.items():
        a = navB[s:e] / navB[s:e].dropna().iloc[0]
        c = navC[s:e] / navC[s:e].dropna().iloc[0]
        ma, mc = metrics(a), metrics(c)
        ok = ma["年化"] > 0 and ma["年化"] > mc["年化"]
        stable += ok
        print(f"  {name}: B {ma['年化']:+.1%} vs C {mc['年化']:+.1%} 跑赢:{ok}")
    print(f"  ③ 分年代稳定性: {stable}/3 (>=2 通过: {stable >= 2})")
    # 退市暴露
    exA, exB = (
        delist_exposure(A, data["out_date"]),
        delist_exposure(B, data["out_date"]),
    )
    if len(exA) and len(exB):
        dA, dB = exA["delist_ratio"].mean(), exB["delist_ratio"].mean()
        print(f"  ④ 退市暴露均值: A {dA:.1%} vs B {dB:.1%} (B显著低: {dB < dA * 0.5})")
    # 45bp
    exc45 = m["B45"]["年化"] - m["C全市场"]["年化"]
    print(f"  ⑤ B(45bp) vs C 超额: {exc45:+.1%} (>=1pp: {exc45 >= 0.01})")

    # 子区间
    print("\n== 子区间(真实价) ==")
    for lo, hi in [(0, 2), (2, 3), (3, 5)]:
        A2, B2, _, _, _ = build_sets(data, args.limit, sub_price=(lo, hi))
        navB2 = ew_nav(ret, B2, COST_BASE)
        rec2 = pd.DataFrame(_build_rec(data, args.limit, (lo, hi)))
        print(
            f"  {lo}-{hi}元: B年化 {metrics(navB2)['年化']:+.1%} 回撤 {metrics(navB2)['最大回撤']:.1%} 月均低价 {rec2['low'].mean():.0f} 只"
        )

    print(f"\n总耗时 {time.time() - t0:.0f}s")


def _build_rec(data: dict, limit: int | None, sub_price: tuple | None) -> list:
    _, _, _, rec, _ = build_sets(data, limit, sub_price)
    return rec


if __name__ == "__main__":
    main()
