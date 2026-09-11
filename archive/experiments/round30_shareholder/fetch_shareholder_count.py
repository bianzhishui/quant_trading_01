#!/usr/bin/env python3
"""Round 30 股东户数数据抓取：历次季度报告期 → data/round2/shareholder_count.parquet。

数据源: akshare.stock_zh_a_gdhs(报告期)（东财, 按报告期批量返回全市场, 单次秒级）。
覆盖: 2013-03-31 ~ 2026-06-30 各季度报告期(~54 期)。
含: 代码/股东户数-本次/上次/增减比例/公告日期/统计截止日。

用法: python research/fetch_shareholder_count.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_FILE = Path("data/round2/shareholder_count.parquet")


def report_dates() -> list[str]:
    """2013-03-31 ~ 2026-06-30 各季度报告期（8位数字, 东财格式）。"""
    periods = []
    for y in range(2013, 2027):
        for m in ("0331", "0630", "0930", "1231"):
            d = f"{y}{m}"
            if "20130331" <= d <= "20260630":
                periods.append(d)
    return periods


def fetch_all(dates: list[str]) -> pd.DataFrame:
    import akshare as ak

    frames = []
    fails = []
    for i, rd in enumerate(dates, 1):
        try:
            df = ak.stock_zh_a_gdhs(symbol=rd)
            df["报告期"] = rd
            frames.append(df)
            print(f"  [{i}/{len(dates)}] {rd}: {len(df)} 行", flush=True)
        except Exception as e:  # noqa: BLE001 — 单期失败不中断
            fails.append((rd, str(e)[:80]))
            print(f"  [{i}/{len(dates)}] {rd}: 失败 {e}", flush=True)
        time.sleep(0.4)  # 温和限速
    if frames:
        all_df = pd.concat(frames, ignore_index=True)
        all_df.to_parquet(OUT_FILE, index=False)
    print(
        f"\n完成: {len(frames)}/{len(dates)} 期, 共 {len(all_df) if frames else 0} 行 → {OUT_FILE}"
    )
    if fails:
        print(f"失败 {len(fails)} 期: {fails}")
    return all_df if frames else pd.DataFrame()


def integrity_report(df: pd.DataFrame) -> None:
    if df.empty:
        print("无数据")
        return
    cnt = df.groupby("报告期").size()
    print("\n== 各报告期行数(2013~2026, 抽样) ==")
    print(cnt.iloc[:5].to_string())
    print("...")
    print(cnt.iloc[-3:].to_string())
    print(
        f"\n覆盖股票数: {df['代码'].nunique()} | 有无公告日期缺失: {df['公告日期'].isna().sum()} 行"
    )


if __name__ == "__main__":
    df = fetch_all(report_dates())
    integrity_report(df)
