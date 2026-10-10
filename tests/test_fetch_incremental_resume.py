# -*- coding: utf-8 -*-
"""Round 72: `fetch_daily_incremental` 限速 + 断点续传的测试。

判据见 docs/factor_round72_fetch_incremental_resume_plan.md：
  R1 限速生效   R2 断点续传   R3 合并语义不变   R4 判别力自证   R5 质量门
全部用假 baostock + tmp_path，不联网、不碰真实数据文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import quant_trading_01.data_io as data_io  # noqa: E402
import scripts.fetch_daily_incremental as fdi  # noqa: E402

CODES = [f"sh.{600000 + i}" for i in range(5)]
DATE = "2026-10-09"
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


class _BS:
    """fail_after: 前 N 只查询成功后抛'用户未登录'（模拟被限流）。"""

    def __init__(self, fail_after: int = 10**9):
        self.fail_after = fail_after
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
        if fields == "date":  # 单只探测
            return _RS([[DATE]])
        self.queries.append(code)
        if len(self.queries) > self.fail_after:
            raise RuntimeError("用户未登录")
        return _RS([[DATE, code, "10.0", "1.0", "1.0", "1e6", "10.0", "1", "0"]])


def _stub(tmp: Path, pause: float = 0.0, batch: int = 2):
    class _paths:
        pass

    _paths.fundamental = tmp
    _paths.full_dir = tmp
    _paths.full_file = tmp / "_none.parquet"
    _paths.stock_basic = tmp / "_nb.parquet"

    class _inc:
        print_every = 100

    _inc.pause = pause  # 类体内赋值会遮蔽外层同名参数, 故在类体后赋值
    _inc.stage_batch = batch

    class _fetch:
        pass

    _fetch.daily_incremental = _inc

    class _C:
        pass

    _C.paths = _paths
    _C.fetch = _fetch
    return _C


def _universe(tmp: Path) -> None:
    pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-10-08")] * len(CODES),
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


def _wire(monkeypatch, tmp: Path, bs, pause: float = 0.0, batch: int = 2) -> None:
    stub = _stub(tmp, pause=pause, batch=batch)
    monkeypatch.setitem(sys.modules, "baostock", bs)
    monkeypatch.setattr(fdi, "get_config", lambda: stub)
    monkeypatch.setattr(data_io, "get_config", lambda: stub)
    monkeypatch.setattr("time.sleep", lambda _s: None)


def test_r2_会话失效则暂存并只查剩余(monkeypatch, tmp_path) -> None:
    _universe(tmp_path)
    bs = _BS(fail_after=3)
    _wire(monkeypatch, tmp_path, bs)

    rc = fdi.update_date(DATE)
    assert rc == 3, "会话失效必须返回 3"
    st_p = tmp_path / "_stage_daily_20261009.parquet"
    assert st_p.exists(), "必须落 staging"
    st = pd.read_parquet(st_p)
    assert len(st) == 3, f"应暂存 3 只, 实际 {len(st)}"

    bs2 = _BS()
    monkeypatch.setitem(sys.modules, "baostock", bs2)
    rc2 = fdi.update_date(DATE)
    assert rc2 == 0
    assert bs2.queries == CODES[3:], f"应只查剩余 2 只, 实际 {bs2.queries}"
    assert not st_p.exists(), "完成后应清理 staging"
    df = pd.read_parquet(tmp_path / "2026.parquet")
    assert len(df[df["date"] == pd.Timestamp(DATE)]) == 5, "合并后应有 5 行"


def test_r4_判别力自证_旧写法失败即丢(monkeypatch, tmp_path) -> None:
    """同一中断场景：旧写法（纯内存 buf）续跑要重查全部，新写法只查剩余。"""
    _universe(tmp_path)
    bs = _BS(fail_after=3)
    _wire(monkeypatch, tmp_path, bs)
    assert fdi.update_date(DATE) == 3

    have = set()  # 中断时磁盘上 10-09 一行都没有（旧写法的真实处境）
    staged = set(pd.read_parquet(tmp_path / "_stage_daily_20261009.parquet")["code"])
    old_todo = [c for c in CODES if c not in have]  # 旧写法：只看 have
    new_todo = [c for c in CODES if c not in have and c not in staged]  # 新写法
    assert len(old_todo) == 5, "旧写法必然重查全部（1000 只全部作废的那种）"
    assert len(new_todo) == 2, "新写法只查剩余"
    assert len(old_todo) > len(new_todo), "判据必须有判别力"


def test_r1_请求间隔取自配置(monkeypatch, tmp_path) -> None:
    _universe(tmp_path)
    sleeps: list[float] = []
    bs = _BS()
    _wire(monkeypatch, tmp_path, bs, pause=0.37)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    fdi.update_date(DATE)
    assert sleeps and set(sleeps) == {0.37}, (
        f"间隔应全部来自配置 pause=0.37, 实际 {set(sleeps)}"
    )


def test_r1_源码不再硬编码0点1秒() -> None:
    src = (ROOT / "scripts" / "fetch_daily_incremental.py").read_text()
    assert "time.sleep(0.1)" not in src, "不得再硬编码 0.1s（会被限流）"
    assert "inc.pause" in src
