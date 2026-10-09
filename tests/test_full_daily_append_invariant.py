# -*- coding: utf-8 -*-
"""Round 66: 全市场日线"追加不改历史"不变量护栏。

判据见 docs/factor_round66_append_invariant_plan.md：
  L1 追加不改历史   L2 幂等   L3 判别力自证   L4 真实分区门(slow)   L5 质量门

**测试只在临时目录 /tmp_path 里写**；真实数据文件只被**读取**（L4 复制一份再写副本）。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import quant_trading_01.data_io as data_io  # noqa: E402

REAL_2026 = ROOT / "data" / "fundamental" / "full_daily" / "2026.parquet"
COLS = [
    "date",
    "code",
    "close",
    "pbMRQ",
    "turn",
    "amount",
    "peTTM",
    "tradestatus",
    "isST",
]


def _stub_cfg(full_dir: Path):
    class _P:
        pass

    _P.full_dir = full_dir
    _P.full_file = full_dir / "_nonexistent.parquet"
    _P.stock_basic = full_dir / "_nonexistent_basic.parquet"

    class _C:
        pass

    _C.paths = _P
    return _C


def _frame(date_s: str, codes: list[str], close: float = 10.0) -> pd.DataFrame:
    d = pd.Timestamp(date_s)
    return pd.DataFrame(
        {
            "date": [d] * len(codes),
            "code": codes,
            "close": [close] * len(codes),
            "pbMRQ": [1.0] * len(codes),
            "turn": [1.0] * len(codes),
            "amount": [1e6] * len(codes),
            "peTTM": [10.0] * len(codes),
            "tradestatus": ["1"] * len(codes),
            "isST": ["0"] * len(codes),
        }
    )[COLS]


def _rows(df: pd.DataFrame) -> pd.DataFrame:
    """按 (date, code) 排序并只比较数值/字符串内容（忽略 datetime 精度）。"""
    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.sort_values(["date", "code"]).reset_index(drop=True)


# ---------------- L3 判别力自证（无 IO） ----------------


def test_l3_判别力自证_keep_last必然覆盖历史生产语义保留() -> None:
    prev = _frame("2026-01-05", ["sh.600000"], close=10.0)
    new = _frame("2026-01-05", ["sh.600000"], close=99.0)  # 同日同 code, 不同值

    naive = pd.concat([prev, new], ignore_index=True).drop_duplicates(
        subset=["date", "code"], keep="last"
    )
    assert float(naive["close"].iloc[0]) == 99.0, (
        "keep=last 必然用新值覆盖历史（旧写法必违规）"
    )

    prod = pd.concat([prev, new], ignore_index=True).drop_duplicates(
        subset=["date", "code"], keep="first"
    )
    assert float(prod["close"].iloc[0]) == 10.0, "生产语义必须保留历史值"

    # 该断言在旧写法上会失败 → 判据有判别力
    assert float(naive["close"].iloc[0]) != float(prod["close"].iloc[0])


# ---------------- L1 追加不改历史 ----------------


def test_l1_追加新日期不改动既有行(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(data_io, "get_config", lambda: _stub_cfg(tmp_path))
    codes = ["sh.600000", "sh.600001"]

    data_io.write_full_daily(_frame("2026-01-05", codes, close=10.0))
    before = pd.read_parquet(tmp_path / "2026.parquet")
    assert len(before) == 2

    # 追加新日期；同时**重复发一次已有的 01-05**（模拟重复抓取/手工重发）
    data_io.write_full_daily(
        pd.concat(
            [
                _frame("2026-01-06", codes, close=11.0),
                _frame("2026-01-05", codes, close=999.0),
            ],
            ignore_index=True,
        )
    )
    after = pd.read_parquet(tmp_path / "2026.parquet")
    assert len(after) == 4, "只应新增 01-06 的两行（同日重复不得新增）"

    keep = _rows(after[after["date"].dt.strftime("%Y-%m-%d") == "2026-01-05"])
    assert (keep["close"] == 10.0).all(), "既有 01-05 行不得被新值 999.0 覆盖"
    pd.testing.assert_frame_equal(keep, _rows(before))


# ---------------- L2 幂等 ----------------


def test_l2_同日重复追加幂等(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(data_io, "get_config", lambda: _stub_cfg(tmp_path))
    codes = ["sh.600000", "sh.600002"]
    day = _frame("2026-02-10", codes, close=12.5)

    data_io.write_full_daily(day)
    first = pd.read_parquet(tmp_path / "2026.parquet")
    data_io.write_full_daily(day)  # 再写一次同一天
    second = pd.read_parquet(tmp_path / "2026.parquet")

    assert len(second) == len(first)
    pd.testing.assert_frame_equal(_rows(second), _rows(first))


# ---------------- L4 真实分区门（slow，只在副本上写） ----------------


@pytest.mark.slow
def test_l4_真实分区重新追加当日不改动任何既有行(monkeypatch, tmp_path) -> None:
    if not REAL_2026.exists():
        pytest.skip("真实 2026 分区不存在")
    shutil.copy2(REAL_2026, tmp_path / "2026.parquet")  # 只读真实文件 → 写到副本
    monkeypatch.setattr(data_io, "get_config", lambda: _stub_cfg(tmp_path))

    before = pd.read_parquet(tmp_path / "2026.parquet")
    n_before = len(before)
    d08 = before[before["date"].dt.strftime("%Y-%m-%d") == "2026-10-08"].copy()
    assert len(d08) > 3000, f"10-08 行数异常: {len(d08)}"

    data_io.write_full_daily(d08)  # 把 10-08 原样重新追加一次

    after = pd.read_parquet(tmp_path / "2026.parquet")
    assert len(after) == n_before, f"行数变化: {n_before} → {len(after)}"
    older = before[before["date"] < pd.Timestamp("2026-10-08")]
    older_after = after[after["date"] < pd.Timestamp("2026-10-08")]
    assert len(older_after) == len(older)
    pd.testing.assert_frame_equal(_rows(older_after), _rows(older))
