#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 53: A1 低波60 在 P3 八账户的份额级落地验证（1 手约束 × 真实成本）—— 按 plan §2/§3。

复用生产同款 PaperPortfolio + scenario_ytd_p3 份额级回放（不重实现除权/阻塞逻辑）:
  S0 = 现冻结 P3（不截断）; S1 = 低波60 池内升序取前 70%（= R51 A1 口径, NaN 记最差）
窗口: 主 2021-01-04→2026-09-28（R51/R52 验证段）; 稳健性 全样本 2014-02-10→2026-09-28
输出: 每账户 × 变体 × 窗口的 年化/回撤/实际持仓/现金占比/累计费用/买不起1手占比 + 判定
用法: uv run python scripts/factor_round53_p3_a1_share_level.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from quant_trading_01.config import get_config, load_config  # noqa: E402
from quant_trading_01.dividend_factor import metrics  # noqa: E402
from scripts.factor_round41_low_price import load_data as load_data_p3  # noqa: E402
from scripts.p3.scenario_ytd_p3 import run_scenario_p3  # noqa: E402

KEEP = 0.70
HOLD_MIN = 30  # §3 分散度下限
HOLD_RATIO = 0.70  # §3 实际持仓 ≥ 目标 70%


def make_target_fn(vol: pd.DataFrame):
    """低波截断: 池内 vol60 升序取前 70%（NaN 记最差）。"""

    def fn(T: pd.Timestamp, S: set) -> set:
        if not S:
            return set()
        v = (
            vol.loc[T]
            .reindex(sorted(S))
            .replace([np.inf, -np.inf], np.nan)
            .fillna(np.inf)
        )
        n = max(int(np.ceil(len(v) * KEEP)), 1)
        return set(v.sort_values(ascending=True).index[:n])

    return fn


def summarize(nav: pd.Series, rows: list, aum: float) -> dict:
    m = metrics(nav / nav.iloc[0])  # nav 以 aum 起 → 必须先归一化(否则年化失真)
    d = pd.DataFrame(rows)
    tgt = float(d["n_target"].mean())
    hold = float(d["n_hold"].mean())
    short = float(d["n_1lot_short"].sum() / max(d["n_target"].sum(), 1))
    return {
        "年化": m["年化"],
        "回撤": m["最大回撤"],
        "夏普": m["夏普"],
        "累计": float(nav.iloc[-1] / nav.iloc[0] - 1),
        "目标只数": tgt,
        "实际持仓": hold,
        "持仓率": hold / tgt if tgt else np.nan,
        "未持有": float(d["n_fail"].mean()),
        "买不起1手占比": short,
        "现金占比": float((d["cash"] / d["post_nav"]).mean()),
        "累计费用%": float(d["fee"].sum() / aum),
        "调仓次数": int(len(d)),
    }


def main() -> None:
    load_config(None)
    t0 = time.time()
    print("== Round 53: A1 低波60 份额级八账户落地验证 ==", flush=True)

    aums = list(get_config().p3.aum_list)
    print(f"账户 {len(aums)} 个: {[int(a / 1e4) for a in aums]} 万", flush=True)

    data = load_data_p3()
    close = data["close"]
    vol = close.pct_change().rolling(60).std()
    fn = make_target_fn(vol)
    print(f"vol60 面板就绪 {time.time() - t0:.0f}s", flush=True)

    windows = [
        ("主 2021-01-04→2026-09-28", "2021-01-04", "2026-09-28"),
        ("全样本 2014-02-10→2026-09-28", "2014-02-10", "2026-09-28"),
    ]
    out = {}
    for wname, ws, we in windows:
        for vname, tfn in (("S0 现冻结", None), ("S1 A1低波60", fn)):
            detail: list = []
            navs = run_scenario_p3(
                ws, we, verbose=False, aums=aums, target_fn=tfn, detail=detail
            )
            for aum in aums:
                tag = f"aum{int(aum / 1e4)}w"
                rows = [r for r in detail if r["aum"] == aum]
                out[(wname, vname, tag)] = summarize(navs[tag], rows, aum)
            print(f"  [{wname}] {vname} 完成 ({time.time() - t0:.0f}s)", flush=True)

    for wname, _, _ in windows:
        print(f"\n=== {wname}（份额级, 15bp, 阻塞 on） ===")
        print(
            "  账户 | 变体 |    年化 |   回撤 | 夏普 |  目标/实际 | 持仓率 | 买不起1手% | "
            "现金% | 费用% |  年化差 | 回撤差"
        )
        verdict = {}
        for aum in aums:
            tag = f"aum{int(aum / 1e4)}w"
            r0 = out[(wname, "S0 现冻结", tag)]
            r1 = out[(wname, "S1 A1低波60", tag)]
            d_ann = r1["年化"] - r0["年化"]
            d_dd = r1["回撤"] - r0["回撤"]  # 正 = 更浅(改善)
            for vname, r in (("S0", r0), ("S1", r1)):
                print(
                    f"  {tag:>8s} | {vname} | {r['年化']:+7.2%} | {r['回撤']:+6.2%} | "
                    f"{r['夏普']:.2f} | {r['目标只数']:4.1f}/{r['实际持仓']:4.1f} | "
                    f"{r['持仓率']:5.1%} | {r['买不起1手占比']:9.1%} | "
                    f"{r['现金占比']:5.1%} | {r['累计费用%']:5.2%} | "
                    f"{d_ann:+7.2%} | {d_dd:+6.2%}"
                )
            ok = (
                d_ann >= -0.005
                and d_dd >= 0
                and r1["实际持仓"] >= HOLD_MIN
                and r1["持仓率"] >= HOLD_RATIO
            )
            verdict[tag] = ok
        usable = [t for t in verdict if verdict[t]]
        print(
            f"  → A1 可用账户: {usable if usable else '无'}"
            f" | 不可用: {[t for t in verdict if not verdict[t]]}"
        )
        if usable:
            first = min(int(t[3:-1]) for t in usable)
            print(f"  → A1 可用门槛规模: {first}万（及以上满足 §3 三条）")

    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
