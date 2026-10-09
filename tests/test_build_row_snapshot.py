# -*- coding: utf-8 -*-
"""Round 70: 建仓行以账本 build 快照为权威（旧版"文件已存在即跳过"导致遗留旧世代）。

判据见 docs/factor_round70_build_row_repair_plan.md：
  P1 建仓行与账本一致   P3 判别力自证   P4 幂等/正文零改动   P5 质量门
测试全部在 tmp_path 内进行（monkeypatch `_cfg`），不碰真实数据文件。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.r5.paper_live as pl  # noqa: E402

FUNDS_COLS = "date,pre_nav,post_nav,月涨幅%,买入额,卖出额,换手率%,费用,分红入账,期末现金,期末持仓,较本金盈亏"
AUM = 600000.0
SNAP = {
    "date": "2026-09-01",
    "nav": 598087.91,
    "cash": 348357.94,
    "buy": 120000.0,
    "sell": 0.0,
    "fee": 1912.67,
}
WRONG_FIRST = "2026-09-01,600000,598179.99,,130000.00,0,21.7,1820.54,0,359760.99,238419.00,-1820.01"


def _stub(out_dir: Path):
    class _r5:
        pass

    _r5.out_dir = out_dir

    class _C:
        pass

    _C.r5 = _r5
    return _C


def _setup(tmp_path: Path, with_snapshot: bool = True) -> tuple[Path, Path]:
    led_p = tmp_path / "ledger_aum60w.json"
    mf_p = tmp_path / "monthly_funds_aum60w.csv"
    led = {
        "aum": AUM,
        "nav_history": [
            {"date": "2026-09-01", "nav": SNAP["nav"], "bench": 1.0},
            {"date": "2026-10-08", "nav": 5973300.51, "bench": 0.96799},
        ],
        "cash": 399300.23,
        "trades": [],
        "total_fees": 11269.51,
    }
    if with_snapshot:
        led["build"] = SNAP
    led_p.write_text(json.dumps(led))
    mf_p.write_text(
        FUNDS_COLS
        + "\n"
        + WRONG_FIRST
        + "\n"
        + "2026-10-08,5982529.24,5973300.51,-0.2576,1944888,1839278,31.627,9228.67,0,284725.32,5688575.19,-26699.49\n"
    )
    return led_p, mf_p


def test_p1_按快照重建且口径自洽(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pl, "_cfg", lambda: _stub(tmp_path))
    _, mf_p = _setup(tmp_path)
    pl._seed_build_row(AUM)
    r = pd.read_csv(mf_p).iloc[0]
    assert abs(float(r["post_nav"]) - SNAP["nav"]) < 0.005
    assert abs(float(r["期末现金"]) - SNAP["cash"]) < 0.005
    assert abs(float(r["费用"]) - SNAP["fee"]) < 0.005
    assert abs(float(r["期末现金"]) + float(r["期末持仓"]) - float(r["post_nav"])) < 1.0
    assert abs(float(r["post_nav"]) - (AUM - float(r["费用"]))) <= 1.0


def test_p3_判别力自证_旧版存在即返回必然不修(monkeypatch, tmp_path) -> None:
    """旧行为 = `if p.exists(): return` → 首行保持错值；新行为必须重建。"""
    monkeypatch.setattr(pl, "_cfg", lambda: _stub(tmp_path))
    _, mf_p = _setup(tmp_path)
    wrong_nav = float(pd.read_csv(mf_p).iloc[0]["post_nav"])
    assert abs(wrong_nav - SNAP["nav"]) > 1.0, "夹具必须含一个明显不一致的旧世代首行"

    # 旧写法：文件存在就直接返回（用同一 CSV 模拟），首行不动
    before_old = float(pd.read_csv(mf_p).iloc[0]["post_nav"])
    assert before_old == wrong_nav

    pl._seed_build_row(AUM)  # 新写法
    after = float(pd.read_csv(mf_p).iloc[0]["post_nav"])
    assert abs(after - SNAP["nav"]) < 0.005, "新写法必须重建为快照值"
    assert after != before_old, "判据必须有判别力"


def test_p4_step行与正文零改动且幂等(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pl, "_cfg", lambda: _stub(tmp_path))
    _, mf_p = _setup(tmp_path)
    rest_before = pd.read_csv(mf_p).iloc[1:].reset_index(drop=True)
    pl._seed_build_row(AUM)
    a = pd.read_csv(mf_p)
    pl._seed_build_row(AUM)  # 幂等
    b = pd.read_csv(mf_p)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)
    pd.testing.assert_frame_equal(
        a.iloc[1:].reset_index(drop=True), rest_before, check_dtype=False
    )


def test_老账本无快照_保持旧行为不改首行(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pl, "_cfg", lambda: _stub(tmp_path))
    _, mf_p = _setup(tmp_path, with_snapshot=False)
    before = pd.read_csv(mf_p).iloc[0]["post_nav"]
    pl._seed_build_row(AUM)
    assert pd.read_csv(mf_p).iloc[0]["post_nav"] == before, "无快照时不得擅自改写"


# ---------------- P3 同构（R70 镜像） ----------------


import scripts.p3.paper_live_p3 as p3mod  # noqa: E402


def _stub_p3(out_dir: Path):
    class _p3:
        pass

    _p3.out_dir = out_dir

    class _C:
        pass

    _C.p3 = _p3
    return _C


def test_p3_同样按账本快照重建建仓行(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(p3mod, "_cfg", lambda: _stub_p3(tmp_path))
    led = {
        "aum": AUM,
        "nav_history": [
            {"date": "2026-09-01", "nav": SNAP["nav"], "bench": 1.0},
            {"date": "2026-10-08", "nav": 5973300.51, "bench": 0.96799},
        ],
        "cash": 399300.23,
        "trades": [],
        "total_fees": 11269.51,
        "build": SNAP,
    }
    (tmp_path / "ledger_p3_aum60w.json").write_text(json.dumps(led))
    mf_p = tmp_path / "monthly_funds_p3_aum60w.csv"
    mf_p.write_text(FUNDS_COLS + "\n" + WRONG_FIRST + "\n")

    p3mod._seed_build_row(AUM)

    r = pd.read_csv(mf_p).iloc[0]
    assert abs(float(r["post_nav"]) - SNAP["nav"]) < 0.005, "P3 必须同样按快照重建"
    assert abs(float(r["期末现金"]) + float(r["期末持仓"]) - float(r["post_nav"])) < 1.0
