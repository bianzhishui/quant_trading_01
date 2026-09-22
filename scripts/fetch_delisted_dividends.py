#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""退市股分红补抓 —— 推翻"退市分红不可得"结论(同花顺 history_dividend_detail 接口可用)。

池: stock_basic 主板退市股 − dividends.parquet 已有 code。
源: akshare stock_history_dividend_detail(同花顺, 含送股/转增/派息/进度/除权除息日)。
映射: 仅收 进度=="实施"; date=除权除息日; cashBeforeTax=派息/10(每股);
      stocksPs=(送股+转增)/10(每股); total_shares/eps=NaN(无东财列)。
写: 并入 data/round2/dividends.parquet(读现有+concat+去重, 分批原子写)。
用法: python tmp/fetch_delisted_dividends.py [--limit N]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")
from quant_trading_01.data_io import stock_basic

OUT = Path("data/round2/dividends.parquet")
BATCH = 40


def main() -> None:
    sb = stock_basic()
    od = sb["outDate"].astype(str).str.strip()
    delisted = ~od.isin(["", "NaT", "nan", "None"])
    mb = sb["code"].str.startswith(("sh.60", "sz.00"))
    sel = sb[delisted & mb]
    have = set(pd.read_parquet(OUT)["code"]) if OUT.exists() else set()
    todo = sel[~sel["code"].isin(have)]
    print(
        f"主板退市 {len(sel)}, 已有分红 {len(have & set(sel['code']))}, 待抓 {len(todo)}",
        flush=True,
    )
    if "--limit" in sys.argv:
        todo = todo.head(int(sys.argv[sys.argv.index("--limit") + 1]))

    import akshare as ak

    rows: list[pd.DataFrame] = []
    n_ok = n_err = 0
    t0 = time.time()
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        c = r["code"]
        try:
            df = ak.stock_history_dividend_detail(symbol=c.split(".")[1])
        except Exception as e:
            n_err += 1
            print(
                f"  ERR {c} {r['code_name']}: {type(e).__name__} {str(e)[:50]}",
                flush=True,
            )
            continue
        if df is None or len(df) == 0:
            continue
        df = df[df["进度"] == "实施"].copy()
        if len(df) == 0:
            continue
        ex = pd.to_datetime(df["除权除息日"], errors="coerce")
        out = pd.DataFrame(
            {
                "code": c,
                "date": ex,
                "cashBeforeTax": pd.to_numeric(df["派息"], errors="coerce") / 10.0,
                "stocksPs": (
                    pd.to_numeric(df["送股"], errors="coerce")
                    + pd.to_numeric(df["转增"], errors="coerce")
                )
                / 10.0,
                "total_shares": float("nan"),
                "eps": float("nan"),
            }
        )
        out = out.dropna(subset=["date"])
        if len(out):
            rows.append(out)
            n_ok += 1
        if i % BATCH == 0 and rows:
            prev = pd.read_parquet(OUT) if OUT.exists() else None
            all_df = pd.concat(
                [prev, pd.concat(rows, ignore_index=True)], ignore_index=True
            )
            all_df = all_df.drop_duplicates(subset=["code", "date"]).sort_values(
                ["code", "date"]
            )
            tmp = OUT.with_suffix(".parquet.tmp")
            all_df.to_parquet(tmp, index=False)
            tmp.replace(OUT)
            rows = []
            print(
                f"  [{i}/{len(todo)}] 累计 {len(all_df)} 行/{all_df['code'].nunique()} 只, "
                f"失败 {n_err}, 耗时 {time.time() - t0:.0f}s",
                flush=True,
            )
        time.sleep(0.5)

    if rows:
        prev = pd.read_parquet(OUT) if OUT.exists() else None
        all_df = pd.concat(
            [prev, pd.concat(rows, ignore_index=True)], ignore_index=True
        )
        all_df = all_df.drop_duplicates(subset=["code", "date"]).sort_values(
            ["code", "date"]
        )
        tmp = OUT.with_suffix(".parquet.tmp")
        all_df.to_parquet(tmp, index=False)
        tmp.replace(OUT)
    print(f"完成: 本次补 {n_ok}, 失败 {n_err}", flush=True)


if __name__ == "__main__":
    main()
