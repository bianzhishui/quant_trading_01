#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""主板 5 分钟行情抓取(baostock, 2025 起), 按月分 parquet。

- 股票池: full_daily 最新日在市主板(sh.60*/sz.00*)
- 每只拉 2025-01-01 至今 5 分钟线(不复权, 与日线真实价口径一致)
- 按月分 parquet: data/fundamental/minute/YYYY-MM.parquet (列 code/date/time/open/high/low/close/volume/amount)
- 断点续传: _done.txt(已完成) / _failed.txt(失败) / 中断重跑自动跳过
- 分批落盘: 每 batch 只合并写月文件(读旧+concat+写), 避免逐只重写
- 会话: baostock 查询失败自动重登重试

用法: .venv/bin/python scripts/fetch_minute_5m.py [--limit N]  (--limit 试点前 N 只)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import load_config  # noqa: E402
from quant_trading_01.data_io import load_full_daily  # noqa: E402

FIELDS = "date,time,open,high,low,close,volume,amount"
COLS = ["code", "date", "time", "open", "high", "low", "close", "volume", "amount"]


def universe() -> list[str]:
    """在市主板: full_daily 最新日有收盘的 code。"""
    full = load_full_daily(columns=["date", "code", "close"])
    last = full["date"].max()
    live = set(full[full["date"] == last]["code"])
    mkt = {
        c
        for c in live
        if c.split(".")[0] in ("sh", "sz")
        and (c.startswith("sh.60") or c.startswith("sz.0"))
    }
    return sorted(mkt)


def fetch_one(bs, code: str, start: str, end: str) -> pd.DataFrame:
    rs = bs.query_history_k_data_plus(
        code, FIELDS, start_date=start, end_date=end, frequency="5", adjustflag="3"
    )
    rows = []
    while (rs.error_code == "0") & rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=FIELDS.split(","))
    df.insert(0, "code", code)
    return df


def month_key(date_s: str) -> str:
    return date_s[:7]  # YYYY-MM


def flush_batch(out_dir: Path, batch_df: pd.DataFrame):
    """按月合并写 parquet(读旧+concat+写)。"""
    if batch_df.empty:
        return
    for mk, g in batch_df.groupby(batch_df["date"].str[:7]):
        p = out_dir / f"{mk}.parquet"
        if p.exists():
            old = pd.read_parquet(p)
            g = pd.concat([old, g], ignore_index=True)
        g.to_parquet(p, index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="试点: 只抓前 N 只")
    args = ap.parse_args()
    cfg = load_config(None)
    out_dir = Path(cfg.fetch.minute.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done_p = out_dir / "_done.txt"
    fail_p = out_dir / "_failed.txt"
    done = set(done_p.read_text().split()) if done_p.exists() else set()
    failed = set(fail_p.read_text().split()) if fail_p.exists() else set()

    codes = universe()
    if args.limit:
        codes = codes[: args.limit]
    todo = [c for c in codes if c not in done and c not in failed]
    print(
        f"股票池 {len(codes)} 只 | 待抓 {len(todo)} 只 (已完成 {len(done)}, 失败 {len(failed)})"
    )

    import baostock as bs

    bs.login()
    t0 = time.time()
    batch = pd.DataFrame()
    batch_n = 0
    for i, code in enumerate(todo, 1):
        ok = False
        for attempt in range(3):
            try:
                df = fetch_one(
                    bs,
                    code,
                    cfg.fetch.minute.start,
                    cfg.fetch.minute.end or "2099-12-31",
                )
                if df.empty:
                    raise RuntimeError("empty result")
                batch = pd.concat([batch, df], ignore_index=True)
                batch_n += 1
                ok = True
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [{i}/{len(todo)}] {code} 失败: {str(e)[:60]}")
                    with fail_p.open("a") as f:
                        f.write(code + "\n")
                else:
                    print(
                        f"  [{i}/{len(todo)}] {code} 重试{attempt + 1}: {str(e)[:50]}",
                        flush=True,
                    )
                    bs.logout()
                    time.sleep(2)
                    bs.login()
        if ok:
            with done_p.open("a") as f:
                f.write(code + "\n")
        # 分批落盘
        if batch_n >= cfg.fetch.minute.batch:
            flush_batch(out_dir, batch)
            batch = pd.DataFrame()
            batch_n = 0
        if i % 50 == 0:
            el = (time.time() - t0) / i
            print(
                f"  进度 {i}/{len(todo)} | {el:.1f}s/只 | 剩余 ~{el * (len(todo) - i) / 3600:.1f}h",
                flush=True,
            )
        time.sleep(cfg.fetch.minute.pause)
    flush_batch(out_dir, batch)
    bs.logout()
    n_ok = len(done) + len(todo) - len(failed)
    print(
        f"\n完成: 成功 {n_ok}/{len(codes)} | 失败 {len(failed)} | 用时 {(time.time() - t0) / 3600:.1f}h"
    )
    for p in sorted(out_dir.glob("*.parquet")):
        print(f"  {p.name}: {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
