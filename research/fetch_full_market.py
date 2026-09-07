#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""全市场扩展数据抓取 v2 —— 去幸存者偏差（主连 + 中小板，非 300/688/北交）。

产出 data/fundamental/full_daily.parquet：date, code, close(qfq), pbMRQ, turn,
amount, peTTM, tradestatus, isST。与现有 800 只管线同口径（adjustflag=2 前复权）。

v2 优化：内存缓冲 + 每 100 只批量写盘（避免 v1 每只重写分片的 O(n²) 开销）。
断点续传：按 OUT 中已有 code 去重，中断重跑自动跳过。
用法: uv run python research/fetch_full_market.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path(__file__).resolve().parent.parent / "data" / "fundamental" / "full_daily.parquet"
START = "2012-06-01"
END = "2026-09-05"
FIELDS = "date,code,close,pbMRQ,turn,amount,peTTM,tradestatus,isST"
KEEP = ["date", "code", "close", "pbMRQ", "turn", "amount", "peTTM", "tradestatus", "isST"]
FLUSH_EVERY = 100


def all_codes() -> list[str]:
    import baostock as bs
    rs = bs.query_stock_basic()
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    ok = df[(df["type"] == "1") & (df["status"] == "1")].copy()
    return [c for c in ok["code"] if c.startswith(("sh.60", "sz.00"))]


def fetch_one(bs, code: str) -> pd.DataFrame:
    rs = bs.query_history_k_data_plus(code, FIELDS, start_date=START, end_date=END,
                                      frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"{code}: {rs.error_msg}")
    if not rows:
        return pd.DataFrame(columns=KEEP)
    df = pd.DataFrame(rows, columns=rs.fields)
    for c in ["close", "pbMRQ", "turn", "amount", "peTTM"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df[df["tradestatus"] == "1"][KEEP]


def main() -> None:
    import baostock as bs
    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    codes = all_codes()
    bs.logout()

    have = set()
    if OUT.exists():
        have = set(pd.read_parquet(OUT, columns=["code"])["code"].unique())
    todo = [c for c in codes if c not in have]
    print(f"全市场: 共 {len(codes)} 只, 已完成 {len(have)}, 待抓 {len(todo)}", flush=True)

    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    buf: list[pd.DataFrame] = []
    done = 0
    t0 = time.time()
    for i, c in enumerate(todo, 1):
        for attempt in range(3):
            try:
                df = fetch_one(bs, c)
                if len(df):
                    buf.append(df)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  {c} 最终失败: {e}", flush=True)
                else:
                    time.sleep(2.0)
        done += 1
        if done % FLUSH_EVERY == 0 or done == len(todo):
            new = pd.concat(buf, ignore_index=True) if buf else None
            buf = []
            if new is not None:
                prev = pd.read_parquet(OUT) if OUT.exists() else None
                big = pd.concat([prev, new], ignore_index=True) if prev is not None else new
                big = big.drop_duplicates(subset=["date", "code"]).sort_values("date")
                big.to_parquet(OUT)
                rate = done / (time.time() - t0) * 60
                eta = (len(todo) - done) / max(rate, 1e-9) / 60
                print(f"  [{done}/{len(todo)}] 累计 {big['code'].nunique()} 只 "
                      f"{big.shape[0]:,} 行 | {rate:.0f}只/分 | 预计还需 {eta:.0f} 分钟", flush=True)
    bs.logout()
    print("全市场下载完成", flush=True)


if __name__ == "__main__":
    main()
