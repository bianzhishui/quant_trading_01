#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""公司行为数据抓取 v2 (弹性限流版): 复权因子 + 分红/送转。断点续传。

应对 baostock 高频查询限流: 每只间隔 PAUSE, 每 RELOGIN 只重连,
连续 EMPTY_STREAK 只无数据时判定被限流 → 长休眠后重连继续。
产出: data/round2/adjust_factor.parquet / dividends.parquet
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.data_io import universe_codes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTF = ROOT / "data" / "round2" / "adjust_factor.parquet"
OUTD = ROOT / "data" / "round2" / "dividends.parquet"
SRC = ROOT / "data" / "fundamental" / "full_daily.parquet"
PAUSE = 0.15
RELOGIN = 200
EMPTY_STREAK = 50
BACKOFF = 90


def all_codes():
    """策略宇宙(含退市股): stock_basic type=1, sh.60/sz.00, status 不限。"""
    return universe_codes()


def save(path, buf):
    if not buf:
        return
    prev = pd.read_parquet(path) if path.exists() else None
    big = (
        pd.concat([prev, pd.DataFrame(buf)], ignore_index=True)
        if prev is not None
        else pd.DataFrame(buf)
    )
    big = big.drop_duplicates().reset_index(drop=True)
    big.to_parquet(path)


def main() -> None:
    import baostock as bs

    codes = all_codes()
    have_f = set(pd.read_parquet(OUTF)["code"].unique()) if OUTF.exists() else set()
    have_d = set(pd.read_parquet(OUTD)["code"].unique()) if OUTD.exists() else set()
    todo = [c for c in codes if c not in have_f or c not in have_d]
    print(
        f"公司行为: 共 {len(codes)}, 因子已有 {len(have_f)}, 分红已有 {len(have_d)}, "
        f"待抓 {len(todo)}",
        flush=True,
    )
    bs.login()
    buf_f, buf_d, streak, done = [], [], 0, 0
    while todo:
        c = todo.pop(0)
        got = False
        for _ in range(3):
            try:
                rs = bs.query_adjust_factor(
                    code=c, start_date="2012-01-01", end_date="2026-09-03"
                )
                while rs.error_code == "0" and rs.next():
                    r = rs.get_row_data()
                    buf_f.append(
                        {"code": r[0], "date": r[1], "foreAdjustFactor": float(r[2])}
                    )
                    got = True
                rs = bs.query_dividend_data(code=c, year="")
                while rs.error_code == "0" and rs.next():
                    r = rs.get_row_data()
                    od, cash, sp = r[6], r[9], r[11]
                    if od and (cash or sp):
                        buf_d.append(
                            {
                                "code": r[0],
                                "date": od,
                                "cashBeforeTax": float(cash or 0),
                                "stocksPs": float(sp or 0),
                            }
                        )
                        got = True
                break
            except Exception:
                time.sleep(2.0)
        done += 1
        streak = streak + 1 if not got else 0
        if done % RELOGIN == 0:
            bs.logout()
            bs.login()
            print(f"  重连 [{len(todo)} 待抓]", flush=True)
        if streak >= EMPTY_STREAK:
            print(
                f"  疑似限流(连续{streak}只无数据), 休眠 {BACKOFF}s 后重连", flush=True
            )
            bs.logout()
            time.sleep(BACKOFF)
            bs.login()
            streak = 0
        if done % 200 == 0:
            save(OUTF, buf_f)
            save(OUTD, buf_d)
            print(
                f"  [{done}/{len(codes) - len(todo)}] 因子+{len(buf_f)} 分红+{len(buf_d)}"
                f" 待抓 {len(todo)}",
                flush=True,
            )
            buf_f, buf_d = [], []
        time.sleep(PAUSE)
    save(OUTF, buf_f)
    save(OUTD, buf_d)
    bs.logout()
    print("公司行为抓取完成", flush=True)


if __name__ == "__main__":
    main()
