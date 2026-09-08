#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""统一的全市场日线读取层 —— 全库唯一入口, 屏蔽物理存储细节。

存储布局(Round 17 起):
  data/fundamental/full_daily/          按年分区目录(2012.parquet...2026.parquet)
  data/fundamental/full_daily.parquet   旧单文件(过渡期回退, 分区就绪后可删)
  data/fundamental/stock_basic.parquet  证券元数据(code/code_name/ipoDate/outDate/type/status)

约定:
- 数值列 float64, 压缩 snappy(默认), 写盘 index=False, 原子写(.tmp + os.replace)
- 停牌日无行(tradestatus=="1" 才入库); 退市股行止于退市年
- 任何脚本不得再直接 pd.read_parquet(full_daily 路径), 一律走本模块
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FULL_DIR = ROOT / "data" / "fundamental" / "full_daily"
FULL_FILE = ROOT / "data" / "fundamental" / "full_daily.parquet"
STOCK_BASIC = ROOT / "data" / "fundamental" / "stock_basic.parquet"
NUMERIC = ["close", "pbMRQ", "turn", "amount", "peTTM"]


def load_full_daily(columns: list[str] | None = None) -> pd.DataFrame:
    """读全市场日线(全部行)。分区目录优先, 不存在则回退旧单文件。"""
    if FULL_DIR.exists():
        return pd.read_parquet(FULL_DIR, columns=columns)
    return pd.read_parquet(FULL_FILE, columns=columns)


def full_daily_codes() -> set[str]:
    """已落盘的 code 集合(断点续传用)。"""
    d = load_full_daily(columns=["code"])
    return set(d["code"].unique())


def data_max_date() -> pd.Timestamp:
    d = load_full_daily(columns=["date"])
    return pd.Timestamp(d["date"].max())


def universe_codes() -> list[str]:
    """策略宇宙: stock_basic 中 type=1 且主板(sh.60/sz.00), status 不限(含退市)。"""
    sb = stock_basic()
    ok = sb[sb["type"] == "1"]
    return sorted(c for c in ok["code"] if c.startswith(("sh.60", "sz.00")))


def stock_basic() -> pd.DataFrame:
    """证券元数据(code, code_name, ipoDate, outDate, type, status)。"""
    return pd.read_parquet(STOCK_BASIC)


def delist_map() -> dict[str, pd.Timestamp]:
    """code → 退市日(outDate)。仅在市股不含于此映射。"""
    sb = stock_basic()
    sb = sb[sb["type"] == "1"]
    out = sb[sb["outDate"].notna() & (sb["outDate"] != "")]
    return {r["code"]: pd.Timestamp(r["outDate"]) for _, r in out.iterrows()}


def write_full_daily(df: pd.DataFrame) -> dict[str, int]:
    """按年分区原子写入(全量合并语义: df 与既有分区合并去重)。

    返回 {年份: 写入行数}。供 fetch 脚本落盘; 调用方需已去重排序或交由本函数处理。
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for year, g in df.groupby("year"):
        path = FULL_DIR / f"{int(year)}.parquet"
        merged = g.drop(columns=["year"])
        if path.exists():  # 与既有分区合并(本函数不做全量重算, 去重交给调用前)
            prev = pd.read_parquet(path)
            merged = pd.concat([prev, merged], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date", "code"]).sort_values("date")
        tmp = path.with_suffix(".parquet.tmp")
        merged.to_parquet(tmp, index=False)  # snappy 默认, float64 保持
        os.replace(tmp, path)
        written[str(int(year))] = len(merged)
    return written


def write_full_daily_replace(df: pd.DataFrame) -> dict[str, int]:
    """按年分区原子写入(替换语义: df 即各年份的最终内容, 不与既有合并)。"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for year, g in df.groupby("year"):
        path = FULL_DIR / f"{int(year)}.parquet"
        merged = (
            g.drop(columns=["year"])
            .drop_duplicates(subset=["date", "code"])
            .sort_values("date")
        )
        tmp = path.with_suffix(".parquet.tmp")
        merged.to_parquet(tmp, index=False)
        os.replace(tmp, path)
        written[str(int(year))] = len(merged)
    return written
