#!/usr/bin/env python3
"""Round 31 龙虎榜数据抓取：逐年 → data/round2/lhb.parquet。

数据源: akshare.stock_lhb_detail_em(日期范围)（东财, 按年批量, 单次秒级）。
覆盖: 2013~2026 各年龙虎榜(净买额/净买额占总成交比/上榜原因/上榜后收益)。
含: 代码/上榜日/净买额/净买额占总成交比/上榜原因/上榜后1/2/5/10日。

用法: python research/fetch_lhb.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_FILE = Path("data/round2/lhb.parquet")


def fetch_all(years: list[int]) -> pd.DataFrame:
    import akshare as ak

    frames = []
    fails = []
    for i, y in enumerate(years, 1):
        try:
            df = ak.stock_lhb_detail_em(start_date=f"{y}0101", end_date=f"{y}1231")
            df["上榜日"] = pd.to_datetime(df["上榜日"])
            frames.append(df)
            print(f"  [{i}/{len(years)}] {y}: {len(df)} 行", flush=True)
        except Exception as e:  # noqa: BLE001 — 单年失败不中断
            fails.append((y, str(e)[:80]))
            print(f"  [{i}/{len(years)}] {y}: 失败 {e}", flush=True)
        time.sleep(0.5)
    if frames:
        all_df = pd.concat(frames, ignore_index=True)
        all_df.to_parquet(OUT_FILE, index=False)
    print(
        f"\n完成: {len(frames)}/{len(years)} 年, 共 {len(all_df) if frames else 0} 行 → {OUT_FILE}"
    )
    if fails:
        print(f"失败 {len(fails)} 年: {fails}")
    return all_df if frames else pd.DataFrame()


def integrity_report(df: pd.DataFrame) -> None:
    if df.empty:
        print("无数据")
        return
    df = df.copy()
    df["year"] = df["上榜日"].dt.year
    print("\n== 各年行数(抽样) ==")
    print(df.groupby("year").size().iloc[:4].to_string())
    print("...")
    print(df.groupby("year").size().iloc[-2:].to_string())
    print(
        f"\n覆盖股票数: {df['代码'].nunique()} | 净买额缺失: {df['净买额'].isna().sum()} 行"
    )
    print(
        f"上榜后1日非空: {df['上榜后1日'].notna().sum()} 行 (占比 {df['上榜后1日'].notna().mean():.0%})"
    )


if __name__ == "__main__":
    df = fetch_all(list(range(2013, 2027)))
    integrity_report(df)
