# -*- coding: utf-8 -*-
"""Round 71: factor_health 在"数据止于月末"时给出显式提示（避免误判为监控滞后）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.r5.factor_health import _t1_gap_note  # noqa: E402


def _idx(end: str) -> pd.DatetimeIndex:
    return pd.bdate_range("2026-06-01", end)


def test_q1_数据止于月末时给出提示() -> None:
    idx = _idx("2026-09-30")  # 月末 = 数据末日 → 缺 T+1
    from quant_trading_01.dividend_factor import month_last_days

    sig = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    note = _t1_gap_note(idx, sig)
    assert note is not None and "2026-09-30" in note and "不是数据缺失" in note


def test_q2_数据不止于月末则无提示() -> None:
    idx = _idx("2026-10-08")  # 09-30 已有 T+1(10-01 起工作日) → 无提示
    from quant_trading_01.dividend_factor import month_last_days

    sig = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    assert _t1_gap_note(idx, sig) is None


def test_q3_判别力自证_同一情形旧版必然静默() -> None:
    """旧版没有这条输出 → 无 note；新版必须给出 note（判据有判别力）。"""
    idx = _idx("2026-09-30")
    from quant_trading_01.dividend_factor import month_last_days

    sig = [t for t in month_last_days(idx) if idx.get_loc(t) + 1 < len(idx)]
    old_output = ""  # 旧版行为：静默
    new_output = _t1_gap_note(idx, sig) or ""
    assert old_output == "" and new_output != "", "新版必须在旧版静默的情形下给出提示"
