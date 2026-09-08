#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""全市场日线抓取 v3 —— 含退市股(去幸存者偏差, Round 17) + 按年分区存储。

产出 data/fundamental/full_daily/ 年分区(2012.parquet...):
date, code, close(qfq), pbMRQ, turn, amount, peTTM, tradestatus, isST。
数值列 float64, 压缩 snappy(默认), 写盘 index=False + 原子写。

宇宙: data/fundamental/stock_basic.parquet 中 type=1 且 sh.60/sz.00, **status 不限
(在市+退市都收, 修正退市股缺席的幸存者偏差)**。

容错:
- 断点续传: 已落盘 code 自动跳过, 中断重跑即续
- 会话失效("用户未登录"): fail-fast 退出(码3), 本环境 logout+login 会制造坏会话
- 看门狗: rs.next() 挂起 8 分钟无进展强制退出(码5)
- 重试: 每只 3 次(网络错误退避 2s)

用法: python research/fetch_full_market.py
"""

from __future__ import annotations

import os
import sys
import threading
import time

import pandas as pd

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.data_io import (
    full_daily_codes,
    stock_basic,
    universe_codes,
    write_full_daily,
)

FLUSH_EVERY = 100
STALL_LIMIT_S = 480  # 看门狗: 连续无进展(rs.next挂起)超过8分钟 → 强制退出由续传接管

_wd_last = time.time()


def _watchdog_start():
    """后台线程: 若主循环超过 STALL_LIMIT_S 无进展(baostock rs.next 挂起), os._exit 让续传接管。"""

    def _mon():
        while True:
            time.sleep(30)
            if time.time() - _wd_last > STALL_LIMIT_S:
                print(
                    "⚠️ 看门狗: 8分钟无进展(疑似挂起), 强制退出, 请重跑续传",
                    flush=True,
                )
                os._exit(5)

    threading.Thread(target=_mon, daemon=True).start()


def _watchdog_tick():
    global _wd_last
    _wd_last = time.time()


def fetch_one(bs, code: str, start: str, end: str) -> pd.DataFrame:
    """抓单只全部历史(退市股止于退市日, baostock 保留)。停牌日(tradestatus≠1)不入库。"""
    fields = "date,code,close,pbMRQ,turn,amount,peTTM,tradestatus,isST"
    keep = fields.split(",")
    rs = bs.query_history_k_data_plus(
        code, fields, start_date=start, end_date=end, frequency="d", adjustflag="2"
    )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"{code}: {rs.error_msg}")
    if not rows:
        return pd.DataFrame(columns=keep)
    df = pd.DataFrame(rows, columns=rs.fields)
    for c in ["close", "pbMRQ", "turn", "amount", "peTTM"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df[df["tradestatus"] == "1"][keep]


def main() -> None:
    import baostock as bs

    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    # 单会话: 全程保持登录(本环境 baostock logout 后重登的会话查询会"用户未登录")
    sb = stock_basic()
    delisted = int(
        ((sb["type"] == "1") & (sb["outDate"].notna()) & (sb["outDate"] != "")).sum()
    )
    codes = universe_codes()  # stock_basic: type=1, sh.60/sz.00, status 不限(含退市)
    print(
        f"宇宙: {len(codes)} 只 (stock_basic 权威清单, 含退市; 全类型退市 {delisted} 只)",
        flush=True,
    )

    have = full_daily_codes()
    todo = [c for c in codes if c not in have]
    print(f"已落盘 {len(have)}, 待抓 {len(todo)}", flush=True)

    # 退市股的起止: 上市日→退市日(减少无效区间查询); 在市股用全局 START/END
    # 与数据窗口 [2012-06-01, 2026-09-07] 无交集的(如 2006 年前退市)直接跳过
    sb_i = sb.set_index("code")
    buf: list[pd.DataFrame] = []
    done = 0
    _watchdog_start()
    for i, c in enumerate(todo, 1):
        start = "2012-06-01"
        end = "2026-09-07"
        if c in sb_i.index:
            ipo = sb_i.at[c, "ipoDate"]
            out_d = sb_i.at[c, "outDate"]
            if pd.notna(out_d) and str(out_d).strip():
                end = min(end, str(out_d)[:10])  # 退市股只查到退市日
            if pd.notna(ipo) and str(ipo).strip():
                start = max(start, str(ipo)[:10])
        if start >= end:
            print(f"  跳过 {c}: 与数据窗口无交集 [{start}, {end})", flush=True)
            done += 1
            _watchdog_tick()
            continue
        for attempt in range(3):
            try:
                df = fetch_one(bs, c, start, end)
                if len(df):
                    buf.append(df)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  {c} 最终失败: {e}", flush=True)
                elif "用户未登录" in str(e):
                    # 本环境 logout+login 会制造坏会话(查询挂起)。正确做法: 失败退出,
                    # 新进程按 code 断点续传(已落盘的不重抓)。
                    print(
                        f"⚠️ baostock 会话失效(首个 {c}), 已落盘 {len(have)} 只; "
                        "请稍后重跑 fetch_full_market.py 续传",
                        flush=True,
                    )
                    sys.exit(3)
                else:
                    time.sleep(2.0)
        done += 1
        _watchdog_tick()
        if done % FLUSH_EVERY == 0 or done == len(todo):
            if buf:
                new = pd.concat(buf, ignore_index=True)
                buf = []
                total_rows = write_full_daily(new)  # 按年分区合并原子写(float64+snappy)
                print(
                    f"  [{done}/{len(todo)}] 累计 {len(have) + done} 只 | "
                    f"全量 {total_rows:,} 行",
                    flush=True,
                )
    bs.logout()
    print("全市场下载完成", flush=True)


if __name__ == "__main__":
    main()
