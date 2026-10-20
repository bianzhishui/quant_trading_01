#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""运营体检（只读）：数据完整性 / 交易日连续 / 序列健康 / 账本状态 / 对账。

用法:
  python scripts/ops_healthcheck.py                 # 全部策略（R5 + P3）
  python scripts/ops_healthcheck.py --strat r5
  python scripts/ops_healthcheck.py --verbose       # 逐账户明细
  python scripts/ops_healthcheck.py --days 90       # 交易日连续检查窗口(自然日, 默认 60)
  python scripts/ops_healthcheck.py --probe         # 用数据源核实可疑缺失日(需网络)
  python scripts/ops_healthcheck.py --config config/custom.yaml

退出码: 0 = 通过；1 = 有异常
只读: 不写任何文件。

关于内置节假日表（重要，诚实说明）:
  表里的 2026 年休市日是**从本地面板反推 + 对着节日名核实**得到的，
  因此它对"已覆盖的历史时段"没有鉴别力（数据少一天，表里也就少一天）。
  它真正的用途是**抓新增缺口**（例：2026-10-12 漏拉这种）——
  新出现的"工作日无数据且不在表里"会被判为异常。
  表只覆盖 2026；跨年检查请用 `--probe` 让数据源定性。
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import contextlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# 2026 年 A 股休市日（只列"工作日"里的；周末天然无行情）
HOLIDAYS: set[str] = {
    "2026-02-16",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-02-20",
    "2026-02-23",  # 春节
    "2026-04-06",  # 清明
    "2026-05-01",
    "2026-05-04",
    "2026-05-05",  # 劳动节
    "2026-06-19",  # 端午
    "2026-09-25",  # 中秋
    "2026-10-01",
    "2026-10-02",
    "2026-10-05",
    "2026-10-06",
    "2026-10-07",  # 国庆
}

BUILD_DAY = "2026-09-01"  # 两策略共同建仓日（用于校验 daily CSV 首行）
TOL_ROWS = 0.03  # 每日行数相对基线的容差


def _say(ok: bool, title: str, detail: str = "") -> tuple[bool, str, str]:
    print(f"  {'✅' if ok else '❌'} {title}" + (f": {detail}" if detail else ""))
    return ok, title, detail


def _panel_rows() -> pd.Series:
    """各交易日行数（只读 date 列）。"""
    from quant_trading_01.data_io import load_full_daily

    df = load_full_daily(columns=["date"])
    return pd.to_datetime(df["date"]).value_counts().sort_index()


def _missing_weekdays(lo: dt.date, hi: dt.date, have: set) -> list[str]:
    out, d = [], lo
    while d <= hi:
        s = str(d)
        if d.weekday() < 5 and s not in have and s not in HOLIDAYS:
            out.append(s)
        d += dt.timedelta(days=1)
    return out


def check_data(days: int, probe: bool) -> list[tuple[bool, str, str]]:
    res = []
    cnt = _panel_rows()
    mx = cnt.index.max().date()
    today = dt.date.today()
    res.append(
        _say(
            True,
            "最新数据日",
            f"{mx}（{len(cnt)} 个交易日有数据；今天 {today}）",
        )
    )

    recent = cnt.tail(6)
    base = int(recent.median())
    dev = max(abs(int(n) - base) / base for n in recent.values) if base else 1.0
    res.append(
        _say(
            dev <= TOL_ROWS,
            "近 6 个交易日行数",
            f"{[int(v) for v in recent.values]}（基线≈{base}，偏差 {dev:.1%} ≤ {TOL_ROWS:.0%}）",
        )
    )

    from quant_trading_01.config import get_config

    st = sorted(Path(get_config().paths.fundamental).glob("_stage_daily_*.parquet"))
    res.append(
        _say(not st, "无 staging 残留", ", ".join(p.name for p in st) if st else "")
    )

    lo = max(cnt.index.min().date(), today - dt.timedelta(days=days))
    have = {str(x.date()) for x in cnt.index}
    miss = _missing_weekdays(lo, mx, have)
    probed = ""
    if miss and probe:
        from scripts.fetch_daily_incremental import probe_dates

        real = probe_dates(miss)  # 数据源有数据 → 说明是我们漏拉（真缺口）
        probed = (
            f" | 数据源核实: {real} 有行情(真缺口)"
            if real
            else " | 数据源核实: 均无行情(节假日)"
        )
        miss = real
    res.append(
        _say(
            not miss,
            f"交易日连续（近 {days} 天）",
            f"缺失工作日 {miss}{probed}" if miss else "",
        )
    )
    return res


def _series_specs(cfg, strat: str) -> list[tuple[str, Path, str, Path, str]]:
    """(策略, 目录, daily 模板, ledger 模板, 账户标签) 列表。"""
    key = "r5" if strat == "r5" else "p3"
    outdir = Path(getattr(cfg, key).out_dir)
    aums = list(getattr(getattr(cfg, key), "aum_list"))
    pre = "" if strat == "r5" else "p3_"
    specs = []
    for aum in aums:
        t = f"{int(aum / 1e4)}w"
        specs.append(
            (
                strat.upper(),
                outdir,
                f"daily_nav_{pre}aum{t}.csv",
                f"ledger_{pre}aum{t}.json",
                t,
            )
        )
    return specs


def check_series(cfg, strat: str, latest: str, verbose: bool):
    res, bad, detail = [], [], []
    for name, outdir, dly, led_f, tag in _series_specs(cfg, strat):
        dn = pd.read_csv(outdir / dly)
        dn["date"] = pd.to_datetime(dn["date"])
        led = json.loads((outdir / led_f).read_text())
        nhd = str(led["nav_history"][-1]["date"])
        nhn = float(led["nav_history"][-1]["nav"])
        row = dn[dn["date"] == nhd]
        checks = {
            "日期单调": bool(dn["date"].is_monotonic_increasing),
            "无重复": not bool(dn["date"].duplicated().any()),
            "首行=建仓日": str(dn.iloc[0]["date"].date()) == BUILD_DAY,
            "末行=最新": str(dn.iloc[-1]["date"].date()) == latest,
            "账本↔daily": bool(len(row))
            and abs(float(row.iloc[-1]["nav"]) / nhn - 1) <= 1e-6,
        }
        fail = [k for k, v in checks.items() if not v]
        if fail:
            bad.append(f"{tag}({'/'.join(fail)})")
        if verbose:
            detail.append(
                f"{tag} {len(dn)}行 {dn.iloc[0]['date'].date()}..{dn.iloc[-1]['date'].date()}"
            )
    res.append(
        _say(
            not bad,
            f"{strat.upper()} 每日序列健康（{len(_series_specs(cfg, strat))} 账户）",
            f"异常 {bad}"
            if bad
            else ("; ".join(detail) if verbose else "单调/无重复/首行/末行/账本一致"),
        )
    )
    return res


def check_ledger(cfg, strat: str):
    key = "r5" if strat == "r5" else "p3"
    outdir = Path(getattr(cfg, key).out_dir)
    aums = list(getattr(getattr(cfg, key), "aum_list"))
    pre = "" if strat == "r5" else "p3_"
    res = []
    execs, sigs = set(), set()
    for aum in aums:
        t = f"{int(aum / 1e4)}w"
        led = json.loads((outdir / f"ledger_{pre}aum{t}.json").read_text())
        execs.add(led["last_exec"])
        sigs.add(led["last_signal"])
    nxt = (
        pd.Timestamp(sigs.copy().pop()) + pd.offsets.MonthEnd(0)
    ) + pd.offsets.MonthEnd(1)
    days_left = (nxt.date() - dt.date.today()).days
    res.append(
        _say(
            len(execs) == 1 and len(sigs) == 1,
            f"{strat.upper()} 账本状态一致",
            f"last_exec={sorted(execs)} last_signal={sorted(sigs)}"
            f"（下一调仓信号 {nxt.date()}，还有 {days_left} 天）",
        )
    )
    return res


def check_recon(cfg, strats: list[str], verbose: bool):
    import scripts.recon_ops as recon

    oks: list[bool] = []
    for s in strats:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oks.extend(recon.run_strategy(s, cfg))
        if verbose:
            print(buf.getvalue().rstrip())
    bad = sum(1 for o in oks if not o)
    return [
        _say(
            bad == 0,
            "对账（四不变量）",
            f"全部通过（共 {len(oks)} 个）"
            if bad == 0
            else f"{bad}/{len(oks)} 个未通过",
        )
    ]


def main() -> int:
    from quant_trading_01.config import add_config_arg, get_config, load_config

    ap = argparse.ArgumentParser(description="运营体检（只读）")
    ap.add_argument("--strat", choices=["all", "r5", "p3"], default="all")
    ap.add_argument("--days", type=int, default=60, help="交易日连续检查窗口(自然日)")
    ap.add_argument(
        "--probe", action="store_true", help="用数据源核实可疑缺失日(需网络)"
    )
    ap.add_argument("--verbose", action="store_true")
    add_config_arg(ap)
    args = ap.parse_args()
    load_config(args.config)
    cfg = get_config()

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"== 运营体检 {now}（只读）==")
    strats = ["r5", "p3"] if args.strat == "all" else [args.strat]
    latest = str(_panel_rows().index.max().date())

    res: list[tuple[bool, str, str]] = []
    print("\n[1] 行情数据")
    res += check_data(args.days, args.probe)
    print(
        f"\n[2] 每日序列（{'R5 四 + P3 七' if args.strat == 'all' else args.strat.upper()}）"
    )
    for s in strats:
        res += check_series(cfg, s, latest, args.verbose)
    print("\n[3] 账本状态")
    for s in strats:
        res += check_ledger(cfg, s)
    print("\n[4] 对账")
    res += check_recon(cfg, strats, args.verbose)

    bad = [r for r in res if not r[0]]
    print("\n" + "=" * 54)
    if bad:
        print(f"❌ 体检发现 {len(bad)} 项异常:")
        for _, title, detail in bad:
            print(f"   - {title}: {detail}")
        return 1
    print(f"✅ 体检通过（{len(res)} 项检查全部正常）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
