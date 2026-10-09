# -*- coding: utf-8 -*-
"""Round 62: `_live_factors` negative cache（"查询成功但无事件"也记账）的测试。

严格按 docs/factor_round62_live_factor_negative_cache_plan.md v1.0 §3 判据：
  H1 窗口覆盖正确   H2 只记成功   H3 二次调用跳过   H4 判别力自证   H5 质量门

全部用合成数据 + 假 baostock + tmp_path，不联网、不碰任何真实数据文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.r5.paper_live as pl  # noqa: E402
from scripts.r5.paper_live import _covered  # noqa: E402

SINCE = "2026-09-01"
FAC_END = "2026-12-31"


# ---------------- 工具桩 ----------------


def _q(codes, since, fac_end) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": list(codes),
            "since": pd.to_datetime([since] * len(codes)),
            "fac_end": pd.to_datetime([fac_end] * len(codes)),
        }
    )


class _FakeRS:
    def __init__(self, rows):
        self.error_code = "0"
        self._rows, self._i = rows, 0

    def next(self):
        if self._i < len(self._rows):
            self._i += 1
            return True
        return False

    def get_row_data(self):
        return self._rows[self._i - 1]


class _FakeBS:
    """rows=[] → 查询成功但无任何事件（9~10 月真实形态）。bad=抛异常的 code 集合。"""

    def __init__(self, rows=None, bad=None):
        self.rows = rows or []
        self.bad = bad or set()
        self.queries = []
        self.logins = 0

    def login(self):
        self.logins += 1
        return type("_L", (), {"error_code": "0", "error_msg": "success"})()

    def logout(self):
        pass

    def query_adjust_factor(self, code, start_date, end_date):
        self.queries.append(code)
        if code in self.bad:
            raise RuntimeError("用户未登录")
        return _FakeRS(self.rows)


def _stub_cfg(live_fac: Path, streak: int = 50, backoff_s: int = 90):
    class _paths:
        pass

    _paths.live_fac = live_fac

    class _live:
        fac_end = FAC_END

    class _ca:
        empty_streak = streak
        backoff = backoff_s

    class _fetch:
        pass

    _fetch.live = _live
    _fetch.corporate_actions = _ca

    class _C:
        pass

    _C.paths = _paths
    _C.fetch = _fetch
    return _C


# ---------------- H1 窗口覆盖语义（纯函数） ----------------


def test_h1_同窗口覆盖() -> None:
    assert _covered(_q(["a"], SINCE, FAC_END), SINCE, FAC_END) == {"a"}


def test_h1_旧窗口更宽则覆盖() -> None:
    # 旧 since 更早（窗口是超集）→ 覆盖
    assert _covered(_q(["a"], "2026-08-01", FAC_END), SINCE, FAC_END) == {"a"}
    # 旧 fac_end 更晚 → 覆盖
    assert _covered(_q(["a"], SINCE, "2027-06-30"), SINCE, FAC_END) == {"a"}


def test_h1_fac_end前移则不覆盖() -> None:
    # 旧 fac_end 更早（窗口是子集）→ 不能跳过，必须重查
    assert _covered(_q(["a"], SINCE, "2026-10-08"), SINCE, FAC_END) == set()


def test_h1_since更晚则不覆盖() -> None:
    # 旧查询从更晚的日期起 → 没覆盖 [SINCE, ...] 的前段 → 不能跳过
    assert _covered(_q(["a"], "2026-10-01", FAC_END), SINCE, FAC_END) == set()


def test_h1_空表与部分覆盖() -> None:
    assert (
        _covered(pd.DataFrame(columns=["code", "since", "fac_end"]), SINCE, FAC_END)
        == set()
    )
    q = pd.concat([_q(["a"], SINCE, FAC_END), _q(["b"], "2026-10-01", FAC_END)])
    assert _covered(q, SINCE, FAC_END) == {"a"}


# ---------------- H3 二次调用跳过（e2e） ----------------


def test_h3_二次调用只查未覆盖的(monkeypatch, tmp_path) -> None:
    fake = _FakeBS(rows=[])
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(pl, "_cfg", lambda: _stub_cfg(tmp_path / "live.parquet"))
    monkeypatch.setattr(pl, "get_config", lambda: _stub_cfg(tmp_path / "live.parquet"))

    held_a = {f"sh.{600000 + i}" for i in range(100)}
    pl._live_factors(held_a, SINCE)
    assert len(fake.queries) == 100, "首次应查询全部 100 只"
    assert (tmp_path / "adjust_factor_live_queried.parquet").exists(), (
        "应写下 negative cache"
    )

    # 第二次：同样 100 只 + 新增 20 只（模拟下一个账户）
    held_b = held_a | {f"sz.{100 + i:06d}" for i in range(20)}
    fake.queries.clear()
    pl._live_factors(held_b, SINCE)
    assert len(fake.queries) == 20, f"只应查询新增的 20 只, 实际 {len(fake.queries)}"
    assert set(fake.queries) == {f"sz.{100 + i:06d}" for i in range(20)}


def test_h3_窗口变宽则重新查询(monkeypatch, tmp_path) -> None:
    fake = _FakeBS(rows=[])
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(pl, "_cfg", lambda: _stub_cfg(tmp_path / "live.parquet"))
    monkeypatch.setattr(pl, "get_config", lambda: _stub_cfg(tmp_path / "live.parquet"))
    held = {"sh.600000"}

    pl._live_factors(held, "2026-10-01")  # 窗口较窄
    fake.queries.clear()
    pl._live_factors(held, SINCE)  # 窗口变宽（since 前移）→ 旧记录不覆盖 → 必须重查
    assert fake.queries == ["sh.600000"], (
        "fac_end 相同但 since 前移 → 旧记录不覆盖, 应重查"
    )


# ---------------- H2 只记成功（e2e） ----------------


def test_h2_失败的code不写负缓存(monkeypatch, tmp_path) -> None:
    bad = {"sh.600000", "sh.600001"}
    fake = _FakeBS(rows=[], bad=bad)
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    stub = _stub_cfg(tmp_path / "live.parquet", streak=10**9, backoff_s=0)  # 关掉退避
    monkeypatch.setattr(pl, "_cfg", lambda: stub)
    monkeypatch.setattr(pl, "get_config", lambda: stub)

    held = {f"sh.{600000 + i}" for i in range(10)}
    pl._live_factors(held, SINCE)

    q = pd.read_parquet(tmp_path / "adjust_factor_live_queried.parquet")
    got = set(q["code"])
    assert got == held - bad, "只有查询成功的 code 才应写负缓存"
    assert not (bad & got), "失败的 code 绝不能写负缓存（否则永久漏事件）"

    # 再跑一次：失败的 2 只必须被重试，成功的 8 只跳过
    fake.queries.clear()
    pl._live_factors(held, SINCE)
    assert set(fake.queries) == bad, f"应只重试失败的 2 只, 实际 {fake.queries}"


# ---------------- H4 判别力自证 ----------------


def test_h4_判别力自证_旧写法必然重复查询(monkeypatch, tmp_path) -> None:
    """同场景：旧写法（只看事件缓存 have）第二次仍查 100 只，新写法查 0 只。"""
    fake = _FakeBS(rows=[])
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(pl, "_cfg", lambda: _stub_cfg(tmp_path / "live.parquet"))
    monkeypatch.setattr(pl, "get_config", lambda: _stub_cfg(tmp_path / "live.parquet"))

    held = {f"sh.{600000 + i}" for i in range(100)}
    pl._live_factors(held, SINCE)

    have = set()  # 无事件 → 事件缓存为空（真实形态：live 缓存只有 50 条）
    q = pl._load_queried()
    covered = _covered(q, SINCE, FAC_END)
    old_todo = [c for c in sorted(held) if c not in have]  # 旧写法
    new_todo = [c for c in sorted(held) if c not in have and c not in covered]  # 新写法
    assert len(old_todo) == 100, "旧写法必然重复查询全部"
    assert len(new_todo) == 0, "新写法 0 重复"
    assert len(old_todo) > len(new_todo), "判据必须有判别力"
