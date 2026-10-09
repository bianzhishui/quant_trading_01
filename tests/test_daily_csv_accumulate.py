# -*- coding: utf-8 -*-
"""Round 69: 每日净值 CSV 累积写（step 后不丢历史）的测试。

判据见 docs/factor_round69_daily_csv_accumulate_plan.md：
  O1 累积不丢历史   O2 幂等   O3 判别力自证   O4 P3 单日窗口已修   O6 质量门
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.r5.paper_live import _write_daily_nav  # noqa: E402

P3_SRC = ROOT / "scripts" / "p3" / "paper_live_p3.py"


def _df(dates: list[str], navs: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "nav": navs, "涨幅%": [None] * len(dates)})


def test_o1_累积不丢历史且旧行逐位不变(tmp_path) -> None:
    out = tmp_path / "daily_nav_aum600w.csv"
    _write_daily_nav(
        out, _df(["2026-09-01", "2026-09-02", "2026-09-30"], [100.0, 101.0, 99.0])
    )
    before = pd.read_csv(out)

    _write_daily_nav(out, _df(["2026-10-08"], [98.0]))  # 新一段窗口(step 后)
    after = pd.read_csv(out)

    assert len(after) == 4, f"应累积为 4 行, 实际 {len(after)}"
    old = after[after["date"] <= "2026-09-30"].reset_index(drop=True)
    pd.testing.assert_frame_equal(old, before, check_dtype=False)


def test_o2_幂等(tmp_path) -> None:
    out = tmp_path / "t.csv"
    _write_daily_nav(out, _df(["2026-09-30"], [99.0]))
    _write_daily_nav(out, _df(["2026-10-08"], [98.0]))
    a = pd.read_csv(out)
    _write_daily_nav(out, _df(["2026-10-08"], [98.0]))  # 重复 mark 同一天
    b = pd.read_csv(out)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


def test_o3_判别力自证_旧写法覆盖必然丢历史(tmp_path) -> None:
    """旧写法 = 直接 to_csv 覆盖 → 只剩新窗口行数；新写法累积。"""
    out = tmp_path / "old.csv"
    _df(["2026-09-01", "2026-09-02", "2026-09-30"], [100.0, 101.0, 99.0]).to_csv(
        out, index=False
    )
    _df(["2026-10-08"], [98.0]).to_csv(out, index=False)  # 旧写法
    n_old = len(pd.read_csv(out))
    assert n_old == 1, "旧写法必然只剩新窗口(实测 22 行 → 2 行)"

    out2 = tmp_path / "new.csv"
    _write_daily_nav(
        out2, _df(["2026-09-01", "2026-09-02", "2026-09-30"], [100.0, 101.0, 99.0])
    )
    _write_daily_nav(out2, _df(["2026-10-08"], [98.0]))
    n_new = len(pd.read_csv(out2))
    assert n_new == 4
    assert n_new > n_old, "判据必须有判别力"


def test_o4_p3单日窗口已修() -> None:
    src = P3_SRC.read_text()
    body = src[src.index("def mark(") : src.index("\ndef ", src.index("def mark(") + 1)]
    assert "_daily_move_text(" in body, "P3 mark 必须用 _daily_move_text"
    assert "nav.iloc[-2]" not in body, (
        "P3 mark 不得再直接取 nav.iloc[-2]（单日窗口越界）"
    )
    assert "_write_daily_nav(" in body, "P3 mark 必须累积写"
