#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""模拟盘程序 paper_trade —— 全市场 R5 真实费率/税/1手取整/分红全口径模拟。

严格按 docs/factor_round10_paper_sim_plan.md v1.0：
- 真实价格账: raw = qfq / foreAdjustFactor(前复权因子), 现金用真实价格收付
- 公司行为: 除权日现金分红(按10%红利税)入现金; 送转调整股数
- 费率: 佣金万1.5(单笔最低5元,双边) + 印花税万5(卖出) + 过户费万0.1(双边) + 滑点(默认0)
- 1手=100股整数倍买入, 卖出允许零股清仓; 现金无收益; 净值=现金+Σ股数×价(逐日盯市)
- 调仓: 每月向目标等权再平衡, |Δ|≥1手才交易; 停牌(tradestatus!=1)跳过

用法:
  python research/paper_trade.py replay --aum 3000000   # 历史回放(2013-2026, 真实费率)
  python research/paper_trade.py init --aum 3000000     # 当前建仓快照(真实价格)
  python research/paper_trade.py init --aum 100000      # 演示: 10万不可行性
选项: --slip 0.001 (滑点比例, 默认0)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import month_last_days, metrics
from research.reversal_factor import build_pool, ew_nav

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
R2 = ROOT / "data" / "round2"
START = "2013-06-01"
MIN_N = 50
MIN_IND = 5

# ---- 真实费率(2026-09 联网核实, 预注册固定) ----
COMM_RATE = 0.00015  # 万1.5
COMM_MIN = 5.0  # 单笔最低 5 元
STAMP_RATE = 0.0005  # 印花税 万5, 仅卖出
TRANSFER_RATE = 0.00001  # 过户费 万0.1, 双边
DIV_TAX = 0.10  # 红利税 10% (1个月-1年持仓口径, 保守)


def _load():
    d = pd.read_parquet(ROOT / "data" / "fundamental" / "full_daily.parquet")
    d["date"] = pd.to_datetime(d["date"])

    def piv(c):
        return d.pivot(index="date", columns="code", values=c).sort_index().loc[START:]

    close, amount, tst, isst = (
        piv("close"),
        piv("amount"),
        piv("tradestatus"),
        piv("isST"),
    )
    ind = pd.read_parquet(R2 / "industry_full.parquet").set_index("code")["industry"]
    ind = ind.reindex(close.columns).dropna()
    return close, amount, tst, isst, ind


def _load_corp(close: pd.DataFrame):
    """真实价格面板 + 复权因子面板。raw = qfq / foreAdjustFactor。
    缺失因子股票回退为 raw=qfq(当前日期正确; 历史日期仅缺 2.2%, 误差可忽略)。
    公司行为由 F 事件驱动: 因子变化日补回除权缺口(见 corp_action_f), 不依赖分红数据。"""
    fac = pd.read_parquet(R2 / "adjust_factor.parquet")
    fac["date"] = pd.to_datetime(fac["date"])
    idx = close.index
    f_series = {}
    for c, g in fac.groupby("code"):
        g = g.sort_values("date").set_index("date")["foreAdjustFactor"]
        g = g.reindex(idx).ffill().bfill().fillna(1.0)
        f_series[c] = g
    F = pd.DataFrame(f_series).reindex(columns=close.columns).fillna(1.0)
    raw = (close / F).ffill()  # 停牌日按最后价计值(价格延续), 与权重模型一致
    return raw, F


def r5_rebalances(close, amount, tst, isst, ind):
    """R5 信号: 行业内百分位(Amihud+中期动量), 前20%。返回 rebs+bench(同池等权)。"""
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    amihud = (
        ((close.pct_change().abs() / amount) * 1e6).rolling(21, min_periods=15).mean()
    )
    mom = close.shift(21) / close.shift(250) - 1.0
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
        keep = ind_s.value_counts()[ind_s.value_counts() >= MIN_IND].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < MIN_N:
            continue
        if k + 1 < len(sig_days):
            bench[exec_day] = set(codes)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = (pa + pm) / 2
        q = pd.qcut(sc.rank(method="first"), 5, labels=False)
        rebs.append({"T": T, "exec": exec_day, "target": set(codes[q == 4])})
    return rebs, bench, ret


def fees(amount: float, side: str, slip: float = 0.0) -> dict:
    comm = max(amount * COMM_RATE, COMM_MIN)
    stamp = amount * STAMP_RATE if side == "sell" else 0.0
    transfer = amount * TRANSFER_RATE
    return {"佣金": comm, "印花税": stamp, "过户费": transfer, "滑点": amount * slip}


class PaperPortfolio:
    def __init__(self, aum: float, slip: float = 0.0):
        self.aum0 = aum
        self.slip = slip
        self.shares: dict[str, int] = {}
        self.cash = aum
        self.trades: list[dict] = []
        self.div_cash = 0.0

    def value(self, prices: pd.Series) -> float:
        v = self.cash
        for c, s in self.shares.items():
            p = prices.get(c, np.nan)
            if pd.notna(p):
                v += s * p
        return v

    def _order(self, code: str, side: str, qty: int, price: float):
        if qty == 0 or pd.isna(price):
            return
        amt = qty * price
        f = fees(amt, side, self.slip)
        px = price * (1 - self.slip) if side == "sell" else price * (1 + self.slip)
        if side == "buy":
            need = amt * (1 + self.slip) + f["佣金"] + f["过户费"]
            if need > self.cash + 1e-6:
                qty = (
                    int((self.cash - COMM_MIN) / (price * (1 + self.slip)) // 100) * 100
                )
                if qty <= 0:
                    return
                amt, px = qty * price, price * (1 + self.slip)
                f = fees(amt, side, self.slip)
                need = amt * (1 + self.slip) + f["佣金"] + f["过户费"]
            self.cash -= need
            self.shares[code] = self.shares.get(code, 0) + qty
        else:
            self.cash += amt * (1 - self.slip) - f["佣金"] - f["印花税"] - f["过户费"]
            self.shares[code] = self.shares.get(code, 0) - qty
            if self.shares[code] <= 0:
                self.shares.pop(code, None)
        self.trades.append(
            {
                "code": code,
                "side": side,
                "qty": qty,
                "price": round(px, 3),
                "amount": round(amt, 2),
                **{k: round(v, 2) for k, v in f.items()},
            }
        )

    def corp_action_f(self, code: str, raw_price: float, f_prev: float, f_now: float):
        """复权因子事件日补回除权缺口(价值精确):
        现金 += 股数 × raw × (f_now/f_prev − 1); 现金分红按10%红利税保守计。
        现金/送转均价值等效, 不依赖分红数据完整性。"""
        if code in self.shares and f_prev > 0 and f_now != f_prev:
            s = self.shares[code]
            credit = s * raw_price * (f_now / f_prev - 1.0) * (1 - DIV_TAX)
            if credit > 0:
                self.cash += credit
                self.div_cash += credit

    def rebalance(self, target: set, prices: pd.Series, tradable: pd.Series):
        V = self.value(prices)
        n = len(target)
        if n == 0:
            return
        tgt_val = V / n
        for c in list(self.shares.keys()):
            if c not in target:
                if tradable.get(c, False):
                    self._order(c, "sell", self.shares[c], prices.get(c, np.nan))
            else:
                p = prices.get(c, np.nan)
                if pd.isna(p) or not tradable.get(c, False):
                    continue
                held = self.shares[c]
                tgt_sh = int(tgt_val / p / 100) * 100
                if held - tgt_sh >= 100:
                    self._order(c, "sell", held - tgt_sh, p)
        for c in target:
            p = prices.get(c, np.nan)
            if pd.isna(p) or not tradable.get(c, False):
                continue
            held = self.shares.get(c, 0)
            tgt_sh = int(tgt_val / p / 100) * 100
            if tgt_sh - held >= 100:
                self._order(c, "buy", tgt_sh - held, p)


def replay_w(aum: float, slip: float = 0.0, min_notional: float = 3000.0):
    """权重口径 + 精确费率(佣金5元最低/印花/过户按每笔计) 的历史回放。

    权重/调仓与已验证明细一致(ew_nav 口径, 15bp 模型 = +4.61pp 可复现);
    成本从"换手×15bp"换成每笔真实费率, 1手取整以 min_notional(约半手) 作无交易带近似。
    精确股数级回放见 replay()(需公司行为数据齐全)。
    """
    close, amount, tst, isst, ind = _load()
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]

    cols = ret.columns
    W = pd.DataFrame(0.0, index=ret.index, columns=cols)
    w = pd.Series(0.0, index=cols)
    execs = {r["exec"] for r in rebs}
    for dt in ret.index:
        if dt in execs:
            S = next(r["target"] for r in rebs if r["exec"] == dt)
            w = pd.Series(0.0, index=cols)
            if S:
                w[list(S)] = 1.0 / len(S)
        W.iloc[W.index.get_loc(dt)] = w
    dW = W.diff().fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * ret.fillna(0.0)).sum(axis=1)
    nav, navs, orders, tot_fee = 1.0, [], 0, 0.0
    for i, dt in enumerate(ret.index):
        nav *= 1 + gross.iloc[i]
        row = dW.iloc[i]
        if (row.abs() > 1e-12).any():
            cost_yuan, n_o = 0.0, 0
            nav_yuan = nav * aum
            for c, dw in row.items():
                nn = abs(dw) * nav_yuan  # 每笔订单名义金额(元)
                if nn < min_notional or nn < 1e-9:
                    continue
                side = "sell" if dw < 0 else "buy"
                f = fees(nn, side, slip)
                cost_yuan += f["佣金"] + f["印花税"] + f["过户费"] + f["滑点"]
                n_o += 1
            nav *= 1 - cost_yuan / nav_yuan  # 费用以占净值比例计入(复利口径)
            orders += n_o
            tot_fee += cost_yuan
        navs.append(nav)
    nav = pd.Series(navs, index=ret.index)
    m = metrics(nav)
    exc = m["年化"] - ann_bench
    years = len(nav) / 244
    print(f"\n== 历史回放·权重口径+精确费率 (AUM={aum / 1e4:.0f}万, 滑点{slip:.1%}) ==")
    print(
        f"  全口径超额: {exc:+.2%} | 策略年化 {m['年化']:.1%} | 同池等权基准 {ann_bench:.1%}"
    )
    print(f"  夏普 {m['夏普']:.2f} | 最大回撤 {m['最大回撤']:.1%}")
    print(
        f"  订单 {orders} 笔 | 总费用 {tot_fee / 1e4:.1f}万 = {tot_fee / aum / years:.2%}/年"
    )
    print("  (1手取整的现金拖累未含, 见建仓快照的实测资金利用率外推)")
    print(f"  vs 理想化 15bp口径+4.61pp → 费率税执行代价 {0.0461 - exc:+.2%}pp")
    return exc


def replay(aum: float, slip: float = 0.0):
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    # 守卫: share级回放需要完整复权因子(覆盖历史持仓股的价格调整)
    fac = pd.read_parquet(R2 / "adjust_factor.parquet")
    have = set(fac["code"].unique())
    miss = set(close.columns) - have
    if len(miss) > len(close.columns) * 0.05:
        raise SystemExit(
            f"share级回放: 复权因子未齐, {len(miss)} 只缺因子 "
            f"({len(miss) / len(close.columns):.0%}) → 请先跑 fetch_corporate_actions.py "
            f"或改用 replay_w(权重口径+精确费率)"
        )
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1

    pf = PaperPortfolio(aum, slip)
    idx = close.index
    F_prev = F.shift(1).fillna(F.iloc[0])
    navs, tot_fee = [], 0.0
    for i, dt in enumerate(idx):
        prices = raw.loc[dt]
        f_now = F.loc[dt]
        f_prev = F_prev.loc[dt]
        for c in list(pf.shares.keys()):
            if f_now[c] != f_prev[c]:
                pf.corp_action_f(c, prices.get(c, np.nan), f_prev[c], f_now[c])
        rb = next((r for r in rebs if r["exec"] == dt), None)
        if rb is not None:
            pf.rebalance(rb["target"], prices, trad.loc[dt])
        navs.append(pf.value(prices))
    nav = pd.Series(navs, index=idx) / aum  # 归一化到 1.0 起点(元→单位净值)
    tot_fee = sum(t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades)
    m = metrics(nav)
    exc = m["年化"] - ann_bench
    years = len(nav) / 244
    print(f"\n== 历史全口径回放 (AUM={aum / 1e4:.0f}万, 滑点{slip:.1%}) ==")
    print(
        f"  全口径超额: {exc:+.2%} | 策略年化 {m['年化']:.1%} | 同池等权基准 {ann_bench:.1%}"
    )
    print(
        f"  夏普 {m['夏普']:.2f} | 最大回撤 {m['最大回撤']:.1%} | 期末净值 {nav.iloc[-1]:.2f}"
    )
    print(
        f"  订单 {len(pf.trades)} 笔 | 总费用 {tot_fee / 1e4:.1f}万 = {tot_fee / aum / years:.2%}/年"
    )
    print(
        f"  累计分红(税后) {pf.div_cash / 1e4:.1f}万 | 换手参考 {nav_bench.index.size}日"
    )
    print(f"  vs 理想化 15bp口径+4.61pp → 真实执行代价 {0.0461 - exc:+.2%}pp")
    return exc


def init_portfolio(aum: float, slip: float = 0.0):
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs, _, _ = r5_rebalances(close, amount, tst, isst, ind)
    last = rebs[-1]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    pf = PaperPortfolio(aum, slip)
    prices = raw.loc[last["exec"]]
    pf.rebalance(last["target"], prices, trad.loc[last["exec"]])
    total_fee = sum(
        t["佣金"] + t["印花税"] + t["过户费"] + t["滑点"] for t in pf.trades
    )
    n_skip = len(last["target"]) - len(pf.shares)
    print(
        f"\n== 当前建仓快照 (信号 {last['T'].date()} → 执行 {last['exec'].date()}) =="
    )
    print(
        f"  AUM {aum / 1e4:.0f}万: 目标 {len(last['target'])} 只, 实际买入 {len(pf.shares)} 只"
        f" (跳过 {n_skip}: 停牌/涨停/1手不足), 现金 {pf.cash / 1e4:.1f}万 ({pf.cash / aum:.1%})"
    )
    print(
        f"  建仓订单 {len(pf.trades)} 笔, 总费用 {total_fee:.0f} 元"
        f" ({total_fee / aum:.2%} 的一次性成本)"
    )
    if aum < 200_000:
        print("  ⚠️ 10万级资金: 1手约束下多数标的一手都买不起 → 不可行(如预期)")
    df = pd.DataFrame(pf.trades).sort_values("amount", ascending=False)
    path = OUT / f"paper_init_aum{aum / 1e4:.0f}w.csv"
    df.to_csv(path, index=False)
    print(f"  建仓明细: {path.name}  | 头部5笔:\n{df.head(5).to_string()}")
    return pf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["replay", "replay_w", "init"])
    ap.add_argument("--aum", type=float, default=3_000_000)
    ap.add_argument("--slip", type=float, default=0.0)
    args = ap.parse_args()
    if args.mode == "replay":
        replay(args.aum, args.slip)
    elif args.mode == "replay_w":
        replay_w(args.aum, args.slip)
    else:
        init_portfolio(args.aum, args.slip)


if __name__ == "__main__":
    main()
