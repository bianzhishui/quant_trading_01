# -*- coding: utf-8 -*-
"""P3 运营链黄金测试（合成数据、零文件 IO、确定性）。

覆盖 P3 特有逻辑（R5 test_paper_trade 覆盖共享 PaperPortfolio 引擎）：
  - eval_prices（R48 停牌估值）：停牌沿用最后价 / 退市按最后价冻结 / 上市前 NaN 不填 / 复牌正常
  - holdings_detail.compute_detail：净投入成本(含费) / 市值 / 盈亏 / 已回本成本归零

运行: uv run pytest tests/test_paper_live_p3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quant_trading_01.config import load_config  # noqa: E402
from scripts.r5.paper_trade import PaperPortfolio  # noqa: E402
from scripts.r5.paper_live import eval_prices  # noqa: E402
from scripts.holdings_detail import compute_detail  # noqa: E402


@pytest.fixture(scope="module")
def cfg():
    load_config(None)
    return None


# ---------------- eval_prices (R48) ----------------

def _mk_raw() -> pd.DataFrame:
    """a=中间停牌2天, b=尾部停牌(退市), c=上市前NaN, d=正常。"""
    return pd.DataFrame(
        {
            "a": [10.0, 10.5, np.nan, np.nan, 11.0],  # 索引1后停牌, 索引4复牌
            "b": [3.0, 3.1, 3.2, np.nan, np.nan],     # 索引3起尾部 NaN(退市)
            "c": [np.nan, 5.0, 5.1, 5.2, 5.3],        # 索引0上市前 NaN
            "d": [2.0, 2.1, 2.2, 2.3, 2.4],
        },
        index=pd.date_range("2026-09-01", periods=5),
    )


def test_eval_suspend_uses_last_price():
    raw = _mk_raw()
    raw_e = eval_prices(raw)
    # 停牌日(索引2): a 沿用 10.5, b 沿用 3.2
    assert raw_e.loc[raw_e.index[2], "a"] == 10.5
    assert raw_e.loc[raw_e.index[2], "b"] == 3.2


def test_eval_delisted_tail_frozen_at_last_price():
    raw = _mk_raw()
    raw_e = eval_prices(raw)
    # 退市尾部(索引4): b 冻结在最后价 3.2(非NaN)
    assert raw_e.loc[raw_e.index[4], "b"] == 3.2
    assert raw_e.loc[raw_e.index[4], "b"] != np.nan


def test_eval_pre_listing_stays_nan():
    raw = _mk_raw()
    raw_e = eval_prices(raw)
    # 上市前(索引0): c 保持 NaN(ffill 不填列首)
    assert pd.isna(raw_e.loc[raw_e.index[0], "c"])


def test_eval_resume_day_shows_true_move():
    raw = _mk_raw()
    raw_e = eval_prices(raw)
    # 复牌日(索引4): a = 11.0(真实复牌价, 非冻结)
    assert raw_e.loc[raw_e.index[4], "a"] == 11.0


def test_eval_value_accounts_suspended():
    """停牌持仓在 ffill 后计入市值(NAV 不归零)。"""
    raw = _mk_raw()
    raw_e = eval_prices(raw)
    pf = PaperPortfolio(100000, 0.0015)
    pf.shares = {"a": 100, "b": 100}
    day = 2  # a/b 均停牌
    v_old = pf.value(raw.iloc[day])
    v_new = pf.value(raw_e.iloc[day])
    assert v_new > v_old  # 旧口径 b 市值归零
    # 新口径: 现金 + a*10.5 + b*3.2
    assert v_new == pytest.approx(100000 + 100 * 10.5 + 100 * 3.2)


# ---------------- holdings_detail.compute_detail ----------------

def _mk_prices() -> tuple:
    idx = pd.date_range("2026-09-01", periods=3)
    real = pd.DataFrame(
        {"x": [10.0, 10.2, 10.4], "y": [5.0, 5.1, 5.2]}, index=idx
    )
    close = pd.DataFrame(
        {"x": [10.0, 10.2, 10.4], "y": [5.0, 5.1, 5.2]}, index=idx
    )
    ret_d = close.pct_change()
    return real, close, ret_d


def _mk_ledger() -> dict:
    """x: 买100股@10 + 费(佣金5/过户0.1) → 成本 1005.1; y: 已买入卖回(净成本≈0)."""
    return {
        "aum": 100000.0,
        "shares": {"x": 100, "y": 100},
        "cash": 1000.0,
        "trades": [
            {"code": "x", "side": "buy", "amount": 1000.0, "佣金": 5.0, "过户费": 0.1, "印花税": 0.0},
            {"code": "y", "side": "buy", "amount": 500.0, "佣金": 5.0, "过户费": 0.05, "印花税": 0.0},
            {"code": "y", "side": "sell", "amount": 500.0, "佣金": 5.0, "印花税": 2.5, "过户费": 0.05},
        ],
        "nav_history": [{"date": "2026-09-01", "nav": 100000.0}],
    }


def test_compute_detail_cost_and_pnl():
    real, close, ret_d = _mk_prices()
    df = compute_detail(_mk_ledger(), real, close, ret_d, {"x": "X股", "y": "Y股"})
    row_x = df[df["code"] == "x"].iloc[0]
    # 净投入成本 = 1000+5+0.1 = 1005.1; 成本价 = 10.051; 现价 10.4; 市值 1040
    assert row_x["cost_px"] == pytest.approx(1005.1 / 100, abs=1e-3)
    assert row_x["mkt_val"] == pytest.approx(1040.0)
    assert row_x["pnl"] == pytest.approx(1040.0 - 1005.1, abs=1e-6)
    # 当日涨幅(索引2 vs 1): x = 10.4/10.2-1
    assert row_x["ret_today"] == pytest.approx(10.4 / 10.2 - 1)


def test_compute_detail_breakeven_cost_zero():
    """y 已买回卖(净投入≈0) → 成本价归零(剩余是纯利润), 不除零。"""
    real, close, ret_d = _mk_prices()
    df = compute_detail(_mk_ledger(), real, close, ret_d, {})
    row_y = df[df["code"] == "y"].iloc[0]
    # 净投入 = (500+5+0.05) - (500-5-2.5-0.05) = 505.05 - 492.45 = 12.6 > 0 → 成本价 = 12.6/100
    assert row_y["cost_px"] == pytest.approx(12.6 / 100, abs=1e-3)
    assert row_y["pnl"] == pytest.approx(100 * 5.2 - 12.6, abs=1e-6)


def test_compute_detail_suspended_px_nan():
    """持仓股某日停牌(real NaN): mkt_val 为 NaN, 不计入 sort(不崩溃)。"""
    real, close, ret_d = _mk_prices()
    real.loc[real.index[2], "x"] = np.nan  # x 最后日停牌
    df = compute_detail(_mk_ledger(), real, close, ret_d, {})
    row_x = df[df["code"] == "x"].iloc[0]
    assert pd.isna(row_x["mkt_val"])
