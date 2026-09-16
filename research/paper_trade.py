#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""模拟盘程序 paper_trade —— 全市场 R5 真实费率/税/1手取整/分红全口径模拟。

严格按 docs/factor_round10_paper_sim_plan.md v1.0：
- 真实价格账: raw = qfq / foreAdjustFactor(前复权因子), 现金用真实价格收付
- 公司行为: 除权日现金分红(按10%红利税)入现金; 送转调整股数
- 费率: 佣金万1.5(单笔最低5元,双边) + 印花税万5(卖出) + 过户费万0.1(双边) + 滑点(默认15bp, Round33)
- 1手=100股整数倍买入, 卖出允许零股清仓; 现金无收益; 净值=现金+Σ股数×价(逐日盯市)
- 调仓: 每月向目标等权再平衡, |Δ|≥1手才交易; 停牌(tradestatus!=1)跳过

用法:
  python research/paper_trade.py replay --aum 3000000   # 历史回放(2013-2026, 真实费率)
  python research/paper_trade.py init --aum 3000000     # 当前建仓快照(真实价格)
  python research/paper_trade.py init --aum 100000      # 演示: 10万不可行性
选项: --slip 0.001 (滑点比例, 默认0.0015=15bp, Round33 与基准/账本口径统一; 0=纯因子口径)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.config import get_config  # noqa: E402
from research.data_io import delist_map, load_full_daily  # noqa: E402
from research.dividend_factor import month_last_days, metrics  # noqa: E402
from research.reversal_factor import build_pool, ew_nav  # noqa: E402


# 注：paper_trade 不再定义模块级配置常量。所有配置值在函数内通过 get_config() 读取
# （方案二：函数内惰性读取，main() 里 load_config(args.config) 后生效）。
# 外部脚本如需要路径/账户等，请从 research.config 读取，不再 import paper_trade 的常量。
ROOT = Path(__file__).resolve().parent.parent


def _cfg():
    """当前进程配置单例（main() 里 load_config 后生效；被 import 时用默认）。"""
    return get_config()


def _load():
    cfg = _cfg()
    d = load_full_daily()
    d["date"] = pd.to_datetime(d["date"])

    def piv(c):
        return (
            d.pivot(index="date", columns="code", values=c)
            .sort_index()
            .loc[cfg.strategy.start :]
        )

    close, amount, tst, isst = (
        piv("close"),
        piv("amount"),
        piv("tradestatus"),
        piv("isST"),
    )
    ind = pd.read_parquet(cfg.paths.round2 + "/industry_full.parquet").set_index(
        "code"
    )["industry"]
    ind = ind.reindex(close.columns).dropna()
    return close, amount, tst, isst, ind


def _load_corp(close: pd.DataFrame):
    """真实价格面板 + 复权因子面板。raw = qfq / foreAdjustFactor。
    缺失因子股票回退为 raw=qfq(当前日期正确; 历史日期仅缺 2.2%, 误差可忽略)。
    公司行为由 F 事件驱动: 因子变化日补回除权缺口(见 corp_action_f), 不依赖分红数据。"""
    cfg = _cfg()
    fac = pd.read_parquet(cfg.paths.round2 + "/adjust_factor.parquet")
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
    """R5 信号: 行业内百分位(Amihud+中期动量), 前 1/quantile。返回 rebs+bench(同池等权)。"""
    cfg = _cfg()
    min_ind = cfg.strategy.min_ind
    min_n = cfg.strategy.min_n
    amihud_w = cfg.strategy.amihud_w
    r5 = cfg.strategy.r5
    ret = close.pct_change()
    pool = build_pool(close, tst, isst)
    amihud = (
        ((close.pct_change().abs() / amount) * r5.amihud_scale)
        .rolling(r5.amihud_lookback, min_periods=r5.amihud_min_periods)
        .mean()
    )
    mom = close.shift(r5.mom_short) / close.shift(r5.mom_long) - 1.0
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
        keep = ind_s.value_counts()[ind_s.value_counts() >= min_ind].index
        codes = common[ind_s.isin(keep)]
        if len(codes) < min_n:
            continue
        if k + 1 < len(sig_days):
            bench[exec_day] = set(codes)
        pa = a.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        pm = m.reindex(codes).groupby(ind_s[codes]).rank(pct=True)
        sc = amihud_w * pa + (1 - amihud_w) * pm  # Round 29: Amihud 0.85 : 动量 0.15
        q = pd.qcut(sc.rank(method="first"), r5.quantile, labels=False)
        rebs.append(
            {"T": T, "exec": exec_day, "target": set(codes[q == r5.quantile - 1])}
        )
    return rebs, bench, ret


def fees(amount: float, side: str, slip: float = 0.0) -> dict:
    cfg = _cfg()
    comm = max(amount * cfg.costs.comm_rate, cfg.costs.comm_min)
    stamp = amount * cfg.costs.stamp_rate if side == "sell" else 0.0
    transfer = amount * cfg.costs.transfer_rate
    return {"佣金": comm, "印花税": stamp, "过户费": transfer, "滑点": amount * slip}


def slip_for_amount(amount_val: float) -> float:
    """流动性依赖滑点（Round 35 口径 B）：按成交额分档，金额越大滑点越低。

    分档表来自 config costs.slip_bounds/slip_tiers（全样本 amount 分位数, 冻结）：
    <Q20→40bp, Q20-40→25bp, Q40-60→15bp, Q60-80→10bp, ≥Q80→5bp。
    """
    cfg = _cfg()
    bounds = cfg.costs.slip_bounds
    tiers = cfg.costs.slip_tiers
    for b, t in zip(bounds, tiers):
        if amount_val < b:
            return float(t)
    return float(tiers[-1])


def amount_slip_series(amount_row: pd.Series) -> pd.Series:
    """exec 日成交额行 → 每只股票的差异化滑点 Series（口径 B）。"""
    return amount_row.map(slip_for_amount)


class PaperPortfolio:
    def __init__(self, aum: float, slip: float = 0.0):
        self.aum0 = aum
        self.slip = slip
        self.slip_series: pd.Series | None = (
            None  # Round35 B: 按股滑点(有则优先于 self.slip)
        )
        self.shares: dict[str, int] = {}
        self.cash = aum
        self.trades: list[dict] = []
        self.div_cash = 0.0
        self.blocked_buys: list[
            tuple[str, float]
        ] = []  # Round24: (code, 想买资金) 涨停买不进
        self.blocked_sells: list[
            tuple[str, float]
        ] = []  # Round24: (code, 想卖市值) 跌停卖不出

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
        comm_min = _cfg().costs.comm_min
        # Round35 B: 有 slip_series 时按股差异化滑点, 否则用全局 self.slip
        slip = (
            float(self.slip_series.get(code, self.slip))
            if self.slip_series is not None
            else self.slip
        )
        amt = qty * price
        f = fees(amt, side, slip)
        px = price * (1 - slip) if side == "sell" else price * (1 + slip)
        if side == "buy":
            need = amt * (1 + slip) + f["佣金"] + f["过户费"]
            if need > self.cash + 1e-6:
                qty = int((self.cash - comm_min) / (price * (1 + slip)) // 100) * 100
                if qty <= 0:
                    return
                amt, px = qty * price, price * (1 + slip)
                f = fees(amt, side, slip)
                need = amt * (1 + slip) + f["佣金"] + f["过户费"]
            self.cash -= need
            self.shares[code] = self.shares.get(code, 0) + qty
        else:
            self.cash += amt * (1 - slip) - f["佣金"] - f["印花税"] - f["过户费"]
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
            div_tax = _cfg().costs.div_tax
            credit = s * raw_price * (f_now / f_prev - 1.0) * (1 - div_tax)
            if credit > 0:
                self.cash += credit
                self.div_cash += credit

    def rebalance(
        self, target: set, prices: pd.Series, tradable: pd.Series, ret_exec=None
    ):
        """调仓撮合。ret_exec=None → 理想化(无阻塞, 向后兼容);
        传入执行日涨幅 Series → S3-跟随 阻塞: 涨停(≥+LIMIT_THR)买不进/跌停(≤-LIMIT_THR)卖不出,
        未成交递延到下月调仓再平衡(不强制补买)。Round 24 生产真实口径。
        """
        limit_thr = _cfg().strategy.limit_thr
        V = self.value(prices)
        n = len(target)
        if n == 0:
            return
        self.blocked_buys = []
        self.blocked_sells = []
        tgt_val = V / n
        for c in list(self.shares.keys()):
            if c not in target:
                if tradable.get(c, False):
                    if ret_exec is not None and ret_exec.get(c, 0.0) <= -limit_thr:
                        self.blocked_sells.append(
                            (c, self.shares[c] * prices.get(c, np.nan))
                        )  # 跌停卖不出, 记录想卖市值
                        continue
                    self._order(c, "sell", self.shares[c], prices.get(c, np.nan))
            else:
                p = prices.get(c, np.nan)
                if pd.isna(p) or not tradable.get(c, False):
                    continue
                held = self.shares[c]
                tgt_sh = int(tgt_val / p / 100) * 100
                if held - tgt_sh >= 100:
                    if ret_exec is not None and ret_exec.get(c, 0.0) <= -limit_thr:
                        self.blocked_sells.append(
                            (c, (held - tgt_sh) * p)
                        )  # 跌停卖不出
                        continue
                    self._order(c, "sell", held - tgt_sh, p)
        for c in sorted(
            target
        ):  # 排序迭代: set哈希序随机会致现金约束下买入子集逐次漂移(确定性修复)
            p = prices.get(c, np.nan)
            if pd.isna(p) or not tradable.get(c, False):
                continue
            if ret_exec is not None and ret_exec.get(c, 0.0) >= limit_thr:
                held = self.shares.get(c, 0)
                tgt_sh = int(tgt_val / p / 100) * 100
                if tgt_sh - held >= 100:
                    self.blocked_buys.append(
                        (c, (tgt_sh - held) * p)
                    )  # 涨停买不进, 记录想买资金
                continue
            held = self.shares.get(c, 0)
            tgt_sh = int(tgt_val / p / 100) * 100
            if tgt_sh - held >= 100:
                self._order(c, "buy", tgt_sh - held, p)


def replay_w(
    aum: float,
    slip: float = 0.0,
    min_notional: float = 3000.0,
    slip_by_amount: bool = False,
):
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
                sl = slip_for_amount(amount.loc[dt, c]) if slip_by_amount else slip
                f = fees(nn, side, sl)
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


def force_liquidate_delisted(
    pf: PaperPortfolio,
    delist: dict[str, pd.Timestamp],
    dt: pd.Timestamp,
    raw: pd.DataFrame,
):
    """Round 17 引擎语义A: 持仓股到退市日(outDate)强制以最后可得价清仓。

    退市股 raw 经 ffill 后末价为最后交易价; 完全无价可依时归零(极端兜底)。
    卖出走 _order(含费用), 与真实退市整理期卖出口径一致。
    """
    for c in list(pf.shares.keys()):
        dl = delist.get(c)
        if dl is None or dt < dl:
            continue
        px = raw.loc[dt, c]
        if pd.isna(px):
            s = raw.loc[:dt, c].dropna()
            px = float(s.iloc[-1]) if len(s) else np.nan
        if pd.notna(px):
            pf._order(c, "sell", pf.shares[c], float(px))
        else:
            pf.shares.pop(c, None)  # 无价可依: 该持仓归零


def replay(aum: float, slip: float = 0.0, slip_by_amount: bool = False):
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs, bench, ret = r5_rebalances(close, amount, tst, isst, ind)
    nav_bench, _ = ew_nav(ret, bench, 15e-4)
    ann_bench = metrics(nav_bench)["年化"]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    # 守卫: share级回放需要完整复权因子(覆盖历史持仓股的价格调整)。
    # Round17: 退市股缺因子属常见(老退市股常无数据), 允许 qfq 回退(F=1.0);
    # 在市股缺因子 >5% 仍硬拦(真问题)。
    fac = pd.read_parquet(_cfg().paths.round2 + "/adjust_factor.parquet")
    have = set(fac["code"].unique())
    miss = set(close.columns) - have
    dl_keys = set(delist_map().keys())
    miss_in_mkt = miss - dl_keys
    miss_delisted = miss & dl_keys
    if len(miss_in_mkt) > len(close.columns) * 0.05:
        raise SystemExit(
            f"share级回放: 在市股复权因子未齐, {len(miss_in_mkt)} 只缺因子 "
            f"({len(miss_in_mkt) / len(close.columns):.0%}) → 请先跑 fetch_corporate_actions.py"
        )
    if miss_delisted:
        print(f"  [Round17] {len(miss_delisted)} 只退市股缺因子, 用 qfq 回退(F=1.0)")

    pf = PaperPortfolio(aum, slip)
    delist = delist_map()  # Round 17: 退市股清单(仅 type=1, 主板)
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
        force_liquidate_delisted(pf, delist, dt, raw)  # Round 17 退市强制清仓
        rb = next((r for r in rebs if r["exec"] == dt), None)
        if rb is not None:
            pf.slip_series = (
                amount_slip_series(amount.loc[dt]) if slip_by_amount else None
            )
            pf.rebalance(rb["target"], prices, trad.loc[dt], ret.loc[dt])
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


def init_portfolio(aum: float, slip: float = 0.0, slip_by_amount: bool = False):
    close, amount, tst, isst, ind = _load()
    raw, F = _load_corp(close)
    rebs, _, ret = r5_rebalances(close, amount, tst, isst, ind)
    last = rebs[-1]
    trad = tst.apply(pd.to_numeric, errors="coerce") == 1
    pf = PaperPortfolio(aum, slip)
    if slip_by_amount:  # Round35 B
        pf.slip_series = amount_slip_series(amount.loc[last["exec"]])
    prices = raw.loc[last["exec"]]
    pf.rebalance(last["target"], prices, trad.loc[last["exec"]], ret.loc[last["exec"]])
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
    path = Path(_cfg().paths.output) / f"paper_init_aum{aum / 1e4:.0f}w.csv"
    df.to_csv(path, index=False)
    print(f"  建仓明细: {path.name}  | 头部5笔:\n{df.head(5).to_string()}")
    return pf


def main():
    from research.config import add_config_arg, get_config, load_config  # noqa: PLC0415

    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["replay", "replay_w", "init"])
    ap.add_argument("--aum", type=float, default=3_000_000)
    ap.add_argument(
        "--slip",
        type=float,
        default=None,
        help="滑点比例(默认取配置 costs.slip_default=15bp; 0=纯因子口径)",
    )
    ap.add_argument(
        "--slip-by-amount",
        action="store_true",
        help="Round35 B: 按执行日成交额分档差异化滑点(流动性依赖, 覆盖 --slip)",
    )
    add_config_arg(ap)
    args = ap.parse_args()
    load_config(
        args.config
    )  # 方案二: 入口处加载配置(含 --config), 之后函数内 get_config() 生效
    slip = args.slip if args.slip is not None else get_config().costs.slip_default
    if args.mode == "replay":
        replay(args.aum, slip, slip_by_amount=args.slip_by_amount)
    elif args.mode == "replay_w":
        replay_w(args.aum, slip, slip_by_amount=args.slip_by_amount)
    else:
        init_portfolio(args.aum, slip, slip_by_amount=args.slip_by_amount)


if __name__ == "__main__":
    main()
