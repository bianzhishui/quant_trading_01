#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""P3 场景回放: 指定起始日期建仓, 八账户的每日净值(对齐 R5 scenario_ytd)。

同一套 P3 策略(真实价3-4元+质量+等权月频) + 全口径成本(佣金万1.5最低5元/印花万5/
过户万0.1/1手取整/现金无息/因子事件补分红税后10%/涨跌停阻塞), 仅建仓起点可指定。
不触碰正式账本(ledger_p3_aum*.json), 输出:
  output/p3/daily_nav_{START}_aum{3w..600w}.csv   (date, nav, 涨幅%, 较本金盈亏)

用法: python scripts/p3/scenario_ytd_p3.py [--start 2025-01-01]   (默认 2026-01-01)
核心: run_scenario_p3(start, end, out_prefix, verbose) 可导入复用。
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from quant_trading_01.config import get_config, load_config  # noqa: E402
from scripts.r5.paper_trade import PaperPortfolio  # noqa: E402
from scripts.r5.paper_live import _factor_panel  # noqa: E402  # 场景回放用静态因子(与R5一致), 不混入运营live增量
from scripts.factor_round41_low_price import build_sets, load_data as load_data_p3  # noqa: E402


def run_scenario_p3(
    start: str,
    end: str | None = None,
    out_prefix: str | None = None,
    verbose: bool = True,
    aums: list | None = None,
    block: bool = True,
    target_fn=None,
    detail: list | None = None,
    low_vol_keep: float | None = None,
    low_vol_window: int = 60,
) -> dict[str, pd.Series]:
    """P3 场景回放: 指定建仓起点, 返回 {tag: nav Series}。

    aums: 限定账户(默认 None = 配置七账户); block: 涨跌停阻塞(R50 E3 对照用, 默认 True)。
    target_fn: 可选 (信号日 T, 原始目标集合) -> 目标集合; None(默认) = 不额外截断
               (R53 研究钩子; **不要与 low_vol_keep 同时用**, 否则双重截断)。
    detail: 可选 list; 给出时把每次调仓明细(含 n_target/n_hold/n_fail/cash/fee)追加进去,
            不影响任何默认输出(CSV 列不变)。
    low_vol_keep/low_vol_window: R54 A1 低波截断, 直接转发 build_sets(默认 None = 不启用)。
    """
    cfg = get_config()
    aum_list = aums if aums is not None else cfg.p3.aum_list
    out = Path(cfg.p3.out_dir)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) if end else None

    data = load_data_p3()
    close = data["close"]
    raw = data["real"]
    # R56: 估值口径与生产 paper_live_p3 统一 —— 估值用 raw.ffill()(停牌沿用最后价, 与 R48 一致),
    # 成交/除权补缺/1手买不起判断仍用原始价 raw。此前全程用 raw 估值 → 停牌持仓市值记 0,
    # 触发换手/费用死亡螺旋(R53 §0.1 全样本窗口因此作废)。
    raw_e = raw.ffill()
    tst = data["tst"]
    ret = close.pct_change()  # 涨跌停阻塞需执行日涨幅
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    idx = close.index
    A, B, C, _, _ = build_sets(
        data,
        None,
        sub_price=(cfg.p3.price_lo, cfg.p3.price_hi),
        n_years=cfg.p3.n_years,
        low_vol_keep=low_vol_keep,  # R54 A1(与 paper_live_p3 同口径)
        low_vol_window=low_vol_window,
    )
    from quant_trading_01.dividend_factor import month_last_days

    sig = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    rebs = []
    for T in sig:
        ex = idx[idx.get_loc(T) + 1]
        if ex in B:
            rebs.append({"T": T, "exec": ex, "target": B[ex]})
    F = _factor_panel(close)
    F_prev = F.shift(1).fillna(F.iloc[0])

    rb0 = next(r for r in rebs if r["exec"].date() >= start_ts.date())
    rb_by_exec = {
        r["exec"]: r
        for r in rebs
        if r["T"] >= rb0["T"]
        and r["exec"] <= idx[-1]
        and (end_ts is None or r["exec"] <= end_ts)
    }
    i0 = idx.get_loc(rb0["exec"])
    i1 = (
        idx.get_indexer([end_ts], method="ffill")[0]
        if end_ts is not None
        else len(idx) - 1
    )
    if verbose:
        print(
            f"== P3 建仓场景: 信号 {rb0['T'].date()} → 建仓执行 {rb0['exec'].date()} "
            f"({len(rb_by_exec)} 次月频调仓, 至 {idx[i1].date()}) =="
        )
    result: dict[str, pd.Series] = {}
    for aum in aum_list:
        pf = PaperPortfolio(aum, 0.0015)  # 滑点 15bp, 与回测/账本口径统一
        navs = []
        funds_rows = []
        prev_post = None
        for i in range(i0, i1 + 1):
            prices = raw.iloc[i]
            if i > i0:  # 因子事件补除权缺口
                fn, fp = F.iloc[i], F_prev.iloc[i]
                for c in list(pf.shares.keys()):
                    if fn[c] != fp[c]:
                        pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])
            rb = rb_by_exec.get(idx[i])
            if rb is not None:
                pre_nav = pf.value(raw_e.iloc[i])  # R56: 估值用 ffill 价
                div_before = pf.div_cash
                target = (
                    rb["target"]
                    if target_fn is None
                    else target_fn(rb["T"], rb["target"])
                )
                pf.rebalance(
                    target,
                    prices,
                    trad.loc[idx[i]],
                    ret.loc[idx[i]] if block else None,  # R50 E3: None = 无阻塞理想口径
                )
                post_nav = pf.value(raw_e.iloc[i])  # R56: 估值用 ffill 价
                buy = sum(t["amount"] for t in pf.trades if t["side"] == "buy")
                sell = sum(t["amount"] for t in pf.trades if t["side"] == "sell")
                fee = sum(
                    t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades
                )
                # R53: 实际持仓只数 / 因 1 手约束或涨跌停无法建仓的目标数
                n_target = len(target)
                n_fail = len([c for c in target if pf.shares.get(c, 0) <= 0])
                # R53 诊断: 按理论等权额度(pre_nav/n_target)连 1 手都买不起的目标数
                _budget = pre_nav / max(n_target, 1)
                n_1lot_short = len(
                    [
                        c
                        for c in target
                        if pd.notna(prices.get(c, np.nan))
                        and 100.0 * float(prices[c]) > _budget
                    ]
                )
                funds_rows.append(
                    {
                        "date": str(idx[i].date()),
                        "pre_nav": pre_nav,
                        "post_nav": post_nav,
                        "mret": (post_nav / prev_post - 1) * 100
                        if prev_post is not None
                        else None,
                        "buy": buy,
                        "sell": sell,
                        "turnover": (buy + sell) / 2 / pre_nav * 100
                        if pre_nav
                        else 0.0,
                        "fee": fee,
                        "div": pf.div_cash - div_before,
                        "cash": pf.cash,
                        "pos": post_nav - pf.cash,
                        "n_target": n_target,
                        "n_hold": n_target - n_fail,
                        "n_fail": n_fail,
                        "n_1lot_short": n_1lot_short,
                    }
                )
                prev_post = post_nav
                pf.trades = []
            navs.append(pf.value(raw_e.iloc[i]))  # R56: 估值用 ffill 价
        nav = pd.Series(navs, index=idx[i0 : i1 + 1])
        result[f"aum{int(aum / 1e4)}w"] = nav
        if out_prefix is not None:
            nav_ret = nav.pct_change() * 100
            df = pd.DataFrame(
                {
                    "date": nav.index.strftime("%Y-%m-%d"),
                    "nav": nav.round(2),
                    "涨幅%": nav_ret.round(4),
                    "较本金盈亏": (nav - aum).round(2),
                }
            )
            df.to_csv(
                out / f"daily_nav_{out_prefix}_aum{int(aum / 1e4)}w.csv", index=False
            )
            fdf = pd.DataFrame(
                [
                    {
                        "date": r["date"],
                        "pre_nav": r["pre_nav"],
                        "post_nav": r["post_nav"],
                        "月涨幅%": r["mret"],
                        "买入额": r["buy"],
                        "卖出额": r["sell"],
                        "换手率%": r["turnover"],
                        "费用": r["fee"],
                        "分红入账": r["div"],
                        "期末现金": r["cash"],
                        "期末持仓": r["pos"],
                        "较本金盈亏": r["post_nav"] - aum,
                    }
                    for r in funds_rows
                ]
            )
            cols = [
                "date",
                "pre_nav",
                "post_nav",
                "月涨幅%",
                "买入额",
                "卖出额",
                "换手率%",
                "费用",
                "分红入账",
                "期末现金",
                "期末持仓",
                "较本金盈亏",
            ]
            fdf[cols].to_csv(
                out / f"monthly_funds_{out_prefix}_aum{int(aum / 1e4)}w.csv",
                index=False,
            )
            cum = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
            print(
                f"\n[{int(aum / 1e4)}万] {nav.index[0].date()} → {nav.index[-1].date()} "
                f"({len(nav) - 1} 个交易日) | 期间累计 {cum:+.2f}%"
            )
        if detail is not None:
            for r in funds_rows:
                r["aum"] = aum
            detail.extend(funds_rows)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default=None, help="截止日期(含), 默认数据末尾")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    load_config(args.config)
    prefix = pd.Timestamp(args.start).strftime("%Y%m%d")
    # R54: 场景回放与生产同口径(读配置的 A1 低波截断)
    run_scenario_p3(
        args.start,
        args.end,
        out_prefix=prefix,
        verbose=True,
        low_vol_keep=get_config().p3.low_vol_keep,
        low_vol_window=get_config().p3.low_vol_window,
    )


if __name__ == "__main__":
    main()
