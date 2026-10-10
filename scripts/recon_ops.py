#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""运营对账（只读）：手册 §9.1 三不变量抽查 —— R5 四账户 + P3 七账户。

① 期末净值 = 期末现金 + 期末持仓
② 期末净值 ≈ 期初净值 − 本次费用（差额 <1%）
③ 月涨幅连乘 = 期末/期初（建仓期只有 1 行时可算，多期时校验）
④ 账本 nav_history 末条 ↔ daily CSV 同日值逐位一致（跨文件交叉核对）

另附：账本 last_exec / 最新 daily 日期 / 是否**疑似**需要 step。

用法：
  .venv/bin/python scripts/recon_ops.py                       # 全部（R5 + P3）
  .venv/bin/python scripts/recon_ops.py --strat r5            # 只跑 R5
  .venv/bin/python scripts/recon_ops.py --strat p3            # 只跑 P3
  .venv/bin/python scripts/recon_ops.py --config config/custom.yaml

退出码：0 = 全部通过；1 = 有不变量未通过
只读：不写任何文件（Round 74 由 tmp/recon_ops.py 提升为正式运营脚本）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

TOL_ABS = 1.0  # ①② 绝对容差(元)：1 手取整/滑点
TOL_REL = 0.01  # ②③ 相对容差 1%
TOL_EXACT = 1e-6  # ④ 账本 ↔ daily 应逐位一致

# 策略 → (配置段名, 账户列表属性名, ledger / daily / monthly_funds 文件名模板)
SPECS: dict[str, tuple[str, str, str, str, str]] = {
    "r5": (
        "r5",
        "aum_list",
        "ledger_aum{t}.json",
        "daily_nav_aum{t}.csv",
        "monthly_funds_aum{t}.csv",
    ),
    "p3": (
        "p3",
        "aum_list",
        "ledger_p3_aum{t}.json",
        "daily_nav_p3_aum{t}.csv",
        "monthly_funds_p3_aum{t}.csv",
    ),
}


def check_one(name: str, ledger_p: Path, daily_p: Path, funds_p: Path) -> bool:
    """对账单个账户，打印明细并返回是否全部通过（四个不变量）。"""
    led = json.loads(ledger_p.read_text())
    mf = pd.read_csv(funds_p)
    dn = pd.read_csv(daily_p)
    last, first = mf.iloc[-1], mf.iloc[0]

    # ① 期末净值 = 期末现金 + 期末持仓
    lhs = float(last["post_nav"])
    rhs = float(last["期末现金"]) + float(last["期末持仓"])
    ok1 = abs(lhs - rhs) <= TOL_ABS

    # ② 期末净值 ≈ 期初净值 − 本次费用
    fee = float(last["费用"])
    exp = float(last["pre_nav"]) - fee
    ok2 = abs(lhs - exp) <= max(TOL_ABS, TOL_REL * float(last["pre_nav"]))

    # ③ 月涨幅连乘 = 期末/期初
    rs = pd.to_numeric(mf["月涨幅%"], errors="coerce").dropna() / 100.0
    if len(rs) >= 1:
        prod = float((1 + rs).prod())
        target = lhs / float(first["pre_nav"])
        ok3 = abs(prod / target - 1) <= TOL_REL
        note3 = f"{len(rs)} 期连乘 {prod:.6f} vs {target:.6f}"
    else:
        ok3, note3 = True, "仅建仓期(无月涨幅可比)"

    # ④ 账本 nav_history 末条 ↔ daily CSV 同日（应逐位一致）
    nh_date = str(led["nav_history"][-1]["date"])
    nh_nav = float(led["nav_history"][-1]["nav"])
    d = dn[dn["date"] == nh_date]
    if len(d):
        ok4 = abs(float(d.iloc[-1]["nav"]) / nh_nav - 1) <= TOL_EXACT
        note4 = (
            f"账本 {nh_nav:,.2f} vs daily {float(d.iloc[-1]['nav']):,.2f} @{nh_date}"
        )
    else:
        ok4, note4 = False, f"daily 无 {nh_date}"

    # 信息项(不作判据): 建仓行(monthly_funds)与账本净值的差
    info = ""
    if str(first["date"]) == nh_date:
        gap = float(first["post_nav"]) - nh_nav
        info = f" | 建仓行vs账本 {gap:+,.2f} 元({gap / nh_nav:+.4%},信息项)"

    flag = "✅" if all([ok1, ok2, ok3, ok4]) else "❌"
    print(
        f"{flag} {name:6s} 调仓日 {str(last['date'])} | 净值 {lhs:>13,.2f} | "
        f"现金+持仓 {rhs:>13,.2f} | 费用 {fee:>9,.2f} | 换手 {float(last['换手率%']):>6.2f}%"
    )
    print(
        f"    ①{'✅' if ok1 else '❌'} 差 {lhs - rhs:+,.2f} 元"
        f" | ②{'✅' if ok2 else '❌'} 差 {lhs - exp:+,.2f} 元"
        f" | ③{'✅' if ok3 else '❌'} {note3}"
        f" | ④{'✅' if ok4 else '❌'} {note4}{info}"
    )

    # step 待办提示 ——
    # monthly_funds 记的是"每次调仓"，daily 记的是"每个交易日"，两者末日期**本就不相等**；
    # 只有 daily 已越过"下一个信号的月末"（= 该月末之后的执行日已出现）才**疑似**需要 step。
    ls = pd.Timestamp(led["last_signal"])
    nxt_sig = (ls + pd.offsets.MonthEnd(0)) + pd.offsets.MonthEnd(1)
    if pd.Timestamp(str(dn.iloc[-1]["date"])) > nxt_sig:
        print(
            f"    ⚠️ 疑似需 step：daily 已到 {dn.iloc[-1]['date']} > 下一信号月末 "
            f"{nxt_sig.date()}（last_signal={ls.date()}，"
            f"monthly_funds 末 {mf.iloc[-1]['date']}）"
        )
    return all([ok1, ok2, ok3, ok4])


def run_strategy(strat: str, cfg) -> list[bool]:
    """对账单个策略的全部账户，返回每个账户的通过与否。"""
    key, list_attr, led_f, dly_f, fnd_f = SPECS[strat]
    outdir = Path(getattr(cfg, key).out_dir)
    aums = list(getattr(getattr(cfg, key), list_attr))
    oks: list[bool] = []
    print(f"\n=== {strat.upper()} 对账（{len(aums)} 账户）===")
    for aum in aums:
        t = f"{int(aum / 1e4)}w"
        led_p = outdir / led_f.format(t=t)
        dly_p = outdir / dly_f.format(t=t)
        fnd_p = outdir / fnd_f.format(t=t)
        missing = [p.name for p in (led_p, dly_p, fnd_p) if not p.exists()]
        if missing:
            print(f"❌ {t:6s} 缺文件: {missing}")
            oks.append(False)
            continue
        oks.append(check_one(t, led_p, dly_p, fnd_p))
    return oks


def main() -> int:
    from quant_trading_01.config import add_config_arg, get_config, load_config

    ap = argparse.ArgumentParser(description="运营对账（只读）：三/四不变量抽查")
    ap.add_argument(
        "--strat",
        choices=["all", *SPECS],
        default="all",
        help="只对账某个策略（默认全部）",
    )
    add_config_arg(ap)
    args = ap.parse_args()
    load_config(args.config)

    cfg = get_config()
    strats = list(SPECS) if args.strat == "all" else [args.strat]
    oks: list[bool] = []
    for s in strats:
        oks.extend(run_strategy(s, cfg))

    bad = sum(1 for o in oks if not o)
    print(
        f"\n{'✅ 全部通过' if bad == 0 else f'❌ {bad} 个账户未通过'}（共 {len(oks)} 个）"
    )
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
