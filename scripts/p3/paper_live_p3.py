#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""P3 模拟盘长期运营 —— 8 账户(3万/10万/20万/30万/60万/100万/300万/600万)。

策略 P3: 真实价 3.0-4.0 元 + 近3年扣非为正 + 负债率<70% + 流动性 + 分红 + 等权月频。
引擎/费用/账本机制复用 paper_live(PaperPortfolio), 信号换 P3 build_sets。
账本: output/ledger_p3_aum{XX}w.json | 月度: monthly_funds_p3_aum*.csv /
      monthly_holdings_p3_aum*.csv | 每日: daily_nav_p3_aum*.csv
用法:
  python scripts/p3/paper_live_p3.py init                 # 建仓 8 账户
  python scripts/p3/paper_live_p3.py init --aum 100000    # 单账户
  python scripts/p3/paper_live_p3.py step                 # 推进全部账本(月调仓)
  python scripts/p3/paper_live_p3.py mark                 # 每日涨幅(全部)
  python scripts/p3/paper_live_p3.py report               # 全部账本报告
数据: 全市场 full_daily(经 data_io) + financial_quality + dividends + raw_close_*(真实价)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from quant_trading_01.config import get_config, load_config  # noqa: E402
from quant_trading_01.data_io import data_version  # noqa: E402
from quant_trading_01.dividend_factor import month_last_days  # noqa: E402
from scripts.r5.paper_trade import (  # noqa: E402
    PaperPortfolio,
    amount_slip_series,
)
from scripts.r5.paper_live import (  # noqa: E402
    _apply_corp_period,
    _bench_levels,
    _factor_panel_cached,
)
from scripts.factor_round41_low_price import (  # noqa: E402
    build_sets,
    load_data as load_data_p3,
)


_CORE = None
_CORE_KEY = None
_F_PANEL = None
_F_PANEL_KEY = None


def _cfg():
    return get_config()


def _mtime(p: Path | str) -> int | None:
    try:
        return int(Path(p).stat().st_mtime_ns)
    except FileNotFoundError:
        return None


def ledger_path(aum: float) -> Path:
    return Path(_cfg().p3.out_dir) / f"ledger_p3_aum{int(aum / 1e4)}w.json"


def monthly_funds_path(aum: float) -> Path:
    return Path(_cfg().p3.out_dir) / f"monthly_funds_p3_aum{int(aum / 1e4)}w.csv"


def holdings_path(aum: float) -> Path:
    return Path(_cfg().p3.out_dir) / f"monthly_holdings_p3_aum{int(aum / 1e4)}w.csv"


FUNDS_COLS = [
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


def _append_monthly_funds(aum: float, row: dict):
    r = [
        row["date"],
        round(row["pre_nav"], 2),
        round(row["post_nav"], 2),
        round(row["mret"], 4) if row["mret"] is not None else "",
        round(row["buy"], 2),
        round(row["sell"], 2),
        round(row["turnover"], 3) if row["turnover"] is not None else "",
        round(row["fee"], 2),
        round(row["div"], 2),
        round(row["cash"], 2),
        round(row["pos"], 2),
        round(row["post_nav"] - aum, 2),
    ]
    p = monthly_funds_path(aum)
    if not p.exists():
        p.write_text(",".join(FUNDS_COLS) + "\n")
    with p.open("a") as f:
        f.write(",".join(str(x) for x in r) + "\n")


def _append_holdings_snapshot(aum: float, date_s: str, pf, prices):
    rows = []
    for c, s in pf.shares.items():
        p = prices.get(c, np.nan)
        if pd.notna(p):
            rows.append(
                {
                    "date": date_s,
                    "code": c,
                    "shares": int(s),
                    "close": round(float(p), 3),
                    "value": round(s * p, 2),
                }
            )
    p = holdings_path(aum)
    if not p.exists():
        p.write_text("date,code,shares,close,value\n")
    with p.open("a") as f:
        for r in rows:
            f.write(
                f"{r['date']},{r['code']},{r['shares']},{r['close']},{r['value']}\n"
            )


def _seed_build_row(aum: float):
    p = monthly_funds_path(aum)
    if p.exists():
        return
    path = ledger_path(aum)
    if not path.exists():
        return
    led = json.loads(path.read_text())
    h0 = led["nav_history"][0]
    if len(led["nav_history"]) == 1:
        buy = sum(t["amount"] for t in led["trades"] if t["side"] == "buy")
        sell = sum(t["amount"] for t in led["trades"] if t["side"] == "sell")
    else:
        buy, sell = h0["nav"], 0.0
    _append_monthly_funds(
        aum,
        {
            "date": h0["date"],
            "pre_nav": led["aum"],
            "post_nav": h0["nav"],
            "mret": None,
            "buy": buy,
            "sell": sell,
            "turnover": buy / led["aum"] * 100,
            "fee": led["total_fees"],
            "div": 0.0,
            "cash": led["cash"],
            "pos": h0["nav"] - led["cash"],
        },
    )


def _load_all_p3():
    """P3 面板: (close, amount, tst, isst, ind, raw, rebs, bench, ret)。"""
    global _CORE, _CORE_KEY
    key = (data_version(), _mtime(_cfg().paths.round2 + "/financial_quality.parquet"))
    if _CORE_KEY == key and _CORE is not None:
        return _CORE
    data = load_data_p3()
    close = data["close"]
    amount = data["amount"]
    tst = data["tst"]  # tradestatus('1'=正常); data 键序 isst 在 tst 前, 按键取防错位
    isst = data["isst"]
    raw = data["real"]
    A, B, C, _, _ = build_sets(
        data,
        None,
        sub_price=(_cfg().p3.price_lo, _cfg().p3.price_hi),
        n_years=_cfg().p3.n_years,
    )
    idx = close.index
    sig = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    rebs = []
    for T in sig:
        ex = idx[idx.get_loc(T) + 1]
        if ex in B:
            rebs.append({"T": T, "exec": ex, "target": B[ex]})
    ret = close.pct_change()
    _CORE = (close, amount, tst, isst, None, raw, rebs, C, ret)
    _CORE_KEY = key
    return _CORE


def init_ledger(aum: float, slip: float | None = None, slip_by_amount: bool = False):
    slip = slip if slip is not None else _cfg().costs.slip_default
    close, amount, tst, isst, ind, raw, rebs, bench, ret = _load_all_p3()
    last = rebs[-1]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    pf = PaperPortfolio(aum, slip)
    if slip_by_amount:
        pf.slip_series = amount_slip_series(amount.loc[last["exec"]])
    prices = raw.loc[last["exec"]]
    pf.rebalance(last["target"], prices, trad.loc[last["exec"]], ret.loc[last["exec"]])
    nav = pf.value(prices)
    bench_lv = _bench_levels(rebs, bench, ret)
    bench_base = bench_lv[last["exec"]]
    led = {
        "aum": aum,
        "last_signal": str(last["T"].date()),
        "last_exec": str(last["exec"].date()),
        "bench_base": bench_base,
        "shares": pf.shares,
        "cash": pf.cash,
        "nav_history": [{"date": str(last["exec"].date()), "nav": nav, "bench": 1.0}],
        "trades": pf.trades,
        "div_credited": pf.div_cash,
        "total_fees": round(
            sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades), 2
        ),
        "last_blocked": {
            "date": str(last["exec"].date()),
            "buy": [{"code": c, "amount": a} for c, a in pf.blocked_buys],
            "sell": [{"code": c, "value": v} for c, v in pf.blocked_sells],
        },
    }
    path = ledger_path(aum)
    path.write_text(json.dumps(led, ensure_ascii=False, indent=1))
    _seed_build_row(aum)
    _append_holdings_snapshot(aum, str(last["exec"].date()), pf, prices)
    print(
        f"\n== P3 建账完成 {int(aum / 1e4)}万 == 信号 {led['last_signal']} → 执行 {led['last_exec']}"
        f" | 持仓 {len(pf.shares)} 只 | 现金 {pf.cash / 1e4:.1f}万 ({pf.cash / aum:.1%})"
        f" | NAV {nav / 1e4:.1f}万 | 费用 {led['total_fees']:.0f}元"
    )
    if pf.blocked_buys:
        print(f"  [阻塞] 涨停买不进 {len(pf.blocked_buys)} 只")


def step(aum: float, slip: float | None = None, slip_by_amount: bool = False):
    slip = slip if slip is not None else _cfg().costs.slip_default
    path = ledger_path(aum)
    if not path.exists():
        raise SystemExit(f"账本不存在: {path.name} → 先跑 init")
    led = json.loads(path.read_text())
    close, amount, tst, isst, ind, raw, rebs, bench, ret = _load_all_p3()
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    bench_lv = _bench_levels(rebs, bench, ret)
    todo = [
        r
        for r in rebs
        if r["T"] > pd.Timestamp(led["last_signal"]) and r["exec"] <= close.index[-1]
    ]
    if not todo:
        print(
            f"\n[{int(aum / 1e4)}万] 已是最新(信号 {led['last_signal']}), 无待处理调仓"
        )
        return
    F = _factor_panel_cached(close)
    pf = PaperPortfolio(led["aum"], slip)
    pf.shares = {k: int(v) for k, v in led["shares"].items()}
    pf.cash = float(led["cash"])
    pf.div_cash = float(led.get("div_credited", 0))
    pf.trades = []
    print(f"\n== 推进 {int(aum / 1e4)}万 账本 (待处理 {len(todo)} 个月) ==")
    prev_exec = pd.Timestamp(led["last_exec"])
    _seed_build_row(aum)
    prev_post = led["nav_history"][-1]["nav"]
    step_fees = 0.0
    for rb in todo:
        _apply_corp_period(pf, F, raw, prev_exec, rb["exec"])
        pre_nav = pf.value(raw.loc[rb["exec"]])
        div_before = pf.div_cash
        pf.slip_series = (
            amount_slip_series(amount.loc[rb["exec"]]) if slip_by_amount else None
        )
        pf.rebalance(
            rb["target"], raw.loc[rb["exec"]], trad.loc[rb["exec"]], ret.loc[rb["exec"]]
        )
        post_nav = pf.value(raw.loc[rb["exec"]])
        buy = sum(t["amount"] for t in pf.trades if t["side"] == "buy")
        sell = sum(t["amount"] for t in pf.trades if t["side"] == "sell")
        fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
        step_fees += fee
        _append_monthly_funds(
            aum,
            {
                "date": str(rb["exec"].date()),
                "pre_nav": pre_nav,
                "post_nav": post_nav,
                "mret": (post_nav / prev_post - 1) * 100,
                "buy": buy,
                "sell": sell,
                "turnover": (buy + sell) / 2 / pre_nav * 100,
                "fee": fee,
                "div": pf.div_cash - div_before,
                "cash": pf.cash,
                "pos": post_nav - pf.cash,
            },
        )
        prev_post = post_nav
        bench_base = led.get("bench_base", 1.0)
        led["nav_history"].append(
            {
                "date": str(rb["exec"].date()),
                "nav": post_nav,
                "bench": bench_lv[rb["exec"]] / bench_base,
            }
        )
        led["trades"] += pf.trades
        pf.trades = []
        prev_exec = rb["exec"]
        print(
            f"  {rb['T'].date()} → {rb['exec'].date()}: 目标 {len(rb['target'])} 只, NAV {post_nav / 1e4:.2f}万"
        )
    led["last_signal"] = str(todo[-1]["T"].date())
    led["last_exec"] = str(todo[-1]["exec"].date())
    led["shares"] = pf.shares
    led["cash"] = pf.cash
    led["div_credited"] = pf.div_cash
    led["total_fees"] = round(led["total_fees"] + step_fees, 2)
    path.write_text(json.dumps(led, ensure_ascii=False, indent=1))
    prices = raw.loc[led["last_exec"]]
    _append_holdings_snapshot(aum, led["last_exec"], pf, prices)
    print(
        f"  → 最新 {led['last_exec']}, 持仓 {len(pf.shares)} 只, NAV {post_nav / 1e4:.2f}万"
    )


def mark(aum: float, slip: float | None = None):
    slip = slip if slip is not None else _cfg().costs.slip_default
    path = ledger_path(aum)
    if not path.exists():
        print(f"[{int(aum / 1e4)}万] 无账本")
        return
    led = json.loads(path.read_text())
    close, amount, tst, isst, ind, raw, rebs, bench, ret = _load_all_p3()
    pending = [
        r
        for r in rebs
        if r["T"] > pd.Timestamp(led["last_signal"]) and r["exec"] <= close.index[-1]
    ]
    if pending:
        print(
            f"  [警告] {int(aum / 1e4)}万 落后 {len(pending)} 个月调仓, 涨幅按旧持仓计; 先跑 step"
        )
    F = _factor_panel_cached(close)
    pf = PaperPortfolio(led["aum"], slip)
    pf.shares = {k: int(v) for k, v in led["shares"].items()}
    pf.cash = float(led["cash"])
    idx = close.index
    start = pd.Timestamp(led["last_exec"])
    if start not in idx:
        print(f"  [跳过] 执行日 {led['last_exec']} 不在行情内")
        return
    i0 = idx.get_loc(start)
    F_prev = F.shift(1).fillna(F.iloc[0])
    navs = []
    for i in range(i0, len(idx)):
        if i > i0:
            fn, fp = F.iloc[i], F_prev.iloc[i]
            prices_i = raw.iloc[i]
            for c in list(pf.shares.keys()):
                if fn[c] != fp[c]:
                    pf.corp_action_f(c, prices_i.get(c, np.nan), fp[c], fn[c])
        navs.append(pf.value(raw.iloc[i]))
    nav = pd.Series(navs, index=idx[i0:])
    df = pd.DataFrame(
        {
            "date": nav.index.strftime("%Y-%m-%d"),
            "nav": nav.round(2),
            "涨幅%": (nav.pct_change() * 100).round(4),
        }
    )
    out = Path(_cfg().p3.out_dir) / f"daily_nav_p3_aum{int(aum / 1e4)}w.csv"
    df.to_csv(out, index=False)
    cum = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
    print(
        f"  P3 {int(aum / 1e4)}万: 最新 {nav.index[-1].date()} NAV {nav.iloc[-1] / 1e4:.2f}万 | "
        f"昨日 {nav.iloc[-2] / 1e4:.2f}万 | 今日 {nav.pct_change().iloc[-1]:+.2%} | 建仓以来 {cum:+.2f}%"
    )


def report(aum: float):
    path = ledger_path(aum)
    if not path.exists():
        print(f"[{int(aum / 1e4)}万] 无账本")
        return
    led = json.loads(path.read_text())
    close, amount, tst, isst, ind, raw, rebs, bench, ret = _load_all_p3()
    prices = raw.loc[led["last_exec"]]
    nav_now = led["cash"] + sum(
        s * prices.get(c, np.nan)
        for c, s in led["shares"].items()
        if pd.notna(prices.get(c, np.nan))
    )
    h = led["nav_history"]
    years = len(h) / 12
    ann = (nav_now / h[0]["nav"]) ** (1 / years) - 1 if years > 0 else 0
    bench_now = h[-1]["bench"]
    ann_b = (bench_now / 1.0) ** (1 / years) - 1 if years > 0 else 0
    print(
        f"\n== P3 账本报告 {int(aum / 1e4)}万 == (起 {h[0]['date']} → 今 {led['last_exec']})"
    )
    print(
        f"  净值 {nav_now / 1e4:.1f}万 | 持仓 {len(led['shares'])} 只 | 现金 {led['cash'] / 1e4:.1f}万 "
        f"({led['cash'] / nav_now:.1%})"
    )
    print(f"  年化 {ann:.1%} | 全市场基准年化 {ann_b:.1%} | 超额 {ann - ann_b:+.2%}pp")
    print(
        f"  累计费用 {led['total_fees'] / 1e4:.2f}万 | 累计分红(税后) {led['div_credited'] / 1e4:.2f}万"
    )
    # 阻塞记录(涨停买不进/跌停卖不出)
    lb = led.get("last_blocked")
    if lb:
        for blk in lb if isinstance(lb, list) else [lb]:
            amt_b = sum(b["amount"] for b in blk["buy"])
            codes_b = ", ".join(b["code"] for b in blk["buy"][:6])
            if len(blk["buy"]) > 6:
                codes_b += f" 等 {len(blk['buy'])} 只"
            print(
                f"  阻塞({blk['date']}): 涨停买不进 {len(blk['buy'])} 只"
                f"(滞留 {amt_b / 1e4:.1f}万: {codes_b}) | 跌停卖不出 {len(blk['sell'])} 只"
            )
    # 近 6 次 NAV
    for i in range(max(0, len(h) - 6), len(h)):
        x = h[i]
        print(f"    {x['date']}: NAV {x['nav'] / 1e4:.1f}万 | 基准 {x['bench']:.3f}")
    # 月度资金变动(近 6 次调仓)
    mp = monthly_funds_path(aum)
    if mp.exists():
        mf = pd.read_csv(mp)
        print("  月度资金变动(近6次调仓, 单位: 万元):")
        for _, r in mf.tail(6).iterrows():
            m = r["月涨幅%"]
            m_s = f"{m:+.2f}%" if pd.notna(m) else "建仓"
            print(
                f"    {r['date']}: 买 {r['买入额'] / 1e4:.1f} / 卖 {r['卖出额'] / 1e4:.1f} "
                f"| 换手 {r['换手率%']:.1f}% | 费 {r['费用']:.0f}元 | 月涨 {m_s} "
                f"| 较本金 {r['较本金盈亏'] / 1e4:+.1f}万 | NAV {r['post_nav'] / 1e4:.1f}万"
            )


def main():
    ap = argparse.ArgumentParser(description="P3 模拟盘(8账户)")
    ap.add_argument("cmd", choices=["init", "step", "mark", "report"])
    ap.add_argument("--config", default=None)
    ap.add_argument("--aum", type=float, default=None)
    ap.add_argument("--slip", type=float, default=None)
    ap.add_argument("--slip-by-amount", action="store_true")
    args = ap.parse_args()
    load_config(args.config)
    aums = [args.aum] if args.aum else list(_cfg().p3.aum_list)
    for a in aums:
        t0 = time.time()
        if args.cmd == "init":
            init_ledger(a, args.slip, args.slip_by_amount)
        elif args.cmd == "step":
            step(a, args.slip, args.slip_by_amount)
        elif args.cmd == "mark":
            mark(a, args.slip)
        elif args.cmd == "report":
            report(a)
        print(
            f"    [{args.cmd} {int(a / 1e4)}万] 耗时 {time.time() - t0:.0f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
