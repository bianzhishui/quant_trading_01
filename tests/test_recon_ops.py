# -*- coding: utf-8 -*-
"""Round 74: 运营对账脚本（scripts/recon_ops.py）的测试。

判据见 docs/factor_round74_recon_ops_promote_plan.md：
  T1 配置化   T3 判别力自证   T4 只读   T5 --strat
全部在 tmp_path 造假数据，不碰真实产物。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import quant_trading_01.config as config_mod  # noqa: E402
import scripts.recon_ops as recon  # noqa: E402

FUNDS_COLS = (
    "date,pre_nav,post_nav,月涨幅%,买入额,卖出额,换手率%,费用,分红入账,"
    "期末现金,期末持仓,较本金盈亏"
)
LED = {
    "aum": 600000.0,
    "last_signal": "2026-08-31",
    "last_exec": "2026-09-01",
    "nav_history": [{"date": "2026-09-01", "nav": 598087.91, "bench": 1.0}],
}


def _write_account(d: Path, nav: float, cash: float, pos: float, fee: float) -> None:
    (d / "ledger_aum60w.json").write_text(
        json.dumps(
            {**LED, "nav_history": [{"date": "2026-09-01", "nav": nav, "bench": 1.0}]}
        )
    )
    (d / "monthly_funds_aum60w.csv").write_text(
        FUNDS_COLS + "\n"
        f"2026-09-01,600000,{nav},,500000.00,0,83.3,{fee},0,{cash},{pos},{nav - 600000}\n"
    )
    (d / "daily_nav_aum60w.csv").write_text(f"date,nav,涨幅%\n2026-09-01,{nav:.2f},\n")


def _stub_cfg(d: Path, aums=(600000.0,)):
    class _r5:
        out_dir = d

    _r5.aum_list = list(aums)

    class _p3:
        out_dir = d
        aum_list = []

    class _C:
        r5 = _r5
        p3 = _p3

    return _C()


def _patch_main(monkeypatch, d: Path, aums=(600000.0,)):
    monkeypatch.setattr(config_mod, "get_config", lambda: _stub_cfg(d, aums))
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: None)
    monkeypatch.setattr(
        config_mod,
        "add_config_arg",
        lambda ap: ap.add_argument("--config", default=None),
    )
    monkeypatch.setattr(sys, "argv", ["recon_ops.py"])


def test_t1_无硬编码账户标签() -> None:
    src = (ROOT / "scripts" / "recon_ops.py").read_text()
    for label in ('"60w"', '"10w"', '"600w"', "'60w'"):
        assert label not in src, f"不得硬编码账户标签 {label}"
    assert "aum_list" in src and "SPECS" in src


def test_t3_好账户全过_退出码0(monkeypatch, tmp_path) -> None:
    _write_account(tmp_path, nav=598087.91, cash=348357.94, pos=249729.97, fee=1912.67)
    _patch_main(monkeypatch, tmp_path)
    assert recon.main() == 0


def test_t3_判别力自证_坏账户必不通过且退出码1(monkeypatch, tmp_path) -> None:
    """① 净值 ≠ 现金+持仓（差 100 元 > 容差 1 元）→ 必须判 ❌ 且退出码 1。"""
    _write_account(tmp_path, nav=598087.91, cash=348357.94, pos=249629.97, fee=1912.67)
    _patch_main(monkeypatch, tmp_path)
    assert (
        recon.check_one(
            "60w",
            tmp_path / "ledger_aum60w.json",
            tmp_path / "daily_nav_aum60w.csv",
            tmp_path / "monthly_funds_aum60w.csv",
        )
        is False
    )
    assert recon.main() == 1, "有账户未通过必须返回 1"


def test_t3_缺文件也算不通过(monkeypatch, tmp_path) -> None:
    _patch_main(monkeypatch, tmp_path)  # 什么都没写
    assert recon.main() == 1


def test_t4_check_one只读(monkeypatch, tmp_path) -> None:
    _write_account(tmp_path, nav=598087.91, cash=348357.94, pos=249729.97, fee=1912.67)
    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    recon.check_one(
        "60w",
        tmp_path / "ledger_aum60w.json",
        tmp_path / "daily_nav_aum60w.csv",
        tmp_path / "monthly_funds_aum60w.csv",
    )
    after = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    assert before == after, "对账必须只读，不得改动/新增文件"


def test_t5_strat分流() -> None:
    cfg = _stub_cfg(Path("/nonexistent"), aums=(600000.0, 1000000.0))
    assert len(recon.run_strategy("r5", cfg)) == 2
    assert recon.run_strategy("p3", cfg) == []  # p3.aum_list 为空
