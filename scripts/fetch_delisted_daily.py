#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""退市股历史日线补抓(akshare 东财) → 并入 full_daily 年分区。

动机: full_daily 主板退市股中 2 只完全缺失 + 4 只尾部缺口(停牌股) → 修正幸存者偏差。
源: akshare.stock_zh_a_hist(东财, 前复权 qfq) —— baostock 对退市股挂起(实测确认)。
池: 研究窗口内(退市>=2013-01-01)退市股中 完全无日线 或 尾部缺口>tail_gap_days 的。
写: data_io.write_full_daily 合并语义(按年分区去重, 原子写), 不重复写入已有行。
字段: date/code/close/amount/turn 来自 akshare(单位与 baostock 一致);
      tradestatus="1"(停牌日无行); pbMRQ/peTTM/isST=NaN(akshare 日线无,
      研究时退市股排雷改用财务扣非)。
用法: uv run python scripts/fetch_delisted_daily.py [--limit N] [--codes 600485,000787] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config, load_config
from quant_trading_01.data_io import (
    load_full_daily,
    stock_basic,
    write_full_daily,
)


def _cfg():
    return get_config()


def delisted_mainboard() -> list[dict]:
    """主板(sh.60/sz.00)退市股清单: [{code, name, out_date}]。"""
    sb = stock_basic()
    sb = sb[sb["type"] == "1"]
    od = sb["outDate"].astype(str).str.strip()
    delisted = ~od.isin(["", "NaT", "nan", "None"])
    mb = sb["code"].str.startswith(("sh.60", "sz.00"))
    sel = sb[delisted & mb]
    out = []
    for _, r in sel.iterrows():
        out.append(
            {
                "code": r["code"],
                "name": r.get("code_name", ""),
                "out_date": pd.Timestamp(r["outDate"]),
            }
        )
    return out


def need_backfill(all_delisted: list[dict], tail_gap_days: int) -> list[dict]:
    """精确补缺: 研究窗口内(退市>=2013-01-01)且 完全无日线 或 尾部缺口>tail_gap_days。"""
    d = load_full_daily(columns=["date", "code"])
    d["date"] = pd.to_datetime(d["date"])
    last = d.groupby("code")["date"].max()
    todo = []
    for x in all_delisted:
        out = x["out_date"]
        if out < pd.Timestamp("2013-01-01"):  # 研究窗口外退市: 本来就不需要
            continue
        if x["code"] not in last.index:
            todo.append(x)  # 完全缺失
            continue
        mx = last[x["code"]]
        if (out - mx).days > tail_gap_days:
            todo.append(x)  # 尾部缺口(停牌股可能补不上, 如实记录)
    return todo


def fetch_one(code: str, start: str, end: str) -> pd.DataFrame:
    """抓单只退市股日线(前复权), 返回 full_daily 同构 DataFrame; 空数据返回空 df。

    akshare 对老退市股可能忽略 start_date 参数返回全历史 → 本地按 [start, end] 再过滤,
    避免把研究窗口外的行写入 full_daily。
    """
    import akshare as ak

    symbol = code.split(".")[1]
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq"
    )
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["日期"]),
            "code": code,
            "close": df["收盘"].astype(float),
            "pbMRQ": np.nan,
            "turn": df["换手率"].astype(float),
            "amount": df["成交额"].astype(float),
            "peTTM": np.nan,
            "tradestatus": "1",
            "isST": np.nan,
        }
    )
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return out[(out["date"] >= lo) & (out["date"] <= hi)]


def main() -> None:
    ap = argparse.ArgumentParser(description="退市股历史日线补抓(akshare 东财)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--limit", type=int, default=None, help="只抓前 N 只(测试)")
    ap.add_argument("--codes", default=None, help="逗号分隔 6 位代码, 只抓这些(测试)")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不抓取")
    args = ap.parse_args()

    load_config(args.config)
    cfg = _cfg()
    pause = cfg.fetch.delisted_daily.pause
    retry = cfg.fetch.delisted_daily.retry
    print_every = cfg.fetch.delisted_daily.print_every
    start = cfg.fetch.delisted_daily.start
    today = pd.Timestamp.today().normalize()

    all_delisted = delisted_mainboard()
    todo = need_backfill(all_delisted, cfg.fetch.delisted_daily.tail_gap_days)
    window = [d for d in all_delisted if d["out_date"] >= pd.Timestamp("2013-01-01")]
    print(
        f"主板退市股: 总 {len(all_delisted)}, 研究窗口内 {len(window)}, 待补 {len(todo)}",
        flush=True,
    )

    if args.codes:
        want = {c.strip() for c in args.codes.split(",")}
        todo = [d for d in todo if d["code"].split(".")[1] in want]
    if args.limit:
        todo = todo[: args.limit]

    print(f"本次抓取 {len(todo)} 只", flush=True)
    if args.dry_run:
        for d in todo:
            print(
                f"  {d['code']} {d['name']} (退市 {d['out_date'].date()})", flush=True
            )
        return

    rows: list[pd.DataFrame] = []
    n_ok = n_skip = n_err = 0
    t0 = time.time()
    for i, d in enumerate(todo, 1):
        end = min(d["out_date"], today)
        ok = False
        for attempt in range(retry + 1):
            try:
                df = fetch_one(d["code"], start, end.strftime("%Y%m%d"))
                ok = True
                break
            except Exception as e:
                if attempt < retry:
                    time.sleep(pause * (2**attempt))
                else:
                    print(
                        f"  ERR {d['code']} {d['name']}: {type(e).__name__} {str(e)[:100]}",
                        flush=True,
                    )
                    n_err += 1
        if not ok:
            continue
        if len(df) == 0:
            n_skip += 1  # 2013 前已退市等: 无数据可补
            continue
        rows.append(df)
        n_ok += 1
        if i % print_every == 0:
            if rows:
                total = write_full_daily(pd.concat(rows, ignore_index=True))
                rows = []
            el = time.time() - t0
            print(
                f"  [{i}/{len(todo)}] 已抓 {n_ok}, 跳过 {n_skip}, 失败 {n_err}, "
                f"全库行数 {total}, 耗时 {el:.0f}s",
                flush=True,
            )
        time.sleep(pause)

    if rows:
        total = write_full_daily(pd.concat(rows, ignore_index=True))
    else:
        total = None
    print(
        f"完成: 补 {n_ok}, 跳过 {n_skip} (无数据), 失败 {n_err} "
        + (f", 全库行数 {total}" if total else ""),
        flush=True,
    )


if __name__ == "__main__":
    main()
