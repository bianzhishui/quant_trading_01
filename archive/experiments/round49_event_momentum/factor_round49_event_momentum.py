#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R49 短线事件动量 · E1 事件研究（预注册见 docs/factor_round49_event_momentum_plan.md）。

涨停事件后 1/2/5/10 日超额（vs 全市场等权），按可交易性分组（换手率）：
- 换手涨停: turn >= 1%(可交易)
- 缩量/一字: 0 < turn < 1%(近似不可交易, 买不进)

判据(E1): ① 涨停后 5 日均超额 > 0 且胜率 > 50%; ② 换手涨停子集 5 日超额 > 0;
         ③ 分段 2014-17/18-21/22-26 至少 2 段为正; ④ 方向反 → 否决。
用法: .venv/bin/python scripts/factor_round49_event_momentum.py [--e1]（当前只实现 E1）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from quant_trading_01.config import load_config  # noqa: E402
from quant_trading_01.data_io import load_full_daily  # noqa: E402

K_LIST = [1, 2, 5, 10]
SEGS = [
    ("2014-2017", "2014-01-01", "2017-12-31"),
    ("2018-2021", "2018-01-01", "2021-12-31"),
    ("2022-2026", "2022-01-01", "2099-12-31"),
]


def run_e1() -> None:
    print("加载数据...", flush=True)
    full = load_full_daily()  # close/turn/isST
    full["date"] = pd.to_datetime(full["date"])
    close = full.pivot(index="date", columns="code", values="close")
    turn = full.pivot(index="date", columns="code", values="turn")
    isst = full.pivot(index="date", columns="code", values="isST").astype(str) == "1"

    ret = close.pct_change()
    limit = ret >= 0.098  # 涨停事件(主板 10%)
    listed = close.notna().cumsum() >= 60  # 上市 >= 60 交易日
    ev = limit & ~isst & listed  # 事件矩阵

    # 全市场等权指数(日)
    ew_ret = ret.mean(axis=1).fillna(0)
    ew_idx = (1 + ew_ret).cumprod()

    # 事件样本收集
    n_ev = int(ev.sum().sum())
    print(f"涨停事件总数: {n_ev:,} (2014-2026, 主板非ST上市60天+)\n")
    print(
        f"{'窗口':<4}{'分组':<14}{'样本':>8}{'超额均值':>10}{'胜率':>8}{'超额中位':>10}"
    )
    rows = {}
    for k in K_LIST:
        fwd = close.shift(-k) / close - 1
        ew_fwd = ew_idx.shift(-k) / ew_idx - 1
        excess = fwd.sub(ew_fwd, axis=0)  # 每列超额
        for grp, mask in [
            ("全部", ev),
            ("换手涨停(>=1%)", ev & (turn >= 1.0)),
            ("缩量/一字(<1%)", ev & (turn > 0) & (turn < 1.0)),
        ]:
            vals = pd.Series(
                excess.to_numpy()[mask.to_numpy()]
            ).dropna()  # numpy 布尔索引: 事件级样本, 剔事件日缺数据
            m, med, win = vals.mean(), vals.median(), (vals > 0).mean()
            rows[(k, grp)] = (m, win, med)
            print(f"{k:<4}{grp:<16}{len(vals):>8,}{m:>+10.3%}{win:>8.1%}{med:>+10.3%}")

    # 判据评估
    print("\n=== E1 判据 ===")
    m5_all = rows[(5, "全部")][0]
    m5_ht = rows[(5, "换手涨停(>=1%)")][0]
    w5_all = rows[(5, "全部")][1]
    print(
        f"① 涨停后5日超额: {m5_all:+.3%} (胜率 {w5_all:.1%}) "
        f"→ {'✅ 通过' if m5_all > 0 and w5_all > 0.5 else '❌ 未通过'}"
    )
    print(
        f"② 换手涨停5日超额: {m5_ht:+.3%} → {'✅ 通过' if m5_ht > 0 else '❌ 未通过'}"
    )

    # 分段(5日, 全部事件)
    print("\n=== E1 分段(涨停后5日超额, 全部事件) ===")
    fwd5 = close.shift(-5) / close - 1
    ew_fwd5 = ew_idx.shift(-5) / ew_idx - 1
    ex5 = fwd5.sub(ew_fwd5, axis=0)
    seg_ok = 0
    for name, a, b in SEGS:
        m_ev = ev.loc[a:b].to_numpy()
        m_ex = ex5.loc[a:b].to_numpy()
        vals = pd.Series(m_ex[m_ev]).dropna()
        m = vals.mean()
        ok = m > 0
        seg_ok += int(ok)
        print(
            f"  {name}: {m:+.3%} (胜率 {(vals > 0).mean():.1%}) {'✅' if ok else '❌'}"
        )
    print(
        f"③ 分段至少2段为正: {'✅ 通过' if seg_ok >= 2 else '❌ 未通过'} ({seg_ok}/3)"
    )


def main() -> None:
    load_config(None)
    run_e1()


if __name__ == "__main__":
    main()
