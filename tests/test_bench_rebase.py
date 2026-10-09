# -*- coding: utf-8 -*-
"""Round 64: `bench_base` 重算（分子分母同源）的测试。

判据见 docs/factor_round64_bench_base_rebase_plan.md v1.0：
  J1 同源自洽  J2 判别力自证  J3 归一化不变  J4 数据修订自愈  J5 质量门

快测用合成 bench_lv；真实面板校验挂 `slow` marker。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.r5.paper_live import _rebased_bench_level  # noqa: E402

D0 = pd.Timestamp("2026-09-01")
D1 = pd.Timestamp("2026-10-08")
OLD_BASE = 2.631265  # 账本里 09-18 冻结的值（错误口径）
LV = {D0: 2.490793, D1: 2.411063}  # 当前面板实测值


# ---------------- J1/J2 真实数字 ----------------


def test_j1_同源比值等于独立复算() -> None:
    base = _rebased_bench_level(LV, D0, OLD_BASE)
    assert base == 2.490793
    ratio = LV[D1] / base
    assert abs(ratio - 0.967990) < 1e-6, (
        f"应为 0.967990(池收益 -3.20%), 实际 {ratio:.6f}"
    )


def test_j2_判别力自证_旧基座必然偏5pp以上() -> None:
    ratio_new = LV[D1] / _rebased_bench_level(LV, D0, OLD_BASE)
    ratio_old = LV[D1] / OLD_BASE  # 旧口径：用冻结 base
    assert abs(ratio_old - 0.916313) < 1e-6, "旧口径应得 0.916313"
    assert abs(ratio_old - ratio_new) > 0.05, "两者差必须 >5pp，否则判据无判别力"


def test_j1_四账户修正后超额() -> None:
    """用真实 nav 复算修正后超额（pp）。"""
    ratio_new = LV[D1] / _rebased_bench_level(LV, D0, OLD_BASE)
    rows = {  # (build_nav, post_nav)
        "60w": (598087.91, 594897.98),
        "100w": (996749.92, 992699.87),
        "300w": (2993240.91, 2984608.65),
        "600w": (5988729.96, 5973300.51),
    }
    for tag, (b, p) in rows.items():
        exc = (p / b - ratio_new) * 100
        assert 2.5 < exc < 3.1, f"{tag} 修正后超额应约 +2.7~+2.9pp, 实际 {exc:+.2f}pp"


# ---------------- J4 数据修订自愈 ----------------


def test_j4_整体缩放对新算法无影响_对旧算法必然漂移() -> None:
    ratio_new = LV[D1] / _rebased_bench_level(LV, D0, OLD_BASE)
    ratio_old = LV[D1] / OLD_BASE
    lv2 = {k: v * 1.7 for k, v in LV.items()}  # 模拟基准路径整体平移
    ratio_new2 = lv2[D1] / _rebased_bench_level(lv2, D0, OLD_BASE)
    ratio_old2 = lv2[D1] / OLD_BASE

    assert abs(ratio_new - ratio_new2) < 1e-12, "新算法对整体缩放免疫（同源比值）"
    assert abs(ratio_old - ratio_old2) > 0.5, "旧算法必然漂移"


def test_j4_建账日缺失则回退存值() -> None:
    assert _rebased_bench_level({}, D0, OLD_BASE) == OLD_BASE
    assert _rebased_bench_level({D0: 0.0}, D0, OLD_BASE) == OLD_BASE
    assert _rebased_bench_level({D1: 1.0}, D0, OLD_BASE) == OLD_BASE


# ---------------- J3 归一化不变（真实账本，slow） ----------------


@pytest.mark.slow
def test_j3_真实面板下所有账本bench自洽() -> None:
    from scripts.r5.paper_live import _bench_levels, _load_all

    close, amount, tst, isst, ind, raw, rebs, bench, ret = _load_all()
    bl = _bench_levels(rebs, bench, ret)
    checked = 0
    for led_p in sorted((ROOT / "output" / "r5").glob("ledger_aum*.json")):
        led = json.loads(led_p.read_text())
        base = bl[pd.Timestamp(led["nav_history"][0]["date"])]
        assert abs(led["bench_base"] - base) < 1e-9, f"{led_p.name} bench_base 未重算"
        assert led["nav_history"][0]["bench"] == 1.0, "建账日归一化必须仍为 1.0"
        for h in led["nav_history"]:
            want = bl[pd.Timestamp(h["date"])] / base
            assert abs(h["bench"] - want) < 1e-9, (
                f"{led_p.name} {h['date']} bench 不自洽"
            )
        checked += 1
    assert checked >= 4, "至少应校验到 4 个 R5 账本"
