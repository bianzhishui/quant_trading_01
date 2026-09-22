#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""退市股真实价(不复权)补抓 —— 分批写盘 + 断点续传 + 东财限频退避。

池: stock_basic 主板(sh.60/sz.00)退市股 − raw_close_delisted.parquet 已有 code。
源: akshare stock_zh_a_hist(东财, adjust="") 不复权 = 历史真实价。
写: 每 BATCH 只原子写盘(读现有+concat), 失败重试 3 次退避递增。
用法: python tmp/fetch_raw_close_delisted.py [--limit N]
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")
from quant_trading_01.data_io import stock_basic

OUT = Path("data/round2/raw_close_delisted.parquet")
PAUSE = 0.8
BATCH = 40


def main() -> None:
    sb = stock_basic()
    od = sb["outDate"].astype(str).str.strip()
    delisted = ~od.isin(["", "NaT", "nan", "None"])
    mb = sb["code"].str.startswith(("sh.60", "sz.00"))
    sel = sb[delisted & mb]
    # 跳过研究窗口外退市(2013 前): 东财对超老退市股接口异常且本就不需要
    sel = sel[pd.to_datetime(sel["outDate"]) >= pd.Timestamp("2013-01-01")]
    done = set(pd.read_parquet(OUT)["code"]) if OUT.exists() else set()
    todo = sel[~sel["code"].isin(done)]
    print(
        f"窗口内退市股 {len(sel)}, 已有真实价 {len(done)}, 待抓 {len(todo)}", flush=True
    )
    if "--limit" in sys.argv:
        todo = todo.head(int(sys.argv[sys.argv.index("--limit") + 1]))

    import akshare as ak

    rows: list[pd.DataFrame] = []
    n_ok = n_err = 0
    t0 = time.time()
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        c, out = r["code"], pd.Timestamp(r["outDate"])
        end = min(out, pd.Timestamp.today()).strftime("%Y%m%d")
        ok = False
        for attempt in range(3):
            try:
                # 腾讯接口: 对退市股稳定可用(东财限频不稳定), 返回不复权真实价
                signal.alarm(60)  # 单请求超时保护(腾讯偶发挂起)
                df = ak.stock_zh_a_hist_tx(
                    symbol=c.split(".")[1],
                    start_date="20120601",
                    end_date=end,
                    adjust="",
                )
                signal.alarm(0)
                ok = True
                break
            except Exception:
                signal.alarm(0)
                time.sleep(4 * (attempt + 1))
        if not ok:
            n_err += 1
            print(f"  ERR {c} {r['code_name']}", flush=True)
            continue
        if df is not None and len(df):
            rows.append(
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(df["date"]),
                        "code": c,
                        "raw_close": df["close"].astype(float),
                    }
                )
            )
            n_ok += 1
        if i % BATCH == 0 and rows:
            prev = pd.read_parquet(OUT) if OUT.exists() else None
            all_df = pd.concat(
                [prev, pd.concat(rows, ignore_index=True)], ignore_index=True
            )
            all_df = all_df.drop_duplicates(subset=["date", "code"]).sort_values(
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
        time.sleep(PAUSE)

    if rows:
        prev = pd.read_parquet(OUT) if OUT.exists() else None
        all_df = pd.concat(
            [prev, pd.concat(rows, ignore_index=True)], ignore_index=True
        )
        all_df = all_df.drop_duplicates(subset=["date", "code"]).sort_values(
            ["code", "date"]
        )
        tmp = OUT.with_suffix(".parquet.tmp")
        all_df.to_parquet(tmp, index=False)
        tmp.replace(OUT)
    print(f"完成: 本次补 {n_ok}, 失败 {n_err}", flush=True)


if __name__ == "__main__":
    main()
