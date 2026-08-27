# -*- coding: utf-8 -*-
"""数据获取与本地缓存。首选 baostock（稳定免费），akshare 兜底。

复权说明：baostock adjustflag 中 ``"2"`` 为前复权（回测推荐）、
``"3"`` 为不复权；本模块对外统一用 ``adjust="qfq"/"hfq"/""`` 表达。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

_COLS = ["open", "high", "low", "close", "volume", "amount"]

_ADJUST_FLAG = {"qfq": "2", "hfq": "1", "": "3"}


def _bs_symbol(symbol: str) -> str:
    """600519 -> sh.600519；000001/300750 -> sz.xxxxxx；688xxx -> sh.688xxx."""
    if symbol.startswith(("sh.", "sz.", "bj.")):
        return symbol
    if symbol.startswith("6") or symbol.startswith(("9", "688")):
        return f"sh.{symbol}"
    return f"sz.{symbol}"


def _fetch_baostock(bs_code: str, start: str, end: str,
                    adjust_flag: str, is_index: bool) -> pd.DataFrame:
    """用 baostock 拉日线；start/end 为 YYYY-MM-DD。失败抛 RuntimeError。"""
    import baostock as bs

    lg = bs.login()
    try:
        if lg.error_code != "0":
            raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
        fields = ("date,open,high,low,close,volume,amount"
                  if not is_index else
                  "date,open,high,low,close,volume,amount")
        rs = bs.query_history_k_data_plus(
            bs_code, fields, start_date=start, end_date=end,
            frequency="d",
            adjustflag=adjust_flag if not is_index else "3")
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if rs.error_code != "0":
            raise RuntimeError(f"baostock 查询失败: {rs.error_msg}")
    finally:
        bs.logout()

    if not rows:
        raise RuntimeError(f"{bs_code} 未取到数据")

    df = pd.DataFrame(rows, columns=["date"] + _COLS)
    df["date"] = pd.to_datetime(df["date"])
    for c in _COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # 停牌日成交量为 0 / 空，价格保持前值即可参与回测（量 0 天不产生信号噪声）
    return df.set_index("date").sort_index()[_COLS].dropna(subset=["close"])


def load_stock_daily(
    symbol: str = "600519",
    start: str = "20200101",
    end: str | None = None,
    adjust: str = "qfq",
    refresh: bool = False,
) -> pd.DataFrame:
    """拉取 A 股个股日线并缓存到 data/ 目录（CSV）。

    Parameters
    ----------
    symbol : 6 位股票代码，如 ``600519``、``000001``、``300750``
    start, end : 形如 ``YYYYMMDD`` 的日期字符串；end 为 None 表示到今天
    adjust :
        - ``"qfq"`` 前复权（**回测推荐**，保证价格序列连续可比）
        - ``"hfq"`` 后复权
        - ``""``   不复权（仅用于看真实成交价，勿直接用于回测）
    refresh : True 时强制重新下载，忽略缓存

    Returns
    -------
    pd.DataFrame，列为 open/high/low/close/volume/amount，索引为 DatetimeIndex
    """
    DATA_DIR.mkdir(exist_ok=True)
    _s = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    e = end or pd.Timestamp.today().strftime("%Y%m%d")
    _e = f"{e[:4]}-{e[4:6]}-{e[6:]}"
    cache = DATA_DIR / f"{symbol}_daily_{adjust}_{start}_{e}.csv"

    if cache.exists() and not refresh:
        df = pd.read_csv(cache, parse_dates=["date"], index_col="date")
        return df[_COLS]

    try:                                   # 首选 baostock
        df = _fetch_baostock(_bs_symbol(symbol), _s, _e,
                             _ADJUST_FLAG.get(adjust, "2"), is_index=False)
    except Exception as exc:               # 兜底 akshare 东方财富源
        print(f"baostock 失败({exc})，改用 akshare...")
        import akshare as ak
        raw = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                 start_date=start, end_date=e,
                                 adjust=adjust)
        if raw is None or raw.empty:
            raise RuntimeError(f"{symbol} 两个数据源均未取到数据")
        cmap = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
                "最低": "low", "成交量": "volume", "成交额": "amount"}
        df = raw.rename(columns=cmap)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()[_COLS]

    df.to_csv(cache)
    return df


def load_index_daily(
    symbol: str = "000300",
    start: str = "20200101",
    end: str | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """拉取指数日线（沪深300 ``000300``），用作业绩基准。列结构同上。"""
    DATA_DIR.mkdir(exist_ok=True)
    _s = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    e = end or pd.Timestamp.today().strftime("%Y%m%d")
    _e = f"{e[:4]}-{e[4:6]}-{e[6:]}"
    cache = DATA_DIR / f"idx{symbol}_daily_{start}_{e}.csv"

    if cache.exists() and not refresh:
        df = pd.read_csv(cache, parse_dates=["date"], index_col="date")
        return df[_COLS]

    try:
        # 中证/上证指数系列(000xxx)托管在沪市，深证系列(399xxx)在深市
        prefix = "sh" if symbol.startswith("0") else "sz"
        df = _fetch_baostock(f"{prefix}.{symbol}", _s, _e, "3", is_index=True)
    except Exception as exc:
        print(f"baostock 指数失败({exc})，改用 akshare...")
        import akshare as ak
        raw = ak.index_zh_a_hist(symbol=symbol, period="daily",
                                 start_date=start, end_date=e)
        if raw is None or raw.empty:
            raise RuntimeError(f"指数 {symbol} 未取到数据")
        cmap = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
                "最低": "low", "成交量": "volume", "成交额": "amount"}
        df = raw.rename(columns=cmap)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()[_COLS]

    df.to_csv(cache)
    return df


def make_synthetic_daily(n_days: int = 800, seed: int = 42) -> pd.DataFrame:
    """生成随机游走行情，供离线测试回测引擎使用（无网络时也能跑通流程）。"""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-02", periods=n_days)
    ret = rng.normal(loc=0.0003, scale=0.02, size=n_days)
    close = 50.0 * np.exp(np.cumsum(ret))
    open_ = close * (1 + rng.normal(0, 0.004, n_days))
    high = np.maximum(open_, close) * (1 + abs(rng.normal(0, 0.006, n_days)))
    low = np.minimum(open_, close) * (1 - abs(rng.normal(0, 0.006, n_days)))
    vol = rng.integers(5_000_000, 30_000_000, n_days).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": vol, "amount": vol * close},
        index=pd.DatetimeIndex(idx, name="date"),
    )
