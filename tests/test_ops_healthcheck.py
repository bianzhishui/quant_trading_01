# -*- coding: utf-8 -*-
"""Round 76: 运营体检脚本（scripts/ops_healthcheck.py）的测试。

判据见 docs/factor_round76_ops_healthcheck_plan.md：
  W2 缺工作日必被抓(含判别力)   W3 staging 残留被抓   W4 序列异常被抓(含判别力)   W5 只读
全部在 tmp_path 造假数据，不碰真实产物。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import quant_trading_01.config as config_mod  # noqa: E402
import quant_trading_01.data_io as data_io  # noqa: E402
import scripts.ops_healthcheck as oh  # noqa: E402

FUNDS = (
    "date,pre_nav,post_nav,月涨幅%,买入额,卖出额,换手率%,费用,分红入账,"
    "期末现金,期末持仓,较本金盈亏"
)


# ---------------- W2 交易日连续（纯函数） ----------------


def test_w2_缺工作日必被抓() -> None:
    d = dt.date(2026, 10, 13)  # 周二, 不在节假日表
    assert oh._missing_weekdays(d, d, set()) == ["2026-10-13"]


def test_w2_判别力_加进节假日表后不算缺口(monkeypatch) -> None:
    monkeypatch.setattr(oh, "HOLIDAYS", oh.HOLIDAYS | {"2026-10-13"})
    d = dt.date(2026, 10, 13)
    assert oh._missing_weekdays(d, d, set()) == [], "表里有的日子不该算缺口"


def test_w2_周末与已有数据不算缺口() -> None:
    sat = dt.date(2026, 10, 17)
    assert oh._missing_weekdays(sat, sat, set()) == [], "周六天然无行情"
    tue = dt.date(2026, 10, 13)
    assert oh._missing_weekdays(tue, tue, {"2026-10-13"}) == [], "已有数据不算缺口"


def test_w2_2026年节假日表覆盖已核实的天数() -> None:
    """表里 17 个 2026 休市工作日（春节6+清明1+劳动3+端午1+中秋1+国庆5）。"""
    assert len(oh.HOLIDAYS) == 17
    for d in [
        "2026-02-16",
        "2026-04-06",
        "2026-05-01",
        "2026-06-19",
        "2026-09-25",
        "2026-10-01",
    ]:
        assert d in oh.HOLIDAYS


# ---------------- 造假环境 ----------------


def _stub(tmp: Path):
    fd = tmp / "full_daily"
    fd.mkdir(exist_ok=True)
    fund = tmp / "fundamental"
    fund.mkdir(exist_ok=True)

    class _paths:
        pass

    _paths.fundamental = fund
    _paths.full_dir = fd
    _paths.full_file = tmp / "_none.parquet"
    _paths.stock_basic = tmp / "_nb.parquet"

    class _C:
        pass

    _C.paths = _paths
    return _C()


def _panel(tmp: Path, dates: dict[str, int]) -> None:
    rows = []
    for d, n in dates.items():
        for i in range(n):
            rows.append({"date": pd.Timestamp(d), "code": f"sh.{600000 + i}"})
    pd.DataFrame(rows).to_parquet(tmp / "full_daily" / "2026.parquet", index=False)


def _wire(monkeypatch, tmp: Path):
    stub = _stub(tmp)
    monkeypatch.setattr(data_io, "get_config", lambda: stub)
    # 脚本在函数内 `from quant_trading_01.config import get_config` → 打模块属性即可
    monkeypatch.setattr(config_mod, "get_config", lambda: stub)
    return stub


# ---------------- W3 staging 残留 ----------------


def test_w3_staging残留被抓(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _panel(tmp_path, {"2026-10-15": 10, "2026-10-16": 10, "2026-10-19": 10})
    (tmp_path / "fundamental" / "_stage_daily_20261019.parquet").write_bytes(b"x")

    res = oh.check_data(days=5, probe=False)
    bad = [r for r in res if not r[0]]
    assert bad, "有 staging 残留必须判异常"
    assert any("staging" in r[1] for r in bad)


def test_w3_无残留则通过(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _panel(tmp_path, {"2026-10-16": 10, "2026-10-19": 10})
    res = oh.check_data(days=3, probe=False)
    assert not [r for r in res if not r[0]], [r for r in res if not r[0]]


# ---------------- W4 序列健康 ----------------


def _series(tmp: Path, last: str, dup: bool = False) -> tuple[Path, str, str]:
    out = tmp / "r5"
    out.mkdir(exist_ok=True)
    # 必须含 ledger nav_history 那天(2026-10-08, nav 102.0), 否则 ④ 无法对账
    dates = ["2026-09-01", "2026-10-08", "2026-10-16", last] + (
        ["2026-10-16"] if dup else []
    )
    navs = [100.0, 102.0, 101.0, 102.0] + ([101.0] if dup else [])
    (out / "daily_nav_aum60w.csv").write_text(
        "date,nav,涨幅%\n" + "\n".join(f"{d},{n}," for d, n in zip(dates, navs)) + "\n"
    )
    (out / "ledger_aum60w.json").write_text(
        json.dumps(
            {
                "aum": 600000.0,
                "last_signal": "2026-09-30",
                "last_exec": "2026-10-08",
                "nav_history": [{"date": "2026-10-08", "nav": 102.0, "bench": 1.0}],
            }
        )
    )

    class _r5:
        pass

    _r5.out_dir = out

    class _p3:
        pass

    _p3.out_dir = tmp / "p3"
    _p3.aum_list = []

    class _C:
        pass

    _C.r5 = _r5
    _C.p3 = _p3

    _r5.aum_list = [600000.0]
    return _C(), "2026-10-19", "60w"


def test_w4_末行不等于最新日被抓(monkeypatch, tmp_path) -> None:
    cfg, latest, _ = _series(tmp_path, last="2026-10-16")
    res = oh.check_series(cfg, "r5", latest, verbose=False)
    assert not res[0][0], "末行 10-16 ≠ 最新 10-19 必须判异常"
    assert "末行=最新" in res[0][2]


def test_w4_日期重复被抓(monkeypatch, tmp_path) -> None:
    cfg, latest, _ = _series(tmp_path, last="2026-10-19", dup=True)
    res = oh.check_series(cfg, "r5", latest, verbose=False)
    assert not res[0][0], "重复日期必须判异常"


def test_w4_判别力_修好后通过(tmp_path) -> None:
    cfg, latest, _ = _series(tmp_path, last="2026-10-19")
    res = oh.check_series(cfg, "r5", latest, verbose=False)
    assert res[0][0], res[0]


# ---------------- W5 只读 ----------------


def test_w5_check_series与账本检查只读(tmp_path) -> None:
    cfg, latest, _ = _series(tmp_path, last="2026-10-19")
    files = sorted((tmp_path / "r5").iterdir())
    before = {p.name: p.stat().st_mtime_ns for p in files}
    oh.check_series(cfg, "r5", latest, verbose=False)
    oh.check_ledger(cfg, "r5")
    after = {p.name: p.stat().st_mtime_ns for p in files}
    assert before == after, "体检必须只读"
