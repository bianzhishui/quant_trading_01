#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""数据健康检查 —— 各数据文件的新鲜度/完整性, 过期时给重跑命令。

覆盖两策略(P3/R5)依赖的全部低频数据:
- full_daily 行情(每日自动)   - financial_quality 财务(季报后重跑)
- dividends 分红(分红季后重跑) - adjust_factor 复权因子(季度)
- stock_basic 宇宙清单(季度)   - raw_close_* 一次性(不提醒)

用法: .venv/bin/python scripts/data_health.py
输出: 每项 ✅正常/⚠️过期N天 → 建议命令
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config  # noqa: E402
from quant_trading_01.data_io import data_max_date_fast, load_full_daily  # noqa: E402


def _mtime_days(p: Path) -> float:
    return (dt.datetime.now() - dt.datetime.fromtimestamp(p.stat().st_mtime)).days


def _parquet_max_date(path: Path, col: str) -> pd.Timestamp | None:
    if not path.exists():
        return None
    d = pd.read_parquet(path, columns=[col])
    return pd.to_datetime(d[col]).max()


def main() -> None:
    cfg = get_config()
    today = dt.date.today()
    r2 = Path(cfg.paths.round2)
    print(f"== 数据健康检查 (今天 {today} 周{'一二三四五六日'[today.weekday()]}) ==\n")

    # 1) 行情(每日)
    mx = data_max_date_fast()
    if mx is None:
        d = load_full_daily(columns=["date"])
        mx = d["date"].max()
    lag = (today - mx.date()).days
    st = "✅" if lag <= 5 else "⚠️"
    print(
        f"{st} full_daily 行情: 最新 {mx.date()} ({lag} 天前) "
        f"{'' if lag <= 5 else '→ 每日: daily_update.py / daily_update_p3.py'}"
    )

    # 2) 质量财务(季报后重跑; P3/R5 选股只用年报 12-31 → 以年报视角检查)
    fq = r2 / "financial_quality.parquet"
    lr = _parquet_max_date(fq, "report_date")
    if lr is None:
        print("⚠️ financial_quality: 缺失 → 跑 fetch_financial_quality.py")
    else:
        d12 = pd.read_parquet(fq, columns=["report_date"])
        lr_ann = pd.to_datetime(
            d12[d12["report_date"].dt.month == 12]["report_date"]
        ).max()
        # 最新年报年份应 >= 去年(今年4/30前披露去年年报; 当前9月应已有去年年报)
        need = today.year - 1 if today.month <= 4 else today.year - 1
        stale = (
            lr_ann.year < need if lr_ann is not None and not pd.isna(lr_ann) else True
        )
        st = "⚠️" if stale else "✅"
        hint = "→ 跑 fetch_financial_quality.py(缺最新年报)" if stale else ""
        print(
            f"{st} financial_quality 财务: 最新报告期(全) {lr.date()} | "
            f"最新年报 {lr_ann.date() if lr_ann is not None and not pd.isna(lr_ann) else '缺失'} {hint}"
        )

    # 3) 分红(分红季后重跑)
    dv = r2 / "dividends.parquet"
    ld = _parquet_max_date(dv, "date")
    if ld is None:
        print("⚠️ dividends: 缺失 → 跑 fetch_dividends_backfill.py")
    else:
        age = (today - ld.date()).days
        st = "✅" if age <= 120 else "⚠️"
        if age < 0:
            extra = "(已公告未来除权日, 数据新鲜)"
        elif age > 120:
            extra = "→ 跑 fetch_dividends_backfill.py(分红季已过)"
        else:
            extra = ""
        print(
            f"{st} dividends 分红: 最新除权日 {ld.date()} ({max(age, 0)} 天前) {extra}"
        )

    # 4) 复权因子(静态截止, 季度重抓; 运营期由 step live 增量兜底)
    fe = pd.Timestamp(cfg.fetch.corporate_actions.end)
    age = (today - fe.date()).days
    st = "✅" if age <= 90 else "⚠️"
    hint = (
        "→ 跑 fetch_corporate_actions.py(超季度)"
        if age > 90
        else "(live 增量由每月 step 兜底)"
    )
    print(f"{st} adjust_factor 复权因子: 静态截止 {fe.date()} ({age} 天前) {hint}")

    # 5) 宇宙清单(季度/半年)
    sb = Path(cfg.paths.stock_basic)
    age = _mtime_days(sb) if sb.exists() else 9999
    st = "✅" if age <= 180 else "⚠️"
    hint = "→ 跑 fetch_stock_basic.py(超半年)" if age > 180 else ""
    print(f"{st} stock_basic 宇宙清单: {age:.0f} 天前更新 {hint}")

    # 6) 一次性数据(不提醒, 仅报存在)
    for name in ["raw_close_delisted", "raw_close_fallback"]:
        p = r2 / f"{name}.parquet"
        print(f"  · {name}: {'✅ 存在' if p.exists() else '⚠️ 缺失(一次性, 需补)'}")


if __name__ == "__main__":
    main()
