#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""增量补当日行情: 对宇宙内 code 只查询指定日, 追加进 full_daily/ 年分区。

用于日常收盘后补一根日K（fetch_full_market 按 code 增量, 不会自动补已有 code 的新日期）。

设计:
- 内存攒批 + 结尾一次性按年分区原子写(只重写受影响年份, 通常仅 1 个)
- 单只探测: 数据源未发布该日则秒退
- fail-fast: "用户未登录" 直接退出(退出码3), 重跑即续
用法: python research/fetch_daily_incremental.py [2026-09-04]
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.data_io import full_daily_codes, load_full_daily, write_full_daily

DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-09-04"
FIELDS = "date,code,close,pbMRQ,turn,amount,peTTM,tradestatus,isST"
KEEP = [
    "date",
    "code",
    "close",
    "pbMRQ",
    "turn",
    "amount",
    "peTTM",
    "tradestatus",
    "isST",
]
PRINT_EVERY = 500


def main() -> None:
    import baostock as bs

    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg

    codes = sorted(full_daily_codes())
    have = set(load_full_daily(columns=["code", "date"]).query("date == @DATE")["code"])
    todo = [c for c in codes if c not in have]
    print(
        f"共 {len(codes)} 只, {DATE} 已有 {len(codes) - len(todo)}, 待补 {len(todo)}",
        flush=True,
    )
    if not todo:
        print("无需补充", flush=True)
        bs.logout()
        return
    # 单只探测: 该日数据源是否已发布(避免整市查空)
    probe = bs.query_history_k_data_plus(
        codes[0], "date", start_date=DATE, end_date=DATE, frequency="d", adjustflag="2"
    )
    if not (probe.error_code == "0" and probe.next()):
        print(f"⚠️ 数据源尚未发布 {DATE} 的行情 (单只探测为空), 跳过本轮", flush=True)
        bs.logout()
        return

    buf: list[pd.DataFrame] = []
    fail = 0
    for i, c in enumerate(todo, 1):
        try:
            rs = bs.query_history_k_data_plus(
                c,
                FIELDS,
                start_date=DATE,
                end_date=DATE,
                frequency="d",
                adjustflag="2",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if rows:
                df = pd.DataFrame(rows, columns=rs.fields)
                for col in ["close", "pbMRQ", "turn", "amount", "peTTM"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["date"] = pd.to_datetime(df["date"])
                buf.append(df[df["tradestatus"] == "1"][KEEP])
        except Exception as e:  # noqa: BLE001
            if "用户未登录" in str(e):
                print(
                    f"⚠️ baostock 会话失效, 已处理 {i - 1} 只; 稍后重跑续传", flush=True
                )
                sys.exit(3)
            fail += 1
            if fail <= 10:
                print(f"  {c} 失败: {e}", flush=True)
        if i % PRINT_EVERY == 0:
            print(f"  [{i}/{len(todo)}] 已抓 {i - fail} 只 | 失败 {fail}", flush=True)
        time.sleep(0.1)
    bs.logout()

    if not buf:
        print(f"无新数据写入 ({DATE} 仍 {len(have)} 只)", flush=True)
        return
    new = pd.concat(buf, ignore_index=True)
    big = pd.concat([load_full_daily(), new], ignore_index=True)
    big = big.drop_duplicates(subset=["date", "code"]).sort_values("date")
    total = write_full_daily(big)  # 按年分区原子写, 返回真实全量行数
    print(
        f"完成: {DATE} 现共 {total:,} 行, 失败 {fail} (按年分区原子写)",
        flush=True,
    )


if __name__ == "__main__":
    main()
