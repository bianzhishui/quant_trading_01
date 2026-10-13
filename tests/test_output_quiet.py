# -*- coding: utf-8 -*-
"""Round 75: 运营输出降噪的测试（探测前置 / 静音 baostock / 回退汇总一行）。

判据见 docs/factor_round75_output_quiet_plan.md：
  U1 未发布只回一行   U2 baostock 打印被静音   U3 回退只汇总一行
  U4 写盘结果不变（含"今天已发布 + 昨天缺失 → 必须补昨天"）
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import quant_trading_01.data_io as data_io  # noqa: E402
import scripts.fetch_daily_incremental as fdi  # noqa: E402
import scripts.r5.daily_update as du  # noqa: E402

CODES = [f"sh.{600000 + i}" for i in range(12)]
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


class _FakeBS:
    """假 baostock：login/logout 会**真的 print**（用来验证我们把它静音了）。"""

    def __init__(self, published: set[str]):
        self.published = published
        self.probed: list[str] = []
        self.fetched: list[tuple[str, str]] = []

    def login(self):
        print("login success!")
        return type("_L", (), {"error_code": "0", "error_msg": "ok"})()

    def logout(self):
        print("logout success!")

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
            self.probed.append(start_date)
            return _RS([[start_date]] if start_date in self.published else [])
        self.fetched.append((start_date, code))
        if start_date not in self.published:
            return _RS([])
        return _RS([[start_date, code, "10.0", "1.0", "1.0", "1e6", "10.0", "1", "0"]])


def _stub(tmp: Path, pause: float = 0.0, batch: int = 5):
    class _paths:
        pass

    _paths.fundamental = tmp
    _paths.full_dir = tmp
    _paths.full_file = tmp / "_none.parquet"
    _paths.stock_basic = tmp / "_nb.parquet"

    class _inc:
        print_every = 100

    _inc.pause = pause
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
            "date": [pd.Timestamp("2026-10-09")] * len(CODES),
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


def _wire(monkeypatch, tmp: Path, bs) -> None:
    stub = _stub(tmp)
    monkeypatch.setitem(sys.modules, "baostock", bs)
    monkeypatch.setattr(fdi, "get_config", lambda: stub)
    monkeypatch.setattr(data_io, "get_config", lambda: stub)
    monkeypatch.setattr("time.sleep", lambda _s: None)


# ---------------- U1 未发布只回一行 ----------------


def test_u1_未发布只回一行且不含待补(monkeypatch, tmp_path, capsys) -> None:
    _universe(tmp_path)
    _wire(monkeypatch, tmp_path, _FakeBS(published=set()))

    rc = fdi.update_date("2026-10-13")
    out = capsys.readouterr().out
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]

    assert rc == 0
    assert len(lines) == 1, f"未发布应恰回 1 行, 实际 {len(lines)} 行:\n{out}"
    assert "待补" not in out, "未发布时不得出现'待补 N'（旧版顺序反了会误报）"
    assert "无当日行情" in out


# ---------------- U2 静音 baostock 打印 ----------------


def test_u2_baostock的login_logout打印被静音(monkeypatch, tmp_path, capsys) -> None:
    _universe(tmp_path)
    bs = _FakeBS(published=set())
    _wire(monkeypatch, tmp_path, bs)

    # 判别力：先证明这个假 bs **确实会**打印（否则"没出现"毫无意义）
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bs.login()
        bs.logout()
    assert "login success!" in buf.getvalue() and "logout success!" in buf.getvalue()

    fdi.update_date("2026-10-13")
    out = capsys.readouterr().out
    assert "login success!" not in out, "库的 login 打印必须被静音"
    assert "logout success!" not in out, "库的 logout 打印必须被静音"


# ---------------- U3 回退只汇总一行 ----------------


def test_u3_回退只汇总一行(monkeypatch, tmp_path, capsys) -> None:
    _universe(tmp_path)
    _wire(monkeypatch, tmp_path, _FakeBS(published={"2026-10-12"}))

    n = fdi.fill_days(["2026-10-10", "2026-10-11", "2026-10-12"], label="回退补洞")
    out = capsys.readouterr().out
    summary = [ln for ln in out.splitlines() if "需补" in ln]

    assert n == 1, "只应真抓 1 个交易日"
    assert len(summary) == 1, f"汇总应恰 1 行, 实际 {len(summary)}:\n{out}"
    assert "无行情" in summary[0] and "10-12" in summary[0]
    assert "10-10(六)" in summary[0] and "10-11(日)" in summary[0], "周末应标出星期"
    assert out.count("待补") == 1, "只有真抓那一天该出现一次'待补'"


# ---------------- U4 写盘结果不变（含"昨天缺失必须补"） ----------------


def test_u4_今天已发布_昨天缺失_必须补昨天(monkeypatch) -> None:
    """R73 修复的端到端回归：数据末端 10-09、昨天(10-12)漏拉、今天(10-13)已发布
    → main() 流程必须把 10-12 补上（旧代码只会抓 10-13，10-12 永久丢失）。"""
    state = {"panel": {"2026-10-09"}, "fetched": [], "marks": []}
    published = {"2026-10-12", "2026-10-13"}

    def fake_max():
        return max(state["panel"])

    def fake_update(d):
        state["fetched"].append(d)
        if d in published:
            state["panel"].add(d)
        return 0

    def fake_probe_dates(cands):
        return [d for d in cands if d in published]

    def fake_fill_days(cands, label="缺失交易日"):
        pub = fake_probe_dates(cands)
        for d in pub:
            fake_update(d)
        return len(pub)

    monkeypatch.setattr(du, "data_max_date", fake_max)
    monkeypatch.setattr(du, "update_date", fake_update)
    monkeypatch.setattr(du, "fill_days", fake_fill_days)
    monkeypatch.setattr(
        du, "_panel_dates", lambda: {pd.Timestamp(d) for d in state["panel"]}
    )
    monkeypatch.setattr(du, "target_date", lambda want=None: "2026-10-13")
    monkeypatch.setattr(du, "completeness_guard", lambda h: (True, f"假守卫 ok @{h}"))
    monkeypatch.setattr(du, "live_mark", lambda aum: state["marks"].append(aum))
    monkeypatch.setattr(du, "print_table", lambda: None)
    monkeypatch.setattr(du, "plot_live", lambda: None)
    monkeypatch.setattr(du, "_aum_list", lambda: [(600000.0, "60w")])
    monkeypatch.setattr(sys, "argv", ["daily_update.py", "2026-10-13"])

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        du.main()

    assert "2026-10-12" in state["panel"], "昨天(10-12)缺失必须被补上"
    assert state["panel"] == {"2026-10-09", "2026-10-12", "2026-10-13"}
    assert state["marks"] == [600000.0], "应基于补到的最新日 mark"
    assert state["fetched"] == ["2026-10-13", "2026-10-12"]


def test_u4_判别力自证_关掉补洞则昨天永久丢失(monkeypatch) -> None:
    """同一场景下，若 fill_missing_days 不干活（= R73 之前），10-12 会丢。"""
    state = {"panel": {"2026-10-09"}}
    published = {"2026-10-12", "2026-10-13"}

    def fake_max():
        return max(state["panel"])

    def fake_update(d):
        if d in published:
            state["panel"].add(d)
        return 0

    monkeypatch.setattr(du, "data_max_date", fake_max)
    monkeypatch.setattr(du, "update_date", fake_update)
    monkeypatch.setattr(du, "fill_days", lambda cands, label="缺失交易日": 0)  # 关掉
    monkeypatch.setattr(du, "target_date", lambda want=None: "2026-10-13")
    monkeypatch.setattr(du, "completeness_guard", lambda h: (True, "ok"))
    monkeypatch.setattr(du, "live_mark", lambda aum: None)
    monkeypatch.setattr(du, "print_table", lambda: None)
    monkeypatch.setattr(du, "plot_live", lambda: None)
    monkeypatch.setattr(du, "_aum_list", lambda: [(600000.0, "60w")])
    monkeypatch.setattr(sys, "argv", ["daily_update.py", "2026-10-13"])

    with contextlib.redirect_stdout(io.StringIO()):
        du.main()

    assert state["panel"] == {"2026-10-09", "2026-10-13"}, "关掉补洞后 10-12 必然丢失"
    assert "2026-10-12" not in state["panel"], "判据必须有判别力"
