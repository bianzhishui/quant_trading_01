# -*- coding: utf-8 -*-
"""Round 78: baostock 结果集安全迭代（`bs_utils.fetch_rows`）的测试。

判据见 docs/factor_round78_bs_iter_guard_plan.md：
  Y1 忙等必被掐断   Y2 判别力自证   Y3 正常路径零变化 + 全仓无裸循环
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_01.bs_utils import (  # noqa: E402
    BaostockQueryError,
    QueryTimeout,
    QueryTooManyRows,
    fetch_rows,
)


class _RS:
    """可配置假结果集。"""

    def __init__(self, rows, busy=False, error_code="0"):
        self.rows = rows
        self.busy = busy
        self.error_code = error_code
        self.error_msg = "boom" if error_code != "0" else ""
        self._i = 0

    def next(self):
        if self.busy:  # 会话半断: 永远 True 但不前进
            return True
        if self._i < len(self.rows):
            self._i += 1
            return True
        return False

    def get_row_data(self):
        return self.rows[self._i - 1] if not self.busy else ["x"]


# ---------------- Y1 忙等必被掐断 ----------------


def test_y1_行数上限掐断忙等() -> None:
    rs = _RS([], busy=True)
    t0 = time.time()
    with pytest.raises(QueryTooManyRows):
        fetch_rows(rs, max_rows=5, timeout_s=30.0)
    assert time.time() - t0 < 5, "必须靠行数上限立即掐断，而不是等超时"


def test_y1_墙钟超时掐断忙等() -> None:
    rs = _RS([], busy=True)
    t0 = time.time()
    with pytest.raises(QueryTimeout):
        fetch_rows(rs, max_rows=10**9, timeout_s=0.3)
    dt = time.time() - t0
    assert dt < 5, f"应在 ~0.3s 后被超时打断，实际 {dt:.1f}s"


# ---------------- Y2 判别力 ----------------


def test_y2_判别力自证_裸循环会跑飞() -> None:
    """旧的裸 while 在同输入下无限循环 —— 这正是 100% CPU 卡死的成因。"""
    rs = _RS([], busy=True)
    n = 0
    while rs.error_code == "0" and rs.next():  # 旧写法
        n += 1
        if n > 1000:
            break
    assert n > 1000, "裸循环必然超过任何合理行数上限"


# ---------------- Y3 正常路径零变化 ----------------


def test_y3_正常路径与裸循环逐元素相同() -> None:
    data = [["2026-10-22", "sh.600000", "10.0"], ["2026-10-22", "sh.600004", "7.7"]]
    got = fetch_rows(_RS(data), max_rows=100, timeout_s=5.0)

    ref_rs = _RS(data)
    ref = []
    while ref_rs.error_code == "0" and ref_rs.next():
        ref.append(ref_rs.get_row_data())
    assert got == ref


def test_y3_错误码非零仍抛异常() -> None:
    rs = _RS([], error_code="10001011")
    with pytest.raises(BaostockQueryError):
        fetch_rows(rs, max_rows=100, timeout_s=5.0)


def test_y3_空结果返回空列表() -> None:
    assert fetch_rows(_RS([]), max_rows=10, timeout_s=5.0) == []


def test_y3_timeout为零则不设超时() -> None:
    data = [["a"], ["b"]]
    assert fetch_rows(_RS(data), max_rows=10, timeout_s=0) == data


# ---------------- Y3 全仓无裸循环（回归护栏） ----------------

# 只在"代码行"（行首就是 while）里找裸循环；注释/docstring 里的说明文字不算
BARE = re.compile(r"^\s*while\s+.*rs\.next\(\s*\)")
# Round 79: 白名单清空 —— 只剩 bs_utils 自己的**文档**里举例说明旧写法
PROTECTED = {
    "src/quant_trading_01/bs_utils.py",  # 文档里举例说明旧写法
}


def test_y3_全仓不再有裸循环() -> None:
    offenders = []
    files = list((ROOT / "scripts").rglob("*.py")) + [
        ROOT / "src" / "quant_trading_01" / "data_loader.py"
    ]
    for p in files:
        rel = str(p.relative_to(ROOT))
        if rel in PROTECTED:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if BARE.search(line):
                offenders.append(f"{rel}:{i}")
    assert offenders == [], f"仍有裸 rs.next() 循环: {offenders}"


# ---------------- Y4 P0 路径：_live_factors 接入护栏、超时不中断 ----------------

import scripts.r5.paper_live as pl  # noqa: E402


class _FakeBS:
    def login(self):
        return type("_L", (), {"error_code": "0", "error_msg": "ok"})()

    def logout(self):
        pass

    def query_adjust_factor(self, **kw):
        return _RS(
            [], busy=False
        )  # error_code=0, 正常空结果（真实 fetch_rows 会被替换）


def _stub_cfg(tmp: Path):
    class _paths:
        pass

    _paths.live_fac = str(tmp / "adjust_factor_live.parquet")

    class _live:
        pass

    _live.fac_end = "2026-10-22"

    class _ca:
        empty_streak = 999
        backoff = 1.0

    class _fetch:
        pass

    _fetch.live = _live
    _fetch.corporate_actions = _ca

    class _C:
        pass

    _C.paths = _paths
    _C.fetch = _fetch
    return _C()


def test_y4_live_factors单只超时被吞掉并继续(monkeypatch, tmp_path) -> None:
    """P0：`_live_factors` 里某只查询超时 → 记失败、继续下一只，不中断整个 step。"""
    cfg = _stub_cfg(tmp_path)
    monkeypatch.setattr(pl, "get_config", lambda: cfg)
    monkeypatch.setitem(sys.modules, "baostock", _FakeBS())
    monkeypatch.setattr("time.sleep", lambda _s: None)

    calls = []

    def fake_rows(rs, *, max_rows, timeout_s):
        calls.append((max_rows, timeout_s))
        raise QueryTimeout("fake")

    monkeypatch.setattr(pl, "fetch_rows", fake_rows)

    pl._live_factors({"sh.600000", "sh.600004"}, "2026-10-01")  # 不应抛异常

    assert calls, "必须走 fetch_rows（安全迭代器）"
    assert all(m == 200 and t == 20.0 for m, t in calls), f"护栏参数异常: {set(calls)}"
    assert len(calls) == 6, f"2 只 × 3 次重试 = 6 次，实际 {len(calls)}"
    assert not Path(cfg.paths.live_fac).exists(), "全部失败时不该写出 live 因子文件"


def test_y4_live_factors源码确实用fetch_rows() -> None:
    src = (ROOT / "scripts" / "r5" / "paper_live.py").read_text()
    body = src[
        src.index("def _live_factors(") : src.index(
            "\ndef ", src.index("def _live_factors(") + 1
        )
    ]
    assert "fetch_rows(rs" in body, "P0 必须用安全迭代器"
    assert "while rs.next()" not in body, "P0 不得再有裸循环"


# ---------------- Z1 R79: 最后两处也迁完了 ----------------


def test_z1_补完的两处调用点已用fetch_rows() -> None:
    for rel in ["scripts/fetch_minute_5m.py", "scripts/fetch_full_market.py"]:
        src = (ROOT / rel).read_text()
        assert "fetch_rows(" in src, f"{rel} 必须用 fetch_rows"
        assert not re.search(r"^\s*while\s+.*rs\.next\(\s*\)", src, re.M), (
            f"{rel} 不得再有裸 rs.next() 循环"
        )


def test_z2_白名单只剩文档文件() -> None:
    assert PROTECTED == {"src/quant_trading_01/bs_utils.py"}, (
        f"白名单应只剩 bs_utils(文档举例)，实际 {PROTECTED}"
    )
