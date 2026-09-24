#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""P3 每日一键: 补当日行情(如需) → 八账户 mark → 输出建仓以来盈亏总表。

对标 R5 scripts/r5/daily_update.py; 复用其通用逻辑(数据守卫/交易日判断/中间洞修复),
P3 特有: 八账户 mark / P3 每日图 / p3.out_dir 产物。

用法:
  python scripts/p3/daily_update_p3.py             # 自动判断最新交易日(以数据源为准)
  python scripts/p3/daily_update_p3.py 2026-09-07  # 指定日期补跑
  python scripts/p3/daily_update_p3.py --table     # 只读现有CSV打印总表(不抓数不mark)
  python scripts/p3/daily_update_p3.py --chart     # mark 后自动出 P3 每日图(daily_gains_p3.png)

总表口径: 盈亏(元) = NAV - 本金(含一次性建仓费); 每日涨幅 = 当天NAV/前日NAV - 1。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from quant_trading_01.config import get_config  # noqa: E402
from scripts.fetch_daily_incremental import update_date  # noqa: E402
from scripts.r5.daily_update import (  # noqa: E402
    backfill_missing,
    completeness_guard,
    data_max_date,
    target_date,
)
from scripts.p3.paper_live_p3 import mark as p3_mark  # noqa: E402
from scripts.p3.plot_daily_gains_p3 import plot as p3_plot  # noqa: E402


def _out_dir() -> Path:
    return Path(get_config().p3.out_dir)


def _aum_list() -> list[tuple[int, str]]:
    return [(aum, f"{int(aum / 1e4)}w") for aum in get_config().p3.aum_list]


def print_table():
    print(
        f"\n{'账户':<7}{'本金':<11}{'最新NAV':<12}{'当日涨幅':<9}{'盈亏(元)':<13}"
        f"{'盈亏率':<9}{'闲置现金':<12}{'持仓市值':<12}{'闲置率':<9}{'建仓日NAV'}"
    )
    out_dir = _out_dir()
    for aum, tag in _aum_list():
        df = pd.read_csv(out_dir / f"daily_nav_p3_aum{tag}.csv")
        last = df.iloc[-1]
        first = df.iloc[0]
        nav, ret, first_nav = last["nav"], last.get("涨幅%", float("nan")), first["nav"]
        ret_s = f"{ret:+.2f}%" if pd.notna(ret) else "-"
        cash = json.loads((out_dir / f"ledger_p3_aum{tag}.json").read_text())["cash"]
        pos = nav - cash
        print(
            f"{tag:<7}{aum:>11,}{nav:>12,.0f}{ret_s:>9}{nav - aum:>+13,.0f}"
            f"{(nav - aum) / aum:>+9.2%}{cash:>12,.0f}{pos:>12,.0f}"
            f"{cash / nav:>9.1%}{first_nav:>12,.0f}"
        )


def main() -> None:
    args = [a for a in sys.argv[1:]]
    if "--table" in args:
        print_table()
        return
    want = args[0] if args and not args[0].startswith("--") else None
    tgt = target_date(want)
    have = data_max_date()
    print(f"== P3 目标交易日: {tgt} (数据源现有: {have}) ==")
    if tgt > have:
        print(f"[1/2] 补 {tgt} 行情(全市场约20-30分钟)...")
        rc = update_date(tgt)
        if rc != 0:
            print(f"⚠️ update_date 返回 {rc}(baostock 会话失效), 请稍后重跑")
        have = data_max_date()
        if tgt > have:
            print(f"⚠️ {tgt} 数据源未发布, 仍以 {have} 为准")
            have = backfill_missing(tgt, have)
    else:
        print(f"[1/2] {tgt} 数据已有, 跳过抓取")
    ok, why = completeness_guard(have)
    if not ok:
        print(
            f"⚠️ 数据守卫未通过: {why} —— 请重跑 fetch_daily_incremental {have} 补全后再 mark; 本次不做标记"
        )
        return
    print(f"[2/2] 数据守卫 {why}")
    print("P3 八账户 mark...")
    for aum, tag in _aum_list():
        p3_mark(aum)
    print_table()
    if "--chart" in args:
        print("出图 daily_gains_p3.png + daily_nav_p3.png...")
        p3_plot()


if __name__ == "__main__":
    main()
