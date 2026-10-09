# -*- coding: utf-8 -*-
"""Round 60: `_live_factors` 退避误判修复的单元测试。

严格按 docs/factor_round60_live_factor_backoff_plan.md v1.0 §3 判据：
  F1 语义正确（空结果不算失败；真失败才退避）
  F3 判别力自证（同一场景下旧写法**必然违规**、新写法 0 违规）
  —— 教训来自 R57-W2（写过无判别力的判据）与 R58-I5（把"判据必须有判别力"变成断言）。

本文件**只调用纯函数 + 读源码文本**，不联网、不触碰任何真实数据文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.r5.paper_live import _streak_after  # noqa: E402

THR = 50  # config.fetch.corporate_actions.empty_streak 的当前值


def _sim(fn, oks: list[bool], thr: int = THR) -> int:
    """按顺序喂入每次查询的成败，返回累计退避次数。"""
    streak, backoffs = 0, 0
    for ok in oks:
        streak, need = fn(ok, streak, thr)
        backoffs += int(need)
    return backoffs


def _old_no_event(_query_ok: bool, streak: int, thr: int) -> tuple[int, bool]:
    """Round 60 修复前的语义：查询成功但窗口内无除权事件 → got=False → 按失败计。

    （旧代码里 `got` 只由 `buf.append(...)` 置 True，即"查到事件"才算成功。）
    """
    s = streak + 1
    return (0, True) if s >= thr else (s, False)


# ---------------- F1 语义正确 ----------------


def test_f1_空结果不算失败_连续一千只也不退避() -> None:
    """9~10 月真实形态：每只都查询成功，但窗口内没有任何除权事件。"""
    assert _sim(_streak_after, [True] * 1000) == 0


def test_f1_真失败达到阈值才退避() -> None:
    assert _sim(_streak_after, [False] * (THR - 1)) == 0  # 差一次不退避
    assert _sim(_streak_after, [False] * THR) == 1  # 恰好达到阈值 → 退避 1 次
    assert _streak_after(False, THR - 1, THR) == (0, True)  # 退避后 streak 归零
    assert _streak_after(False, 0, THR) == (1, False)
    assert _streak_after(False, 10, THR) == (11, False)


def test_f1_成功打断失败连击() -> None:
    assert _streak_after(True, THR - 1, THR) == (0, False)
    # 49 失败 → 1 成功 → 49 失败：全程不退避
    assert _sim(_streak_after, [False] * 49 + [True] + [False] * 49) == 0


def test_f1_阈值连续性_不同阈值都成立() -> None:
    for thr in (1, 2, 5, 50, 500):
        assert _sim(_streak_after, [True] * (thr * 3), thr) == 0
        assert _sim(_streak_after, [False] * thr, thr) == 1
        assert _sim(_streak_after, [False] * (thr - 1), thr) == 0


# ---------------- F3 判别力自证 ----------------


def test_f3_判别力自证_旧写法必然违规() -> None:
    """同一场景（1000 只查询成功但无事件）：新语义 0 次退避，旧语义必然 >0 次。

    若这条断言在旧代码上不失败，说明判据没有判别力 —— 那才是问题。
    """
    scenario = [True] * 1000
    new_backoffs = _sim(_streak_after, scenario)
    old_backoffs = _sim(_old_no_event, scenario)
    assert new_backoffs == 0, "新语义必须 0 违规"
    assert old_backoffs > 0, "旧语义必须违规，否则本判据无判别力"
    assert old_backoffs == 1000 // THR, "旧语义应为每 50 只退避一次"


def test_f3_判别力自证_旧写法在真失败场景与新版一致() -> None:
    """反向判别力：真失败场景下两版**应当一致**（新版没有削弱真限流退避）。"""
    scenario = [False] * 260
    assert _sim(_streak_after, scenario) == _sim(_old_no_event, scenario) == 260 // THR


# ---------------- 防回归：实现确实接入了新语义 ----------------


def test_实现已接入新语义() -> None:
    src = (ROOT / "scripts" / "r5" / "paper_live.py").read_text()
    start = src.index("def _live_factors")
    # 取到"下一个顶层函数定义"为止：不能用 def _factor_panel 作为右界，
    # 它上面的 def _factor_panel_cached 会先被 index() 匹配到，导致切片为空。
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    assert "_streak_after(" in body, "_live_factors 必须用 _streak_after 判定退避"
    assert 'error_code != "0"' in body, (
        '必须显式把 error_code != "0"（如"用户未登录"）当失败'
    )
    assert "got = True" not in body, "旧语义（查到事件才算成功）必须已移除"
    assert "got = False" not in body, "旧变量 got 必须已移除"


# ---------------- 端到端接线测试（假 baostock，不联网、不碰真实数据文件） ----------------


class _FakeRS:
    """模拟 baostock ResultData：error_code='0' + next()/get_row_data()。"""

    def __init__(self, rows: list[list[str]]) -> None:
        self.error_code = "0"
        self._rows = rows
        self._i = 0

    def next(self) -> bool:
        if self._i < len(self._rows):
            self._i += 1
            return True
        return False

    def get_row_data(self) -> list[str]:
        return self._rows[self._i - 1]


class _FakeBS:
    def __init__(self, rows: list[list[str]]) -> None:
        self.rows = rows
        self.logins = 0
        self.logouts = 0
        self.queries = 0

    def login(self):
        self.logins += 1
        return type("_L", (), {"error_code": "0", "error_msg": "success"})()

    def logout(self) -> None:
        self.logouts += 1

    def query_adjust_factor(self, code, start_date, end_date):
        self.queries += 1
        return _FakeRS(self.rows)


def _cfg_stub(live_fac: Path, streak: int, backoff_s: int):
    class _paths:
        pass

    _paths.live_fac = live_fac

    class _live:
        fac_end = "2026-12-31"

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


def test_e2e_全部查询成功但无事件_只登录一次且无退避休眠(monkeypatch, tmp_path) -> None:
    """120 只、每只查询成功但窗口内无除权事件（9~10 月真实形态）。

    修复前：每 50 只触发一次退避 → 2 次 90s 休眠 + 2 次多余 logout/login。
    修复后：只登录 1 次、logout 1 次、无 90s 休眠。
    """
    import scripts.r5.paper_live as pl

    fake = _FakeBS(rows=[])  # 查询成功但没有任何事件
    monkeypatch.setitem(sys.modules, "baostock", fake)
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    stub = _cfg_stub(tmp_path / "live.parquet", streak=50, backoff_s=90)
    monkeypatch.setattr(pl, "_cfg", lambda: stub)
    monkeypatch.setattr(pl, "get_config", lambda: stub)

    held = {f"sh.{600000 + i}" for i in range(120)}
    pl._live_factors(held, "2026-09-01")

    assert fake.queries == 120, "每只持仓股都应被查询一次"
    assert fake.logins == 1, "空结果不应触发重登"
    assert fake.logouts == 1
    assert 90 not in sleeps, "空结果不应触发 90s 退避休眠（Round 60 修复点）"
    assert sleeps == [0.1] * 120, "只应有每只 0.1s 的节流"
    assert not (tmp_path / "live.parquet").exists(), "无事件时不应写缓存文件"


def test_e2e_真失败仍会退避(monkeypatch, tmp_path) -> None:
    """反向保障：查询抛异常 50 次 → 仍触发一次 90s 退避（新版没削弱真限流保护）。"""
    import scripts.r5.paper_live as pl

    class _BoomBS(_FakeBS):
        def query_adjust_factor(self, code, start_date, end_date):
            self.queries += 1
            raise RuntimeError("用户未登录")

    fake = _BoomBS(rows=[])
    monkeypatch.setitem(sys.modules, "baostock", fake)
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    stub = _cfg_stub(tmp_path / "live.parquet", streak=50, backoff_s=90)
    monkeypatch.setattr(pl, "_cfg", lambda: stub)
    monkeypatch.setattr(pl, "get_config", lambda: stub)

    pl._live_factors({f"sh.{600000 + i}" for i in range(50)}, "2026-09-01")

    assert 90 in sleeps, "连续 50 次真失败必须退避"
    assert fake.logins == 2, "退避后应重新登录"
    assert fake.logouts == 2
