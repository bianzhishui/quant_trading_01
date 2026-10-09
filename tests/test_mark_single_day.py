# -*- coding: utf-8 -*-
"""Round 68: `mark` 单日窗口（step 当日即数据末日）不再越界崩溃的测试。

判据见 docs/factor_round68_mark_single_day_plan.md：
  N1 单日窗口不崩   N2 正常窗口逐字不变   N3 判别力自证   N4 实现已接入   N5 质量门
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "r5" / "paper_live.py"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.r5.paper_live import _daily_move_text  # noqa: E402


# ---------------- N1/N3 单日窗口 ----------------


def test_n1_单日窗口返回占位符不崩() -> None:
    ret = pd.Series([float("nan")], index=[pd.Timestamp("2026-10-08")])
    cur, prev = _daily_move_text(ret)
    assert cur.startswith("—") and prev == "—"


def test_n3_判别力自证_旧写法必然抛IndexError() -> None:
    """同输入下旧表达式（ret.iloc[-2]）必然越界，新函数不抛 —— 判据有判别力。"""
    ret = pd.Series([float("nan")])
    with pytest.raises(IndexError):
        _ = f"{ret.iloc[-2]:+.2f}%"  # 旧写法
    cur, prev = _daily_move_text(ret)  # 新写法
    assert prev == "—" and cur.startswith("—")


def test_n1_空序列也不崩() -> None:
    cur, prev = _daily_move_text(pd.Series([], dtype=float))
    assert prev == "—" and cur.startswith("—")


# ---------------- N2 正常窗口逐字不变 ----------------


def test_n2_多日窗口与旧表达式逐字一致() -> None:
    ret = pd.Series([0.0, -0.5334, 0.1266, -0.0373])
    cur, prev = _daily_move_text(ret)
    assert cur == f"{ret.iloc[-1]:+.2f}%"
    assert prev == f"{ret.iloc[-2]:+.2f}%"


# ---------------- N4 实现已接入 ----------------


def test_n4_mark汇总已改用helper() -> None:
    src = SRC.read_text()
    body = src[src.index("def mark(") : src.index("\ndef ", src.index("def mark(") + 1)]
    assert "_daily_move_text(ret)" in body, "mark 必须用 _daily_move_text"
    assert "ret.iloc[-2]" not in body, (
        "mark 内不得再直接取 ret.iloc[-2]（单日窗口会越界）"
    )
