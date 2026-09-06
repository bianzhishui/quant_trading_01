#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""模拟盘长期运行系统 —— 300万/600万两账户, 实时数据月度推进。

账本驱动: output/ledger_aum{XX}w.json 持久化 {持仓股数, 现金, 净值历史, 基准, 费用};
每月新数据到手后运行 step, 自动补跑错过的所有调仓(长期执行核心)。

用法:
  python research/paper_live.py init --aum 3000000   # 建账(当前信号起)
  python research/paper_live.py init --aum 6000000
  python research/paper_live.py step                 # 推进全部账本到最新数据
  python research/paper_live.py step --aum 3000000   # 只推进单个
  python research/paper_live.py report               # 全部账本报告
数据: 行情用 data/fundamental/full_daily.parquet(先跑 fetch_full_market.py 更新);
公司行为增量用 baostock 实时查询(持仓股), 缓存 data/round2/adjust_factor_live.parquet。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.paper_trade import (COMM_MIN, DIV_TAX, OUT, R2, ROOT, PaperPortfolio,
                                  _load, _load_corp, fees, metrics, r5_rebalances)
from research.reversal_factor import ew_nav

LIVE_FAC = R2 / "adjust_factor_live.parquet"


def ledger_path(aum: float) -> Path:
    return OUT / f"ledger_aum{int(aum / 1e4)}w.json"


def monthly_funds_path(aum: float) -> Path:
    return OUT / f"monthly_funds_aum{int(aum / 1e4)}w.csv"


FUNDS_COLS = ["date", "pre_nav", "post_nav", "月涨幅%", "买入额", "卖出额", "换手率%",
              "费用", "分红入账", "期末现金", "期末持仓", "较本金盈亏"]


def _append_monthly_funds(aum: float, row: dict):
    """追加一行月度调仓资金变动到 monthly_funds_aum{XX}w.csv (金额单位: 元)。
    row 键: date, pre_nav, post_nav, mret, buy, sell, turnover, fee, div, cash, pos"""
    r = [row["date"], round(row["pre_nav"], 2), round(row["post_nav"], 2),
         round(row["mret"], 4) if row["mret"] is not None else "",
         round(row["buy"], 2), round(row["sell"], 2),
         round(row["turnover"], 3) if row["turnover"] is not None else "",
         round(row["fee"], 2), round(row["div"], 2), round(row["cash"], 2),
         round(row["pos"], 2), round(row["post_nav"] - aum, 2)]
    p = monthly_funds_path(aum)
    if not p.exists():
        p.write_text(",".join(FUNDS_COLS) + "\n")
    with p.open("a") as f:
        f.write(",".join(str(x) for x in r) + "\n")


def _seed_build_row(aum: float):
    """账本已有而月度资金 CSV 缺失时, 从账本建仓记录补首行(建仓日)。"""
    p = monthly_funds_path(aum)
    if p.exists():
        return
    path = ledger_path(aum)
    if not path.exists():
        return
    led = json.loads(path.read_text())
    h0 = led["nav_history"][0]
    if len(led["nav_history"]) == 1:          # 未 step 过: trades 全是建仓单
        buy = sum(t["amount"] for t in led["trades"] if t["side"] == "buy")
        sell = sum(t["amount"] for t in led["trades"] if t["side"] == "sell")
    else:                                     # 已 step: 无法拆分, 用净值差额近似
        buy, sell = h0["nav"], 0.0
    _append_monthly_funds(aum, {"date": h0["date"], "pre_nav": led["aum"],
                                "post_nav": h0["nav"], "mret": None, "buy": buy,
                                "sell": sell, "turnover": buy / led["aum"] * 100,
                                "fee": led["total_fees"], "div": 0.0,
                                "cash": led["cash"], "pos": h0["nav"] - led["cash"]})


def _live_factors(held: set, since: str):
    """增量查询持仓股的复权因子事件(自 since 起), 并入 live 缓存。baostock 限流弹性。"""
    import baostock as bs
    prev = pd.read_parquet(LIVE_FAC) if LIVE_FAC.exists() else None
    have = set(prev["code"]) if prev is not None else set()
    todo = [c for c in sorted(held) if c not in have]
    if not todo:
        return
    lg = bs.login()
    buf, streak = [], 0
    for c in todo:
        got = False
        for _ in range(3):
            try:
                rs = bs.query_adjust_factor(code=c, start_date=since, end_date="2026-12-31")
                while rs.error_code == "0" and rs.next():
                    r = rs.get_row_data()
                    buf.append({"code": r[0], "date": r[1], "foreAdjustFactor": float(r[2])})
                    got = True
                break
            except Exception:
                time.sleep(2.0)
        streak = streak + 1 if not got else 0
        if streak >= 50:
            print(f"  [live因子] 疑似限流, 休眠60s", flush=True)
            bs.logout(); time.sleep(60); lg = bs.login(); streak = 0
        time.sleep(0.1)
    bs.logout()
    if buf:
        new = pd.DataFrame(buf)
        big = pd.concat([prev, new], ignore_index=True).drop_duplicates() if prev is not None \
            else new
        big.to_parquet(LIVE_FAC)
        print(f"  [live因子] 新增 {len(buf)} 条({len(todo)} 只持仓)", flush=True)


def _factor_panel(close: pd.DataFrame):
    """静态+live 合并的因子面板。"""
    fac = pd.read_parquet(R2 / "adjust_factor.parquet")
    if LIVE_FAC.exists():
        fac = pd.concat([fac, pd.read_parquet(LIVE_FAC)], ignore_index=True)
    fac["date"] = pd.to_datetime(fac["date"])
    idx = close.index
    f_series = {}
    for c, g in fac.groupby("code"):
        g = g.sort_values("date").set_index("date")["foreAdjustFactor"]
        f_series[c] = g.reindex(idx).ffill().bfill().fillna(1.0)
    return pd.DataFrame(f_series).reindex(columns=close.columns).fillna(1.0)


def _bench_levels(rebs, bench, ret):
    """同池等权基准(15bp, 与回测可比)在每次执行日的净值水平。"""
    nav_b, _ = ew_nav(ret, bench, 15e-4)
    return {r["exec"]: float(nav_b.loc[r["exec"]]) for r in rebs}


def _apply_corp_period(pf: PaperPortfolio, F: pd.DataFrame, raw: pd.DataFrame,
                       d_start, d_end):
    """推进期间(d_start, d_end] 的公司行为: 因子事件补回除权缺口(价值精确)。"""
    idx = raw.index
    if d_start not in idx or d_end not in idx:
        return
    i0, i1 = idx.get_loc(d_start), idx.get_loc(d_end)
    F_prev = F.shift(1)
    for i in range(i0 + 1, i1 + 1):
        dt = idx[i]
        fn, fp = F.iloc[i], F_prev.iloc[i]
        prices = raw.iloc[i]
        for c in list(pf.shares.keys()):
            if fn[c] != fp[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), fp[c], fn[c])


def init_ledger(aum: float):
    close, amount, tst, isst, ind = _load()
    raw, _ = _load_corp(close)
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    last = rebs[-1]
    F = _factor_panel(close)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    pf = PaperPortfolio(aum)
    prices = raw.loc[last["exec"]]
    pf.rebalance(last["target"], prices, trad.loc[last["exec"]])
    nav = pf.value(prices)
    bench_lv = _bench_levels(rebs, bench, ret)
    # 基准在建账日归一到 1.0: 模拟盘超额 = 策略自建账起收益 − 同池等权自建账起收益
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
        "total_fees": round(sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"]
                                for t in pf.trades), 2),
    }
    path = ledger_path(aum)
    path.write_text(json.dumps(led, ensure_ascii=False, indent=1))
    _seed_build_row(aum)
    print(f"\n== 建账完成 {int(aum/1e4)}万 == 信号 {led['last_signal']} → 执行 {led['last_exec']}"
          f" | 持仓 {len(pf.shares)} 只 | 现金 {pf.cash/1e4:.1f}万"
          f" ({pf.cash/aum:.1%}) | NAV {nav/1e4:.1f}万")
    print(f"  建仓费用 {led['total_fees']:.0f} 元 | 账本 {path.name}")


def step(aum: float):
    path = ledger_path(aum)
    if not path.exists():
        raise SystemExit(f"账本不存在: {path.name} → 先跑 init")
    led = json.loads(path.read_text())
    close, amount, tst, isst, ind = _load()
    raw, _ = _load_corp(close)
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    bench_lv = _bench_levels(rebs, bench, ret)

    todo = [r for r in rebs if r["T"] > pd.Timestamp(led["last_signal"])
            and r["exec"] <= close.index[-1]]
    if not todo:
        print(f"\n[{int(aum/1e4)}万] 已是最新(信号 {led['last_signal']}), 无待处理调仓")
        return
    # 实时公司行为: 仅当调仓窗口超出静态因子抓取截止日(2026-09-03)才查 baostock。
    # 静态抓取 end_date=2026-09-03, 覆盖当前全部数据; 新数据超过该日后需重抓或增量查询。
    STATIC_FAC_END = pd.Timestamp("2026-09-03")
    need_live = any(r["exec"] > STATIC_FAC_END for r in todo)
    if need_live:
        try:
            _live_factors(set(led["shares"]) | {c for r in todo for c in r["target"]},
                          led["last_exec"])
        except Exception as e:
            print(f"  [live因子] 查询失败({e}), 用静态因子继续——"
                  f"窗口内新除权事件将缺失, 建议尽快重跑", flush=True)
    F = _factor_panel(close)
    pf = PaperPortfolio(led["aum"])
    pf.shares = {k: int(v) for k, v in led["shares"].items()}
    pf.cash = float(led["cash"])
    pf.div_cash = float(led.get("div_credited", 0))
    pf.trades = []

    print(f"\n== 推进 {int(aum/1e4)}万 账本 (待处理 {len(todo)} 个月) ==")
    prev_exec = pd.Timestamp(led["last_exec"])
    step_fees = 0.0
    _seed_build_row(aum)
    prev_post = led["nav_history"][-1]["nav"]
    for rb in todo:
        _apply_corp_period(pf, F, raw, prev_exec, rb["exec"])
        pre_nav = pf.value(raw.loc[rb["exec"]])
        div_before = pf.div_cash
        pf.rebalance(rb["target"], raw.loc[rb["exec"]], trad.loc[rb["exec"]])
        post_nav = pf.value(raw.loc[rb["exec"]])
        buy = sum(t["amount"] for t in pf.trades if t["side"] == "buy")
        sell = sum(t["amount"] for t in pf.trades if t["side"] == "sell")
        fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
        step_fees += fee
        _append_monthly_funds(aum, {"date": str(rb["exec"].date()), "pre_nav": pre_nav,
                                    "post_nav": post_nav,
                                    "mret": (post_nav / prev_post - 1) * 100,
                                    "buy": buy, "sell": sell,
                                    "turnover": (buy + sell) / 2 / pre_nav * 100,
                                    "fee": fee, "div": pf.div_cash - div_before,
                                    "cash": pf.cash, "pos": post_nav - pf.cash})
        prev_post = post_nav
        nav = post_nav
        bench_base = led.get("bench_base", 1.0)
        led["nav_history"].append({"date": str(rb["exec"].date()), "nav": nav,
                                   "bench": bench_lv[rb["exec"]] / bench_base})
        led["trades"] += pf.trades
        pf.trades = []
        print(f"  {rb['T'].date()} → {rb['exec'].date()}: 目标 {len(rb['target'])} 只, "
              f"买 {buy/1e4:.1f}万 / 卖 {sell/1e4:.1f}万, 费 {fee:.0f}元, "
              f"月涨 {((post_nav/prev_post)-1)*100:+.2f}%, NAV {nav/1e4:.1f}万")
        prev_exec = rb["exec"]
    led["last_signal"] = str(todo[-1]["T"].date())
    led["last_exec"] = str(todo[-1]["exec"].date())
    led["shares"] = pf.shares
    led["cash"] = pf.cash
    led["div_credited"] = pf.div_cash
    led["total_fees"] = round(led["total_fees"] + step_fees, 2)
    path.write_text(json.dumps(led, ensure_ascii=False, indent=1))
    print(f"  本批费用 {step_fees:.0f} 元 | 账本已更新: {path.name}")


def report(aum: float):
    path = ledger_path(aum)
    if not path.exists():
        print(f"[{int(aum/1e4)}万] 无账本"); return
    led = json.loads(path.read_text())
    close, amount, tst, isst, ind = _load()
    raw, _ = _load_corp(close)
    prices = raw.loc[led["last_exec"]]
    nav_now = led["cash"] + sum(s * prices.get(c, np.nan) for c, s in
                                led["shares"].items() if pd.notna(prices.get(c, np.nan)))
    h = led["nav_history"]
    nav0, bench0 = h[0]["nav"], h[0]["bench"]   # bench 已归一到 1.0(建账日)
    years = len(h) / 12
    ann = (nav_now / nav0) ** (1 / years) - 1 if years > 0 else 0
    bench_now = h[-1]["bench"]
    ann_b = (bench_now / bench0) ** (1 / years) - 1 if years > 0 else 0
    print(f"\n== 账本报告 {int(aum/1e4)}万 == (起 {h[0]['date']} → 今 {led['last_exec']})")
    print(f"  净值 {nav_now/1e4:.1f}万 | 持仓 {len(led['shares'])} 只 | 现金 {led['cash']/1e4:.1f}万")
    print(f"  年化 {ann:.1%} | 同池等权基准年化 {ann_b:.1%} | 超额 {ann-ann_b:+.2%}pp")
    print(f"  累计费用 {led['total_fees']/1e4:.1f}万 | 累计分红(税后) {led['div_credited']/1e4:.1f}万")
    for i in range(max(0, len(h) - 6), len(h)):
        x = h[i]
        print(f"    {x['date']}: NAV {x['nav']/1e4:.1f}万 | 基准 {x['bench']:.3f}")
    mp = monthly_funds_path(aum)
    if mp.exists():
        mf = pd.read_csv(mp)
        print("  月度资金变动(近6次调仓, 单位: 万元):")
        tail = mf.tail(6)
        for _, r in tail.iterrows():
            m = r["月涨幅%"]
            m_s = f"{m:+.2f}%" if pd.notna(m) else "建仓"
            print(f"    {r['date']}: 买 {r['买入额']/1e4:.1f} / 卖 {r['卖出额']/1e4:.1f} "
                  f"| 换手 {r['换手率%']:.1f}% | 费 {r['费用']:.0f}元 | 月涨 {m_s} "
                  f"| 较本金 {r['较本金盈亏']/1e4:+.1f}万 | NAV {r['post_nav']/1e4:.1f}万")


def mark(aum: float):
    """每日涨幅: 当天收盘 NAV / 前一天收盘 NAV - 1 (逐日盯市, 含分红入账)。

    从账本 last_exec 起逐日: 现金 + Σ股数×收盘价(停牌按最后价); 因子事件补除权缺口。
    输出 daily_nav_aum{XX}w.csv (date, nav, 涨幅%) 并打印最新/昨日/累计涨幅。
    """
    path = ledger_path(aum)
    if not path.exists():
        print(f"[{int(aum/1e4)}万] 无账本"); return
    led = json.loads(path.read_text())
    close, amount, tst, isst, ind = _load()
    raw, _ = _load_corp(close)
    rebs, _, _ = r5_rebalances(close, amount, tst, isst, ind)
    pending = [r for r in rebs if r["T"] > pd.Timestamp(led["last_signal"])
               and r["exec"] <= close.index[-1]]
    if pending:
        print(f"  [警告] {int(aum/1e4)}万 账本落后 {len(pending)} 个月调仓, 涨幅按旧持仓计; 请先跑 step")
    F = _factor_panel(close)
    pf = PaperPortfolio(led["aum"])
    pf.shares = {k: int(v) for k, v in led["shares"].items()}
    pf.cash = float(led["cash"])
    idx = close.index
    start = pd.Timestamp(led["last_exec"])
    if start not in idx:
        print(f"  [跳过] 执行日 {led['last_exec']} 不在行情内"); return
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
    ret = nav.pct_change() * 100
    df = pd.DataFrame({"date": nav.index.strftime("%Y-%m-%d"), "nav": nav.round(2),
                       "涨幅%": ret.round(4)})
    out = OUT / f"daily_nav_aum{int(aum/1e4)}w.csv"
    df.to_csv(out, index=False)
    cum = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
    print(f"\n== 每日涨幅 {int(aum/1e4)}万 == (起 {nav.index[0].date()} → 今 {nav.index[-1].date()})")
    print(f"  最新收盘 NAV {nav.iloc[-1]/1e4:.2f}万 | 当日涨幅 {ret.iloc[-1]:+.2f}%"
          f" | 昨日涨幅 {ret.iloc[-2]:+.2f}% | 累计 {cum:+.2f}%")
    print(f"  文件: {out.name}")
    print(df.tail(3).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["init", "step", "report", "mark"])
    ap.add_argument("--aum", type=float, default=0.0)
    args = ap.parse_args()
    aums = [args.aum] if args.aum > 0 else [600_000, 1_000_000, 3_000_000, 6_000_000]
    for a in aums:
        if args.mode == "init":
            init_ledger(a)
        elif args.mode == "step":
            step(a)
        elif args.mode == "mark":
            mark(a)
        else:
            report(a)


if __name__ == "__main__":
    main()
