#!/usr/bin/env python3
"""Round 25 业绩预告数据抓取：历次报告期 → data/round2/earnings_forecast.parquet。

数据源: akshare.stock_yjyg_em(date=报告期)（东方财富业绩预告, 单次秒级）。
覆盖: 2014-03-31 ~ 2026-09-30 各报告期(0331/0630/0930/1231)。

用法: python research/fetch_earnings_forecast.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_FILE = Path("data/round2/earnings_forecast.parquet")


def report_dates() -> list[str]:
    """2014-03-31 ~ 2026-09-30 的各报告期（8位数字）。"""
    periods = []
    for y in range(2014, 2027):
        for m in ("0331", "0630", "0930", "1231"):
            if (y, m) < (2014, "0331"):
                continue
            if (y, m) > (2026, "0930"):
                continue
            periods.append(f"{y}{m}")
    return periods


def fetch_all(dates: list[str]) -> pd.DataFrame:
    import akshare as ak

    frames = []
    fails = []
    for i, rd in enumerate(dates, 1):
        try:
            df = ak.stock_yjyg_em(date=rd)
            df["报告期"] = rd
            frames.append(df)
            print(f"  [{i}/{len(dates)}] {rd}: {len(df)} 行", flush=True)
        except Exception as e:  # noqa: BLE001 — 单期失败不中断
            fails.append((rd, str(e)[:80]))
            print(f"  [{i}/{len(dates)}] {rd}: 失败 {e}", flush=True)
        time.sleep(0.3)  # 温和限速, 避免反爬
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
    """完整性验证: 各报告期行数(历史早期是否稀疏)。"""
    if df.empty:
        print("无数据")
        return
    cnt = df.groupby("报告期").size()
    print("\n== 各报告期行数(2014~2026) ==")
    full = cnt.reindex(report_dates()).fillna(0).astype(int)
    print(full.to_string())
    n_codes = df["股票代码"].nunique()
    print(
        f"\n覆盖股票数: {n_codes} | 净利润预告行数: {(df['预测指标'] == '净利润').sum()}"
    )


if __name__ == "__main__":
    df = fetch_all(report_dates())
    integrity_report(df)
