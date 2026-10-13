#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""每日一键: 补当日行情(如需) → 四账户 mark → 输出建仓以来盈亏总表。

用法:
  python scripts/r5/daily_update.py             # 自动判断最新交易日(以数据源为准)
  python scripts/r5/daily_update.py 2026-09-07  # 指定日期补跑
  python scripts/r5/daily_update.py --table     # 只读现有CSV打印总表(不抓数不mark)
  python scripts/r5/daily_update.py --chart     # mark 后自动出四账户每日涨幅图(daily_gains_live.png)

总表口径: 盈亏(元) = NAV - 本金(含一次性建仓费); 盈亏率相对本金。
每日涨幅 = 当天收盘NAV / 前一日收盘NAV - 1 (数据源最新K线为准, 非系统日历)。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from quant_trading_01.config import get_config  # noqa: E402
from quant_trading_01.data_io import data_max_date_fast, load_full_daily  # noqa: E402
from scripts.fetch_daily_incremental import fill_days, update_date  # noqa: E402
from scripts.r5.paper_live import mark as live_mark  # noqa: E402
from scripts.r5.plot_daily_gains import plot_live  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
WD = "一二三四五六日"


def _out_dir() -> Path:
    return Path(get_config().r5.out_dir)


def _aum_list() -> list[tuple[int, str]]:
    return [(aum, f"{int(aum / 1e4)}w") for aum in get_config().r5.aum_list]


def data_max_date() -> str:
    mx = data_max_date_fast()  # parquet 列块统计, 毫秒级不读行
    if mx is None:  # 年分区缺失/无统计 → 全读兜底
        d = load_full_daily(columns=["date"])
        mx = d["date"].max()
    return str(mx.date())


def completeness_guard(date_s: str) -> tuple[bool, str]:
    """严谨数据守卫: 今日行数 ≥ 前5个交易日最大行数×90% 且 ≥ 总code×50%。

    不跟绝对100%比(停牌股合法缺行, 100%不可达); 不跟单一昨日比(昨日本身可能坏);
    基线取前5日最大值(抗单日异常+抗停牌抖动), 再加总code下限双保险。
    返回 (是否通过, 诊断信息)。
    """
    d = load_full_daily(columns=["date", "code"])
    cnt = d.groupby("date")["code"].count()
    dates = sorted(cnt.index)
    last_s = str(dates[-1].date())
    if last_s != date_s:
        return False, f"最新交易日 {last_s} != 目标 {date_s}, 数据未更新"
    total = int(d["code"].nunique())
    today_n = int(cnt.iloc[-1])
    base = int(cnt.iloc[-6:-1].max()) if len(cnt) >= 6 else total
    detail = f"今日 {today_n} 行 | 前5日最大 {base} | 总code {total} ({today_n / base:.1%} vs 基线)"
    if today_n < base * 0.9:
        return False, f"{detail} → 低于基线90%, 疑似抓取中断残留"
    if today_n < total * 0.5:
        return False, f"{detail} → 低于总code 50%, 数据严重缺失"
    return True, f"{detail} → 通过"


def target_date(want: str | None) -> str:
    if want:
        return want
    today = dt.date.today()
    have = data_max_date()
    # 不猜交易日: 一律先试"今天"。数据源探测自动处理周末/节假日/调休/补班——
    # 今天无当日K线(非交易日或未发布)则 fetch 探测秒退, 回退到数据源最新交易日。
    return str(today) if str(today) > have else have


def backfill_missing(tgt: str, have: str) -> str:
    """补 (have, tgt) 之间缺失的交易日（目标日未发布时回退）。

    Round 75: 改为**一次探完 + 一行汇总**。旧版逐日调用 update_date，
    每天各 login/logout 并打印"共 3409 只…待补 3409"，回退 3 天刷十几行噪音，
    且把"到底要抓哪一天、要多久"淹没。判定标准与写盘结果不变。
    """
    from datetime import timedelta

    have_dt, tgt_dt = dt.date.fromisoformat(have), dt.date.fromisoformat(tgt)
    cands, nxt = [], have_dt + timedelta(days=1)
    while nxt < tgt_dt:
        cands.append(str(nxt))
        nxt += timedelta(days=1)
    if not cands:
        return have
    if fill_days(cands, label="回退补洞"):
        return data_max_date()
    return have


def _panel_dates() -> set:
    """面板中已有的全部日期（Round 73：用于逐日判断"是否真的缺"）。"""
    d = load_full_daily(columns=["date"])
    return set(pd.to_datetime(d["date"]).unique())


def fill_missing_days(start_s: str, end_s: str) -> int:
    """补 (start_s, end_s] 之间**面板里确实缺失**的自然日（Round 73）。

    为什么不复用 `backfill_missing`：它靠 `data_max_date()` 推进指针，
    当末端已经在前方时会**直接跳过去**；而且当 `have == tgt` 时它一次都不会调用，
    于是"先抓到 10-12、10-09 的洞还在"这种情形永远补不上。
    本函数逐自然日检查面板里是否真的缺（非交易日会自动秒退，代价一次 login+5 探测）。
    返回补了几日。
    """
    from datetime import timedelta

    if not start_s or not end_s or end_s <= start_s:
        return 0
    have = _panel_dates()
    d = dt.date.fromisoformat(start_s) + timedelta(days=1)
    d1 = dt.date.fromisoformat(end_s)
    cands = []
    while d <= d1:
        if pd.Timestamp(d) not in have:  # 该自然日面板里确实没有
            cands.append(str(d))
        d += timedelta(days=1)
    return fill_days(cands, label="中间洞")


def print_table():
    print(
        f"\n{'账户':<7}{'本金':<11}{'最新NAV':<12}{'当日涨幅':<9}{'盈亏(元)':<13}"
        f"{'盈亏率':<9}{'闲置现金':<12}{'持仓市值':<12}{'闲置率':<9}{'建仓日NAV'}"
    )
    out_dir = _out_dir()
    for aum, tag in _aum_list():
        df = pd.read_csv(out_dir / f"daily_nav_aum{tag}.csv")
        last = df.iloc[-1]
        first = df.iloc[0]
        nav, ret, first_nav = last["nav"], last.get("涨幅%", float("nan")), first["nav"]
        ret_s = f"{ret:+.2f}%" if pd.notna(ret) else "-"
        cash = json.loads((out_dir / f"ledger_aum{tag}.json").read_text())["cash"]
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
    print(
        f"== 目标交易日: {tgt} (数据源现有: {have}, 系统日期: {dt.date.today()} 周{WD[dt.date.today().weekday()]}) =="
    )
    have0 = have  # Round 73: 抓取前的数据末端（用于事后补中间洞）
    if tgt > have:
        print(f"[1/2] 检查目标交易日 {tgt} …")
        rc = update_date(tgt)  # 导入直调(替代 subprocess), 0=完成 3=会话失效/被限流
        if rc != 0:
            print(
                f"⚠️ update_date 返回 {rc}(会话失效/被限流), 进度已暂存; 请重跑同一条命令续传"
            )
        have = data_max_date()
    else:
        print(f"[1/2] 检查目标交易日 {tgt} … 数据已有，无需抓取")
    # Round 73: 先补「抓取前末端 → 抓取后末端」之间**确实缺失**的自然日。
    # 旧写法只靠 backfill_missing(tgt, have)；当抓取直接把 have 推到 tgt 时它零调用，
    # 中断留下的中间交易日会被永久跳过。
    if fill_missing_days(have0, data_max_date()):
        have = data_max_date()
    if have < tgt:
        print(
            f"  {tgt}（目标日）尚未发布 → 回退补历史缺失交易日"
            f"（最终以补到的最新日为准）"
        )
    have = backfill_missing(tgt, have)
    # 严谨数据完整度守卫: 中断的抓取会留下半成品(如 500/3187), 此时拒绝 mark
    ok, why = completeness_guard(have)
    if not ok:
        print(
            f"⚠️ 数据守卫未通过: {why} —— 请重跑 fetch_daily_incremental {have} 补全后再 mark; 本次不做标记"
        )
        return
    print(f"[2/2] 数据守卫 {why}")
    print("四账户 mark...")
    for aum, tag in _aum_list():
        live_mark(aum)  # 导入直调(替代 subprocess × 4)
    print_table()
    if "--chart" in args:
        print("出图 daily_gains_live.png...")
        plot_live()  # 导入直调(读最新 mark 后的 CSV)


if __name__ == "__main__":
    main()
