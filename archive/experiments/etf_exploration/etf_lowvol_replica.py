#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""ETF低波轮动策略复现（针对聚宽社区帖《开源一个年化超25%的ETF策略》）。

策略规则：
  每天计算池内各ETF最近60日对数收益标准差(波动率)；
  每周一调仓，全额持有波动率最低的一只；
  (执行细节: 周一用的信号来自上周五收盘数据, 避免未来函数)

复现验证的问题：
  Q1 规则本身是否真能赚钱(不抄作者的自选池, 用独立构造的池子)？
  Q2 收益来自"低波信号"还是"池子里恰好有债/金当避风港"？
     → 对照组: 只含股票ETF的池子跑同一规则
  Q3 扣掉交易成本后还剩多少？
  Q4 不同时间窗口结果稳不稳？

用法: uv run python research/etf_lowvol_replica.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data_loader import _fetch_fund_sina

# 代表性ETF池: 宽基股票 + 行业股票 + 海外股票 + 商品 + 债券
POOL = {
    "510300": "沪深300",
    "510500": "中证500",
    "159915": "创业板",
    "512880": "证券",
    "513100": "纳指",
    "518880": "黄金",
    "511010": "国债",
}
EQUITY_ONLY = ["510300", "510500", "159915", "512880", "513100"]
COST_ONE_WAY = 5e-4  # 单边成本0.05%(佣金+滑点; ETF免印花税)
VOL_WINDOW = 60


def load_pool() -> tuple[pd.DataFrame, dict]:
    """拉取池内全部ETF收盘价, 对齐到公共交易日。"""
    closes, names = {}, {}
    for code, name in POOL.items():
        try:
            df = _fetch_fund_sina(code, "20100101", "20260831")
            closes[code] = df["close"]
            names[code] = name
            print(
                f"  {code} {name}: {len(df)}行 {df.index[0].date()}~{df.index[-1].date()}"
            )
        except Exception as e:
            print(f"  {code} {name}: 获取失败, 剔除 ({e})")
    px = pd.DataFrame(closes).dropna()  # 内连接=只留公共交易日
    return px, names


def weekly_lowvol_positions(px: pd.DataFrame) -> pd.DataFrame:
    """生成每周一换仓的目标持仓(单只ETF, one-hot)。

    周一的信号基于上周五及更早数据( shifting 1 天保证无未来函数)。
    """
    logret = np.log(px / px.shift(1))
    vol = logret.rolling(VOL_WINDOW).std()
    vol_lag = vol.shift(1)  # 关键: 昨天才知道的波动率
    cols = list(px.columns)

    pos = pd.DataFrame(0.0, index=px.index, columns=cols)
    current = None
    for dt, row in vol_lag.iterrows():
        if dt.dayofweek == 0 and row.notna().all():  # 周一且波动率齐全才调仓
            current = row.idxmin()  # 波动率最低的一只
        if current is not None:
            pos.loc[dt, current] = 1.0
    return pos


def backtest(
    px: pd.DataFrame, pos: pd.DataFrame, cost: float = COST_ONE_WAY
) -> tuple[pd.Series, float]:
    """策略日收益 = 昨日持仓 × 今日收益 - 换仓成本。返回(净值, 年换手)。"""
    ret = px.pct_change().fillna(0.0)
    gross = (pos.shift(1) * ret).sum(axis=1)
    turnover = (pos.diff().abs().sum(axis=1)).fillna(0.0)
    net = gross - turnover * cost
    annual_turnover = float(turnover.sum() / 2 / (len(px) / 244))
    return (1 + net).cumprod(), annual_turnover


def metrics(nav: pd.Series, freq: int = 244) -> dict:
    ret = nav.pct_change().dropna()
    years = len(nav) / freq
    cagr = nav.iloc[-1] ** (1 / years) - 1
    vol = ret.std() * np.sqrt(freq)
    dd = (nav / nav.cummax() - 1).min()
    weekly = nav.resample("W").last().pct_change().dropna()
    return {
        "总收益": nav.iloc[-1] - 1,
        "年化": cagr,
        "波动": vol,
        "夏普": (ret.mean() * freq) / vol if vol > 0 else 0.0,
        "最大回撤": dd,
        "周胜率": (weekly > 0).mean(),
    }


def run_pool(px: pd.DataFrame, label: str, windows: dict) -> list[dict]:
    """对一个池子: 跑策略 + 对照组, 输出各窗口的指标行。"""
    pos = weekly_lowvol_positions(px)
    nav, turn = backtest(px, pos)
    ew_ret = px.pct_change().mean(axis=1).fillna(0.0)  # 对照: 等权持有全部
    ew_nav = (1 + ew_ret).cumprod()

    rows = []
    for wname, (s, e) in windows.items():
        nav_w, ew_w = nav[s:e], ew_nav[s:e]
        if len(nav_w) < 100:
            continue
        m = metrics(nav_w / nav_w.dropna().iloc[0])
        m.update({"组合": f"低波策略[{label}]", "窗口": wname, "年换手": turn})
        rows.append(m)
        m2 = metrics(ew_w / ew_w.dropna().iloc[0])
        m2.update({"组合": f"等权全池[{label}]", "窗口": wname, "年换手": 0.0})
        rows.append(m2)
    return rows


def main() -> None:
    print("拉取ETF池数据...")
    px, names = load_pool()
    print(f"\n公共交易日: {len(px)} 天  {px.index[0].date()} ~ {px.index[-1].date()}\n")

    windows = {
        "全历史": (px.index[0], px.index[-1]),
        "近六年(作者口径)": ("2020-08-01", px.index[-1]),
    }

    rows = run_pool(px, "股+债+金", windows)
    rows += run_pool(
        px[["510300", "510500", "159915", "512880", "513100"]], "仅股票", windows
    )
    rows += run_pool(
        px[["510300", "510500", "159915", "512880", "513100", "518880"]],
        "股+金",
        windows,
    )

    # 单标的基准(全历史)
    for code in px.columns:
        nav = px[code] / px[code].iloc[0]
        m = metrics(nav)
        m.update({"组合": names[code], "窗口": "全历史", "年换手": 0.0})
        rows.append(m)

    tab = pd.DataFrame(rows)[
        [
            "组合",
            "窗口",
            "总收益",
            "年化",
            "波动",
            "夏普",
            "最大回撤",
            "周胜率",
            "年换手",
        ]
    ]
    print(tab.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    # ---- 净值曲线图 ----
    fig, ax = plt.subplots(figsize=(11, 6))
    nav_full, _ = backtest(px, weekly_lowvol_positions(px))
    pos_eq = weekly_lowvol_positions(
        px[["510300", "510500", "159915", "512880", "513100"]]
    )
    nav_eq, _ = backtest(px[["510300", "510500", "159915", "512880", "513100"]], pos_eq)
    ax.plot(nav_full, label="低波轮动[股+债+金]", lw=1.4)
    ax.plot(nav_eq, label="低波轮动[仅股票]", lw=1.2)
    ax.plot(
        (1 + px.pct_change().mean(axis=1)).cumprod(), label="等权全池", lw=1, alpha=0.7
    )
    hs300 = px["510300"] / px["510300"].iloc[0]
    ax.plot(hs300, label="沪深300", lw=1, alpha=0.7)
    ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_title("ETF低波轮动策略复现 (对数净值)")
    out = Path(__file__).resolve().parent.parent / "output" / "etf_lowvol_replica.png"
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"\n图已保存: {out}")


if __name__ == "__main__":
    main()
