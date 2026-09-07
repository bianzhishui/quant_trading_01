#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""每日一键: 补当日行情(如需) → 四账户 mark → 输出建仓以来盈亏总表。

用法:
  python research/daily_update.py             # 自动判断最新交易日(以数据源为准)
  python research/daily_update.py 2026-09-07  # 指定日期补跑
  python research/daily_update.py --table     # 只读现有CSV打印总表(不抓数不mark)

总表口径: 盈亏(元) = NAV - 本金(含一次性建仓费); 盈亏率相对本金。
每日涨幅 = 当天收盘NAV / 前一日收盘NAV - 1 (数据源最新K线为准, 非系统日历)。
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUM_LIST = [(600_000, "60w"), (1_000_000, "100w"), (3_000_000, "300w"), (6_000_000, "600w")]
WD = "一二三四五六日"


def data_max_date() -> str:
    d = pd.read_parquet(ROOT / "data" / "fundamental" / "full_daily.parquet", columns=["date"])
    return str(d["date"].max().date())


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def target_date(want: str | None) -> str:
    if want:
        return want
    today = dt.date.today()
    # 候选 = 今天, 周末回退到周五
    cand = today - dt.timedelta(days=(today.weekday() >= 5) * (today.weekday() - 4))
    have = data_max_date()
    if str(cand) > have:
        return str(cand)          # 数据可能已出, 尝试抓
    return have                   # 数据源滞后 → 以数据为准


def print_table():
    print(f"\n{'账户':<7}{'本金':<11}{'最新NAV':<12}{'当日涨幅':<9}{'盈亏(元)':<13}"
          f"{'盈亏率':<9}{'建仓日NAV'}")
    for aum, tag in AUM_LIST:
        df = pd.read_csv(ROOT / "output" / f"daily_nav_aum{tag}.csv")
        last = df.iloc[-1]
        first = df.iloc[0]
        nav, ret, first_nav = last["nav"], last.get("涨幅%", float("nan")), first["nav"]
        ret_s = f"{ret:+.2f}%" if pd.notna(ret) else "-"
        print(f"{tag:<7}{aum:>11,}{nav:>12,.0f}{ret_s:>9}{nav - aum:>+13,.0f}"
              f"{(nav - aum) / aum:>+9.2%}{first_nav:>12,.0f}")


def main() -> None:
    args = [a for a in sys.argv[1:]]
    if "--table" in args:
        print_table()
        return
    want = args[0] if args and not args[0].startswith("--") else None
    tgt = target_date(want)
    have = data_max_date()
    print(f"== 目标交易日: {tgt} (数据源现有: {have}, 系统日期: {dt.date.today()} 周{WD[dt.date.today().weekday()]}) ==")
    if tgt > have:
        print(f"[1/2] 补 {tgt} 行情(全市场约20-30分钟)...")
        r = run([sys.executable, str(ROOT / "research" / "fetch_daily_incremental.py"), tgt])
        out = (r.stdout + r.stderr).strip().splitlines()
        print("\n".join(out[-4:]) if out else f"(无输出, 退出码 {r.returncode})")
        have = data_max_date()
        if tgt > have:
            print(f"⚠️ {tgt} 数据源未发布, 仍以 {have} 为准")
    else:
        print(f"[1/2] {tgt} 数据已有, 跳过抓取")
    print("[2/2] 四账户 mark...")
    for aum, tag in AUM_LIST:
        r = run([sys.executable, str(ROOT / "research" / "paper_live.py"), "mark", "--aum", str(aum)])
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
        if lines:
            print(lines[-1])  # "最新收盘 NAV ... | 当日涨幅 ... | 累计 ..."
    print_table()


if __name__ == "__main__":
    main()
