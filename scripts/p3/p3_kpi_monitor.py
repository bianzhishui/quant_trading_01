#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""P3 退役 KPI 监控（观察期**只读**工具；阈值冻结在 docs/p3_observation_protocol.md）

三条 KPI（任一为 🔴 且持续 → 触发"降仓/退役"复评；阈值**不得事后调整**）：
  A 策略超额: 滚动 12 个月超额(P3-A1 等权 hold − 全市场等权 C) ≤ 0
  B 候选池:   近 3 个信号月 A1 池规模中位 < 20 只
  C 实际落地: 生产 600万 滚动 12 个月收益 < −20% 或当前回撤 < −60%

**只读**：不写任何文件、不动账本、不改参数。默认跑市场部分（约 3 分钟），`--no-market` 秒级。
用法: .venv/bin/python scripts/p3/p3_kpi_monitor.py [--no-market]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

ROLL = 252  # 滚动窗口(交易日) ≈ 12 个月
SUB_PRICE, N_YEARS, EW_COST, KEEP = (3.0, 4.0), 3, 0.0015, 0.70


def light(ok: bool, label: str, value: str) -> str:
    return f"  {label:<34}{'🟢 通过' if ok else '🔴 触发' if ok is False else '⚪ 样本不足'}   {value}"


def kpi_market() -> None:
    from quant_trading_01.config import load_config
    from scripts import factor_round41_low_price as r41

    load_config(None)
    data = r41.load_data()
    ret = r41.ret_matrix(data["close"], data["out_date"], "zero")
    _, B, C, _, _ = r41.build_sets(
        data, None, sub_price=SUB_PRICE, n_years=N_YEARS, low_vol_keep=KEEP
    )
    a1 = r41.ew_nav(ret, B, EW_COST, empty_mode="hold")
    mkt = r41.ew_nav(ret, C, EW_COST)
    if len(a1) < ROLL:
        print(
            light(None, "A 滚动 12 个月超额(A1 − C)", f"样本不足（{len(a1)} 交易日）")
        )
    else:
        ex = (a1.iloc[-1] / a1.iloc[-ROLL] - 1) - (mkt.iloc[-1] / mkt.iloc[-ROLL] - 1)
        print(
            light(
                ex > 0,
                "A 滚动 12 个月超额(A1 − C)",
                f"{ex:+.2%}  (A1 {a1.iloc[-1] / a1.iloc[-ROLL] - 1:+.2%} / C {mkt.iloc[-1] / mkt.iloc[-ROLL] - 1:+.2%})",
            )
        )
    recent = sorted(B)[-3:]
    sizes = [len(B[d]) for d in recent]
    med = float(np.median(sizes))
    print(
        light(
            med >= 20,
            "B 近 3 信号月 A1 池规模中位",
            f"{med:.0f} 只  ({', '.join(f'{d.date()}={n}' for d, n in zip(recent, sizes))})",
        )
    )
    _, B0, _, _, _ = r41.build_sets(
        data, None, sub_price=SUB_PRICE, n_years=N_YEARS, low_vol_keep=None
    )
    print(
        f"  （参考）最新信号 {sorted(B)[-1].date()}: P0 池 {len(B0[sorted(B0)[-1]])} 只 / "
        f"A1 池 {len(B[sorted(B)[-1]])} 只"
    )


def kpi_ledger() -> None:
    p = Path("output/p3/daily_nav_p3_aum600w.csv")
    if not p.exists():
        print(
            light(
                None,
                "C 生产 600万 滚动 12 个月",
                f"缺少 {p}（先跑 daily_update_p3.py）",
            )
        )
        return
    d = pd.read_csv(p)
    d.columns = [c.strip() for c in d.columns]
    nav = d.set_index(pd.to_datetime(d["date"]))["nav"].astype(float).dropna()
    n = min(ROLL, len(nav) - 1)
    r = nav.iloc[-1] / nav.iloc[-1 - n] - 1 if n > 0 else np.nan
    dd = nav.iloc[-1] / nav.cummax().iloc[-1] - 1
    ok = (n >= ROLL) and (r >= -0.20) and (dd >= -0.60)
    note = "" if n >= ROLL else f"样本不足（{n} 交易日, 未满 12 个月 → 只报告不判定）"
    print(
        light(
            ok if n >= ROLL else None,
            "C 生产 600万 滚动 12 个月/回撤",
            f"滚动收益 {r:+.2%} | 当前回撤 {dd:+.2%}  {note}",
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="P3 退役 KPI 监控（只读）")
    ap.add_argument(
        "--no-market", action="store_true", help="跳过市场部分（秒级, 只读账本）"
    )
    a = ap.parse_args()
    print(
        "== P3 退役 KPI 监控（观察期, 只读）== 阈值见 docs/p3_observation_protocol.md"
    )
    kpi_ledger()
    if not a.no_market:
        kpi_market()
    print("\n判定规则: 任一 KPI 连续 12 个月为 🔴 → 触发降仓/退役复评（需用户批准）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
