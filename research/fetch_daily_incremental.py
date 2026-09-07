#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""增量补当日行情: 对已有 code 只查询指定日, 追加进 full_daily.parquet。

用于日常收盘后补一根日K（fetch_full_market 按 code 增量, 不会自动补已有 code 的新日期）。

v2 优化（降发热/降I/O）: 原版每 500 只就全量重写 879万行 parquet(O(n²), 7次重写);
改为**内存攒批 + 结尾一次性原子写**(读1次+写1次), 中断则主文件保持原样(守卫会拦截半成品)。
用法: python research/fetch_daily_incremental.py [2026-09-04]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "data" / "fundamental" / "full_daily.parquet"
TMP = OUT.with_suffix(".parquet.tmp")
DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-09-04"
FIELDS = "date,code,close,pbMRQ,turn,amount,peTTM,tradestatus,isST"
KEEP = ["date", "code", "close", "pbMRQ", "turn", "amount", "peTTM", "tradestatus", "isST"]
PRINT_EVERY = 500


def main() -> None:
    import baostock as bs
    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg

    d = pd.read_parquet(OUT)
    codes = sorted(d["code"].unique())
    have = set(d[d["date"] == pd.Timestamp(DATE)]["code"])
    todo = [c for c in codes if c not in have]
    print(f"共 {len(codes)} 只, {DATE} 已有 {len(codes) - len(todo)}, 待补 {len(todo)}", flush=True)
    if not todo:
        print("无需补充", flush=True)
        bs.logout()
        return
    # 单只探测: 该日数据源是否已发布(避免整市查空)
    probe = bs.query_history_k_data_plus(codes[0], "date", start_date=DATE, end_date=DATE,
                                         frequency="d", adjustflag="2")
    if not (probe.error_code == "0" and probe.next()):
        print(f"⚠️ 数据源尚未发布 {DATE} 的行情 (单只探测为空), 跳过本轮", flush=True)
        bs.logout()
        return

    buf: list[pd.DataFrame] = []
    fail = 0
    t0 = time.time()
    for i, c in enumerate(todo, 1):
        try:
            rs = bs.query_history_k_data_plus(c, FIELDS, start_date=DATE, end_date=DATE,
                                              frequency="d", adjustflag="2")
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
            fail += 1
            if fail <= 10:
                print(f"  {c} 失败: {e}", flush=True)
        if i % PRINT_EVERY == 0:
            n_now = len(have) + sum(len(b) for b in buf)
            rate = i / (time.time() - t0) * 60
            eta = (len(todo) - i) / max(rate, 1e-9) / 60
            print(f"  [{i}/{len(todo)}] 已抓 {n_now} 只 | 失败 {fail} | {rate:.0f}只/分 | 预计剩 {eta:.0f} 分钟",
                  flush=True)
        time.sleep(0.1)
    bs.logout()

    if not buf:
        print(f"无新数据写入 ({DATE} 仍 {len(have)} 只)", flush=True)
        return
    new = pd.concat(buf, ignore_index=True)
    big = pd.concat([d, new], ignore_index=True)
    big = big.drop_duplicates(subset=["date", "code"]).sort_values("date").reset_index(drop=True)
    # 原子写: 先写临时文件再替换, 中断不损坏主文件
    big.to_parquet(TMP)
    os.replace(TMP, OUT)
    n_final = int(big[big["date"] == pd.Timestamp(DATE)]["code"].nunique())
    print(f"完成: {DATE} 共 {n_final} 只, 失败 {fail} (一次性原子写, 读1次/写1次)", flush=True)


if __name__ == "__main__":
    main()
