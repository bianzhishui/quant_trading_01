#!/usr/bin/env .venv/bin/python
# -*- coding: utf-8 -*-
"""轻量事件式回测引擎，针对 A 股规则做了这些事：
1. 信号延迟执行：T 日收盘算出的目标权重 -> T+1 开盘价撮合（杜绝未来函数）；
2. 交易成本：佣金 + 最低佣金 + 卖出印花税 + 过户费 + 滑点；
3. T+1 约束：每天先处理卖出、后处理买入，当日新买的股份天然无法当日卖出；
4. 涨跌停检查：开盘价较昨收触及 ±limit% 视为无法成交并计数；
5. 调仓死区：目标仓位与实际仓位差异小于阈值时不交易，避免整手取整带来的
   每日微调换手；买入 sizing 会为滑点与费用预留现金，保证能足额成交。

引擎为学习用途做了合理简化（单标的、现金撮合、不支持融资融券）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costs import (
    COMMISSION_RATE, INIT_CASH, LOT_SIZE,
    SLIPPAGE, STAMP_TAX_RATE, TRANSFER_FEE_RATE,
)

_BUY_FEE_RATE = COMMISSION_RATE + TRANSFER_FEE_RATE          # 买入按成交额计的费率


@dataclass
class BTResult:
    equity: pd.Series            # 每日总资产
    trades: pd.DataFrame         # 成交记录
    weights: pd.Series           # 实际仓位占资产比例
    stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats
        lines = [
            f"回测区间          : {self.equity.index[0]:%Y-%m-%d} ~ "
            f"{self.equity.index[-1]:%Y-%m-%d}  ({len(self.equity)} 个交易日)",
            f"初始资金 / 期末资产: {s['init_cash']:,.0f} / {s['final_equity']:,.0f}",
            f"总收益率          : {s['total_return']:>8.2%}",
            f"年化收益率        : {s['cagr']:>8.2%}",
            f"年化波动率        : {s['ann_vol']:>8.2%}",
            f"夏普比率          : {s['sharpe']:>8.2f}",
            f"最大回撤          : {s['max_drawdown']:>8.2%}",
            f"Calmar 比率       : {s['calmar']:>8.2f}",
            f"交易次数          : {s['n_trades']}  (被涨跌停拒绝 {s['n_rejected']} 笔)",
            f"总成本            : {s['total_cost']:,.0f}",
        ]
        return "\n".join(lines)


def _commission(amount: float) -> float:
    """佣金：万 2.5，单笔最低 5 元。"""
    return max(amount * COMMISSION_RATE, 5.0)


def _buy_cost_per_share(px_open: float) -> float:
    """买入每股含滑点与费用的预期支出（用于 sizing 预留）。"""
    return px_open * (1 + SLIPPAGE) * (1 + _BUY_FEE_RATE)


def run_backtest(
    df: pd.DataFrame,
    target_weights: pd.Series,
    init_cash: float = INIT_CASH,
    limit_pct: float = 0.10,
    rebalance_band: float = 0.02,
) -> BTResult:
    """运行单标的回测。

    Parameters
    ----------
    df : 行情 DataFrame（需含 open/high/low/close），DatetimeIndex
    target_weights : 策略目标权重序列（0~1），T 日收盘时点计算。
                     NaN 视为 0；引擎自动 shift(1)，用次日开盘价撮合。
    limit_pct : 涨跌停幅度：主板 0.10、创业板/科创板 0.20、ST 0.05。
    rebalance_band : 调仓死区。目标与当前仓位之差占资产比例低于该值则不动，
                     防止因整手取整造成每日微量换手。
    """
    w = target_weights.reindex(df.index).fillna(0.0).clip(0.0, 1.0)
    exec_w = w.shift(1).fillna(0.0)      # 关键：T 日收盘的信号，次日才执行

    cash = float(init_cash)
    shares = 0
    n_rejected = 0
    records: list[tuple] = []
    equity_vals: list[float] = []
    wt_vals: list[float] = []
    closes = df["close"].to_numpy()
    opens = df["open"].to_numpy()
    dates = df.index

    for i in range(len(df)):
        o = opens[i]
        prev_c = closes[i - 1] if i > 0 else o

        # ---- 计算目标股数（整手）与净差 ----
        equity_now = cash + shares * o
        want = int(equity_now * exec_w.iat[i] // (o * LOT_SIZE)) * LOT_SIZE
        net = want - shares

        if net != 0 and abs(net) * o / max(equity_now, 1e-9) >= rebalance_band:
            if net > 0:
                # 涨停买不进：开盘较昨收涨幅达到限制
                if prev_c > 0 and o >= prev_c * (1 + limit_pct) - 1e-9:
                    n_rejected += 1
                else:
                    # 为滑点与费用预留现金后，现金能负担的最大整手数量
                    afford = int(
                        cash // (_buy_cost_per_share(o) * LOT_SIZE)
                    ) * LOT_SIZE
                    lot = min(net, afford)
                    if lot > 0:
                        px = o * (1 + SLIPPAGE)
                        gross = lot * o                       # 费用以未含滑点金额计
                        cost = _commission(gross) + gross * TRANSFER_FEE_RATE
                        spend = lot * px + cost
                        if spend <= cash + 1e-6:
                            cash -= spend
                            shares += lot                     # 当日买入，明日才可卖
                            records.append((dates[i], "BUY", lot, px, cost))
            else:
                # 跌停卖不出：开盘较昨收跌幅达到限制
                if prev_c > 0 and o <= prev_c * (1 - limit_pct) + 1e-9:
                    n_rejected += 1
                else:
                    lot = min(-net, shares)                   # 只能卖已有持仓(T+1下不含今日买入)
                    px = o * (1 - SLIPPAGE)
                    gross = lot * o
                    cost = (_commission(gross)
                            + gross * (STAMP_TAX_RATE + TRANSFER_FEE_RATE))
                    cash += lot * px - cost
                    shares -= lot
                    records.append((dates[i], "SELL", lot, px, cost))

        equity_vals.append(cash + shares * closes[i])
        wt_vals.append(shares * opens[i] / (cash + shares * o)
                       if (cash + shares * o) > 0 else 0.0)

    equity = pd.Series(equity_vals, index=df.index, name="equity")
    weights = pd.Series(wt_vals, index=df.index, name="weight")
    trades = pd.DataFrame(records, columns=["date", "side", "shares", "price", "cost"])

    return BTResult(equity=equity, trades=trades, weights=weights,
                    stats=_calc_stats(equity, init_cash, trades, n_rejected))


def _calc_stats(equity: pd.Series, init_cash: float,
                trades: pd.DataFrame, n_rejected: int) -> dict:
    ret = equity.pct_change().dropna()
    years = len(equity) / 244.0                    # A 股年均约 244 个交易日
    total_return = equity.iloc[-1] / init_cash - 1
    cagr = (equity.iloc[-1] / init_cash) ** (1 / max(years, 1e-9)) - 1
    ann_vol = ret.std() * np.sqrt(244)
    sharpe = (ret.mean() * 244) / ann_vol if ann_vol > 0 else 0.0
    dd = equity / equity.cummax() - 1
    max_dd = float(dd.min())
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
    return {
        "init_cash": float(init_cash),
        "final_equity": float(equity.iloc[-1]),
        "total_return": float(total_return),
        "cagr": float(cagr),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "max_drawdown": max_dd,
        "calmar": float(calmar),
        "n_trades": int(len(trades)),
        "n_rejected": int(n_rejected),
        "total_cost": float(trades["cost"].sum()) if not trades.empty else 0.0,
    }
