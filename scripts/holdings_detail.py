#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""持仓明细(账户级下钻): 每只持仓股票的 成本/现价/市值/当日涨幅/盈亏/权重。

跨 R5/P3 两策略。成本 = 账本 trades 净投入(Σ买入额+费用 − Σ卖出净回笼) / 当前股数;
市值/盈亏用真实价(与账本 mark 口径一致); 当日涨幅用前复权 close(剔除除权)。

用法:
  .venv/bin/python scripts/holdings_detail.py --strat r5 --aum 600000
  .venv/bin/python scripts/holdings_detail.py --strat p3 --aum 600000 [--csv]
输出: 终端表 + output/{r5|p3}/holdings_detail_{YYYY-MM-DD}.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config, load_config  # noqa: E402
from quant_trading_01.data_io import stock_basic  # noqa: E402


def load_prices():
    """全市场 真实价(real) + 前复权 close + 当日涨幅(close pct)。"""
    from scripts.factor_round41_low_price import load_data

    data = load_data()
    real = data["real"]
    close = data["close"]
    ret_d = close.pct_change()
    return real, close, ret_d


def compute_detail(led: dict, real, close, ret_d, names: dict) -> pd.DataFrame:
    """从账本 trades 计算每只持仓的成本/盈亏。"""
    shares = {k: int(v) for k, v in led["shares"].items() if int(v) > 0}
    # 净投入成本: Σ(买: 金额+佣金+过户) − Σ(卖: 金额−佣金−印花−过户)
    net = {}
    for t in led["trades"]:
        c = t["code"]
        if t["side"] == "buy":
            net[c] = (
                net.get(c, 0.0) + t["amount"] + t.get("佣金", 0) + t.get("过户费", 0)
            )
        else:
            net[c] = net.get(c, 0.0) - (
                t["amount"] - t.get("佣金", 0) - t.get("印花税", 0) - t.get("过户费", 0)
            )
    rows = []
    last_date = close.index[-1]
    for c, qty in shares.items():
        px_real = real.loc[last_date, c] if c in real.columns else np.nan
        ret_today = ret_d.loc[last_date, c] if c in ret_d.columns else np.nan
        mkt = qty * px_real if pd.notna(px_real) else np.nan
        cost_net = net.get(c, 0.0)
        cost_px = cost_net / qty if cost_net > 0 and qty > 0 else 0.0
        pnl = mkt - cost_net if pd.notna(mkt) else np.nan
        pnl_pct = pnl / cost_net if pd.notna(pnl) and cost_net > 0 else np.nan
        rows.append(
            {
                "code": c,
                "name": names.get(c, ""),
                "shares": qty,
                "cost_px": round(cost_px, 3),
                "px": round(px_real, 3) if pd.notna(px_real) else np.nan,
                "mkt_val": mkt,
                "ret_today": ret_today,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )
    df = pd.DataFrame(rows).sort_values(
        "ret_today", ascending=False, na_position="last"
    )
    total_mkt = df["mkt_val"].sum()
    df["weight"] = (
        df["mkt_val"] / total_mkt if total_mkt and total_mkt == total_mkt else 0.0
    )
    return df


def print_table(aum: float, df: pd.DataFrame, strat: str):
    total = df["mkt_val"].sum()
    print(
        f"\n== {strat.upper()} {int(aum / 1e4)}万 持仓明细 "
        f"({len(df)} 只) | 持仓市值 {total / 1e4:.1f}万 | "
        f"持仓盈亏 {df['pnl'].sum() / 1e4:+.1f}万 "
        f"(+{df[df['pnl'] > 0]['pnl'].sum() / 1e4:.1f}/-{df[df['pnl'] < 0]['pnl'].sum() / 1e4:.1f}) =="
    )
    print(
        f"{'代码':<10}{'名称':<8}{'股数':>7}{'成本价':>8}{'现价':>8}{'市值(元)':>12}"
        f"{'当日%':>7}{'盈亏(元)':>12}{'盈亏率':>8}{'权重':>6}"
    )
    for _, r in df.iterrows():
        rp = f"{r['pnl_pct']:+.1%}" if pd.notna(r["pnl_pct"]) else "-"
        rt = f"{r['ret_today']:+.2%}" if pd.notna(r["ret_today"]) else "-"
        print(
            f"{r['code']:<10}{r['name']:<8}{r['shares']:>7,}{r['cost_px']:>8.2f}"
            f"{r['px']:>8.2f}{r['mkt_val']:>12,.0f}{rt:>7}{r['pnl']:>+12,.0f}{rp:>8}{r['weight']:>6.1%}"
        )


COL_MAP = {
    "code": "code(代码)",
    "name": "name(名称)",
    "shares": "shares(股数)",
    "cost_px": "cost_px(成本价)",
    "px": "px(现价)",
    "mkt_val": "mkt_val(市值元)",
    "ret_today": "ret_today(当日涨幅)",
    "pnl": "pnl(盈亏元)",
    "pnl_pct": "pnl_pct(盈亏率)",
    "weight": "weight(权重)",
}


def _ledger_path(strat: str, aum: float) -> Path:
    return (
        Path(f"output/{strat}/ledger_p3_aum{int(aum / 1e4)}w.json")
        if strat == "p3"
        else Path(f"output/{strat}/ledger_aum{int(aum / 1e4)}w.json")
    )


def run_one(aum: float, strat: str, real, close, ret_d, names) -> None:
    led_path = _ledger_path(strat, aum)
    if not led_path.exists():
        print(f"账本不存在: {led_path}")
        return
    led = json.loads(led_path.read_text())
    df = compute_detail(led, real, close, ret_d, names)
    print_table(aum, df, strat)
    csv = (
        Path(f"output/{strat}")
        / f"holdings_detail_{strat}_{int(aum / 1e4)}w_{str(close.index[-1].date())}.csv"
    )
    df.round(2).rename(columns=COL_MAP).to_csv(csv, index=False)
    print(f"已导出: {csv}")


def main() -> None:
    ap = argparse.ArgumentParser(description="持仓明细(成本/现价/涨幅/盈亏)")
    ap.add_argument("--strat", required=True, choices=["r5", "p3", "both"])
    ap.add_argument("--aum", type=float, default=None, help="单账户, 如 600000")
    ap.add_argument(
        "--all", action="store_true", help="跑该策略全部账户(数据只加载一次)"
    )
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    load_config(args.config)

    # 确定账户清单
    cfg = get_config()
    if args.aum:
        aums = [(args.strat, args.aum)]
    elif args.all or args.strat == "both":
        aums = []
        for st in [args.strat] if args.strat != "both" else ["r5", "p3"]:
            lst = cfg.r5.aum_list if st == "r5" else cfg.p3.aum_list
            aums.extend((st, a) for a in lst)
    else:
        print("需指定 --aum <金额> 或 --all(全部账户)")
        return

    print(f"加载全市场数据(1次, 供 {len(aums)} 个账户)...", flush=True)
    real, close, ret_d = load_prices()
    names = dict(zip(stock_basic()["code"], stock_basic()["code_name"]))
    for strat, aum in aums:
        run_one(aum, strat, real, close, ret_d, names)


if __name__ == "__main__":
    main()
