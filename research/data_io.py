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

from research.config import get_config

# 路径不设模块级常量（惰性）：每次调用从当前配置单例取，响应 --config/QUANT_CONFIG
ROOT = Path(__file__).resolve().parent.parent
NUMERIC = ["close", "pbMRQ", "turn", "amount", "peTTM"]

# 数据版本计数器: 每次写盘 +1。进程内缓存(paper_live._load_all 等)以它为键,
# 保证"同进程内先 fetch 后 mark"不会读到 fetch 前的旧数据。
_DATA_VERSION = 0


def data_version() -> int:
    return _DATA_VERSION


def _bump_data_version() -> None:
    global _DATA_VERSION
    _DATA_VERSION += 1


def _cfg_paths() -> tuple[Path, Path, Path]:
    """从配置实时取数据路径（惰性, 每次取当前单例）。返回 (full_dir, full_file, stock_basic)。"""
    p = get_config().paths
    return Path(p.full_dir), Path(p.full_file), Path(p.stock_basic)


def load_full_daily(
    columns: list[str] | None = None, filters: list | None = None
) -> pd.DataFrame:
    """读全市场日线(全部行, 或按 filters 行组过滤)。分区目录优先, 不存在则回退旧单文件。"""
    full_dir, full_file, _ = _cfg_paths()
    if full_dir.exists():
        return pd.read_parquet(full_dir, columns=columns, filters=filters)
    return pd.read_parquet(full_file, columns=columns, filters=filters)


def full_daily_codes() -> set[str]:
    """已落盘的 code 集合(断点续传用)。"""
    d = load_full_daily(columns=["code"])
    return set(d["code"].unique())


def data_max_date() -> pd.Timestamp:
    d = load_full_daily(columns=["date"])
    return pd.Timestamp(d["date"].max())


def data_max_date_fast() -> pd.Timestamp | None:
    """用 parquet 列块 min/max 统计取最大日期(不读行, 毫秒级)。

    年分区缺失或统计不可用时回退 None, 由调用方全读兜底。
    """
    full_dir, _, _ = _cfg_paths()
    if not full_dir.exists():
        return None
    import pyarrow.parquet as pq

    mx = None
    for p in sorted(full_dir.glob("*.parquet")):
        pf = pq.ParquetFile(p)
        names = pf.schema_arrow.names
        if "date" not in names:
            continue
        ci = names.index("date")
        for rg in range(pf.metadata.num_row_groups):
            st = pf.metadata.row_group(rg).column(ci).statistics
            if st is not None and st.has_min_max and st.max is not None:
                v = pd.Timestamp(st.max)
                if mx is None or v > mx:
                    mx = v
    return mx


def universe_codes() -> list[str]:
    """策略宇宙: stock_basic 中 type=1 且主板(sh.60/sz.00), status 不限(含退市)。"""
    sb = stock_basic()
    ok = sb[sb["type"] == "1"]
    return sorted(c for c in ok["code"] if c.startswith(("sh.60", "sz.00")))


def stock_basic() -> pd.DataFrame:
    """证券元数据(code, code_name, ipoDate, outDate, type, status)。"""
    _, _, stock_basic_path = _cfg_paths()
    return pd.read_parquet(stock_basic_path)


def delist_map() -> dict[str, pd.Timestamp]:
    """code → 退市日(outDate)。仅在市股不含于此映射。"""
    sb = stock_basic()
    sb = sb[sb["type"] == "1"]
    out = sb[sb["outDate"].notna() & (sb["outDate"] != "")]
    return {r["code"]: pd.Timestamp(r["outDate"]) for _, r in out.iterrows()}


def write_full_daily(df: pd.DataFrame) -> int:
    """按年分区原子写入(全量合并语义: df 与既有分区合并去重)。

    返回**真实全量行数**(全部年份分区之和, 用 parquet 元数据, 秒级)。
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    full_dir, _, _ = _cfg_paths()
    full_dir.mkdir(parents=True, exist_ok=True)
    for year, g in df.groupby("year"):
        path = full_dir / f"{int(year)}.parquet"
        merged = g.drop(columns=["year"])
        if path.exists():  # 与既有分区合并(本函数不做全量重算, 去重交给调用前)
            prev = pd.read_parquet(path)
            merged = pd.concat([prev, merged], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date", "code"]).sort_values("date")
        tmp = path.with_suffix(".parquet.tmp")
        merged.to_parquet(tmp, index=False)  # snappy 默认, float64 保持
        os.replace(tmp, path)
    _bump_data_version()
    # 真实全量行数(元数据, 秒级)
    import pyarrow.parquet as pq

    return int(
        sum(pq.ParquetFile(p).metadata.num_rows for p in full_dir.glob("*.parquet"))
    )


def write_full_daily_replace(df: pd.DataFrame) -> dict[str, int]:
    """按年分区原子写入(替换语义: df 即各年份的最终内容, 不与既有合并)。"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    full_dir, _, _ = _cfg_paths()
    full_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for year, g in df.groupby("year"):
        path = full_dir / f"{int(year)}.parquet"
        merged = (
            g.drop(columns=["year"])
            .drop_duplicates(subset=["date", "code"])
            .sort_values("date")
        )
        tmp = path.with_suffix(".parquet.tmp")
        merged.to_parquet(tmp, index=False)
        os.replace(tmp, path)
        written[str(int(year))] = len(merged)
    _bump_data_version()
    return written
