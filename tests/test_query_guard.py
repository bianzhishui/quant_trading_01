# -*- coding: utf-8 -*-
"""Round 77: `rs.next()` 忙等护栏（行数上限 + 墙钟超时）的测试。

判据见 docs/factor_round77_query_guard_plan.md：
  X1 死循环必被掐断   X2 判别力自证   X3 正常路径不变   X4 超时后继续
背景：实测 `daily_update --chart` 卡在"待补 3409"后 58 分钟、CPU 100%、staging 零进度 ——
      baostock 会话半断时 `next()` 持续返回 True 但不前进，旧的无界 while 空转。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import quant_trading_01.data_io as data_io  # noqa: E402
import scripts.fetch_daily_incremental as fdi  # noqa: E402

CODES = [f"sh.{600000 + i}" for i in range(6)]
DATE = "2026-10-22"
FIELDS = [
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


class _RS:
    def __init__(self, rows):
        self.error_code = "0"
        self.fields = FIELDS if rows and len(rows[0]) > 1 else ["date"]
        self._rows, self._i = rows, 0

    def next(self):
        if self._i < len(self._rows):
            self._i += 1
            return True
        return False

    def get_row_data(self):
        return self._rows[self._i - 1]


class _RSBusy:
    """next() 永远 True 且不前进 —— 模拟会话半断时的忙等。"""

    error_code = "0"
    fields = FIELDS

    def next(self):
        return True

    def get_row_data(self):
        return [DATE, "sh.600000", "10.0", "1.0", "1.0", "1e6", "10.0", "1", "0"]


class _BS:
    def __init__(self, busy: set[str] | None = None):
        self.busy = busy or set()
        self.queries: list[str] = []

    def login(self):
        return type("_L", (), {"error_code": "0", "error_msg": "ok"})()

    def logout(self):
        pass

    def query_history_k_data_plus(
        self,
        code,
        fields,
        start_date=None,
        end_date=None,
        frequency=None,
        adjustflag=None,
    ):
        if fields == "date":  # 探测
            return _RS([[DATE]])
        if code in self.busy:
            return _RSBusy()
        self.queries.append(code)
        return _RS([[DATE, code, "10.0", "1.0", "1.0", "1e6", "10.0", "1", "0"]])


def _stub(tmp: Path, max_rows: int = 10, timeout: float = 25.0):
    class _paths:
        pass

    _paths.fundamental = tmp
    _paths.full_dir = tmp
    _paths.full_file = tmp / "_none.parquet"
    _paths.stock_basic = tmp / "_nb.parquet"

    class _inc:
        print_every = 100

    _inc.pause = 0.0
    _inc.stage_batch = 5
    _inc.max_rows = max_rows
    _inc.query_timeout = timeout

    class _fetch:
        pass

    _fetch.daily_incremental = _inc

    class _C:
        pass

    _C.paths = _paths
    _C.fetch = _fetch
    return _C()


def _universe(tmp: Path) -> None:
    pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-10-21")] * len(CODES),
            "code": CODES,
            "close": [1.0] * len(CODES),
            "pbMRQ": [1.0] * len(CODES),
            "turn": [1.0] * len(CODES),
            "amount": [1e6] * len(CODES),
            "peTTM": [1.0] * len(CODES),
            "tradestatus": ["1"] * len(CODES),
            "isST": ["0"] * len(CODES),
        }
    ).to_parquet(tmp / "2026.parquet", index=False)


def _wire(
    monkeypatch, tmp: Path, bs, max_rows: int = 10, timeout: float = 25.0
) -> None:
    stub = _stub(tmp, max_rows=max_rows, timeout=timeout)
    monkeypatch.setitem(sys.modules, "baostock", bs)
    monkeypatch.setattr(fdi, "get_config", lambda: stub)
    monkeypatch.setattr(data_io, "get_config", lambda: stub)
    monkeypatch.setattr("time.sleep", lambda _s: None)


# ---------------- X1 / X4 ----------------


def test_x1_忙等被行数上限掐断且不中断整体(monkeypatch, tmp_path) -> None:
    _universe(tmp_path)
    bs = _BS(busy={CODES[0]})
    _wire(monkeypatch, tmp_path, bs, max_rows=3, timeout=10.0)

    t0 = time.time()
    rc = fdi.update_date(DATE)
    assert time.time() - t0 < 10, "必须在超时护栏内返回，不能挂住"
    assert rc == 0

    df = pd.read_parquet(tmp_path / "2026.parquet")
    got = set(df[df["date"] == pd.Timestamp(DATE)]["code"])
    assert CODES[0] not in got, "忙等那一只应被跳过"
    assert len(got) == len(CODES) - 1, "其余 code 必须照常入库（X4: 不中断整体）"


def test_x1_墙钟超时也能掐断(monkeypatch, tmp_path) -> None:
    """行数上限设很大时，靠 SIGALRM 墙钟超时兜底。"""
    _universe(tmp_path)
    _wire(monkeypatch, tmp_path, _BS(busy={CODES[0]}), max_rows=10**9, timeout=0.3)

    t0 = time.time()
    rc = fdi.update_date(DATE)
    dt = time.time() - t0
    assert rc == 0
    assert dt < 5, f"应在 ~0.3s 后返回，实际 {dt:.1f}s"
    df = pd.read_parquet(tmp_path / "2026.parquet")
    got = set(df[df["date"] == pd.Timestamp(DATE)]["code"])
    assert CODES[0] not in got and len(got) == len(CODES) - 1


# ---------------- X2 判别力 ----------------


def test_x2_判别力自证_无界循环确实会跑飞() -> None:
    """旧写法 `while rs.error_code == '0' and rs.next()` 在同输入下无限跑 —— 这就是 100% CPU 卡死。"""
    rs = _RSBusy()
    n = 0
    while rs.error_code == "0" and rs.next():  # 旧的无界写法
        n += 1
        if n > 1000:
            break
    assert n > 1000, "旧写法必然超过任何合理行数上限"


# ---------------- X3 正常路径不变 ----------------


def test_x3_正常单选返回仍然成功(monkeypatch, tmp_path) -> None:
    _universe(tmp_path)
    _wire(monkeypatch, tmp_path, _BS(), max_rows=10, timeout=10.0)

    rc = fdi.update_date(DATE)
    assert rc == 0
    df = pd.read_parquet(tmp_path / "2026.parquet")
    got = set(df[df["date"] == pd.Timestamp(DATE)]["code"])
    assert got == set(CODES), "正常路径必须全部入库"
    assert not (tmp_path / "_stage_daily_20261022.parquet").exists(), (
        "完成后清理 staging"
    )
