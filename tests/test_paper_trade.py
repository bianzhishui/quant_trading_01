# -*- coding: utf-8 -*-
"""research/ 生产引擎黄金测试（R5 信号 + PaperPortfolio 撮合）。

与 tests/test_backtest.py（测 src/ 旧引擎）互补：本文件覆盖现行生产引擎
  - r5_rebalances: 行业内百分位打分 + 前 1/quantile 选股（窗口/分组走 config strategy.r5）
  - build_pool: 池定义（seasoning / ST / 非主板 / 涨停剔除）
  - PaperPortfolio: 撮合（整手/现金约束/先卖后买）+ 费用 + 涨跌停阻塞 + 除权补回

全部用合成数据（零文件 IO、确定性），不改真实数据。运行: uv run pytest tests/test_paper_trade.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.config import load_config  # noqa: E402
from research.paper_trade import PaperPortfolio, fees, r5_rebalances  # noqa: E402
from research.reversal_factor import build_pool  # noqa: E402


def _make_universe(n_ind: int = 10, per_ind: int = 10) -> tuple:
    """确定性合成宇宙（零噪声几何漂移 → 强度严格单调 → 前 1/5 可精确预测）。

    100 只主板股 = 10 行业 × 10 只，行业按强度连续分块（行业 k 持有强度
    k*10+1..k*10+10），使行业内百分位 rank == 全局强度序 → 前 20% = 强度 81..100。
    返回 (close, amount, tst, isst, ind)。
    """
    idx = pd.bdate_range("2018-01-02", "2021-12-30")  # 末交易日非月末(避免 exec 越界)
    n = n_ind * per_ind
    codes = [f"sh.60{4000 + i:04d}" for i in range(n)]  # 列序 = 强度序(1..n)
    ind_map = {c: f"ind{(i + 1 - 1) // per_ind + 1}" for i, c in enumerate(codes)}

    closes: dict[str, np.ndarray] = {}
    amounts: dict[str, np.ndarray] = {}
    for i, c in enumerate(codes, start=1):  # i = 强度 1..n
        g = 0.0003 * (i - 1)  # 强者日漂移更大 → 动量更高
        amount_i = 1e8 / (1 + 0.05 * (i - 1))  # 强者成交额更低 → Amihud 更高
        closes[c] = 100.0 * np.cumprod(1 + g)  # 纯几何(零噪声) → 完全确定
        amounts[c] = np.full(len(idx), amount_i)

    close = pd.DataFrame(closes, index=idx)
    amount = pd.DataFrame(amounts, index=idx)
    tst = pd.DataFrame(1, index=idx, columns=codes)  # 全部可交易
    isst = pd.DataFrame(0, index=idx, columns=codes)  # 全部非 ST
    ind = pd.Series(ind_map)
    return close, amount, tst, isst, ind


# ---------------- R5 信号 ----------------


def test_r5_golden_top_quintile():
    """黄金断言: 默认配置下末次信号 target = 强度 81..100（前 1/5, 恰好 20 只）。"""
    close, amount, tst, isst, ind = _make_universe()
    rebs, bench, _ = r5_rebalances(close, amount, tst, isst, ind)
    assert len(rebs) >= 20  # 2019-08 起 pool 满 100, 到 2021-11 约 28 个月
    last = rebs[-1]
    assert last["exec"] == pd.Timestamp("2021-12-01")  # 信号 T=2021-11-30 → 次日执行
    codes = list(close.columns)
    assert last["target"] == set(codes[80:])  # 强度 81..100
    assert len(last["target"]) == 20


def test_r5_rebalances_deterministic():
    """同输入两跑 → 目标集完全一致（防 set 哈希序漂移回归, 见 f7f91f1a）。"""
    close, amount, tst, isst, ind = _make_universe()
    r1, _, _ = r5_rebalances(close, amount, tst, isst, ind)
    r2, _, _ = r5_rebalances(close, amount, tst, isst, ind)
    assert [sorted(x["target"]) for x in r1] == [sorted(x["target"]) for x in r2]


def test_r5_config_wiring_quantile(tmp_path, capsys):
    """config strategy.r5.quantile 驱动分组: 3 → 目标 34 只(≠20), 且触发冻结警告。"""
    custom = tmp_path / "custom.yaml"
    custom.write_text("strategy:\n  r5:\n    quantile: 3\n", encoding="utf-8")
    try:
        load_config(str(custom))
        close, amount, tst, isst, ind = _make_universe()
        rebs, _, _ = r5_rebalances(close, amount, tst, isst, ind)
        assert len(rebs[-1]["target"]) == 33  # 100/3 → 34/33/33, 顶组 33
        out = capsys.readouterr().out
        assert "分组数(strategy.r5.quantile)" in out  # 冻结偏离警告
    finally:
        load_config(None)


def test_r5_config_wiring_seasoning(tmp_path):
    """config strategy.r5.seasoning=2000(>1043日) → 全池为空 → 零调仓。"""
    custom = tmp_path / "custom.yaml"
    custom.write_text("strategy:\n  r5:\n    seasoning: 2000\n", encoding="utf-8")
    try:
        load_config(str(custom))
        close, amount, tst, isst, ind = _make_universe()
        rebs, _, _ = r5_rebalances(close, amount, tst, isst, ind)
        assert rebs == []
    finally:
        load_config(None)


# ---------------- 池定义 ----------------


def test_build_pool_excludes_st_and_young():
    close, amount, tst, isst, ind = _make_universe()
    isst.iloc[:, 0] = 1  # 股0 全程 ST
    close.iloc[:700, 1] = np.nan  # 股1 上市仅 ~343 日(< 375)
    pool = build_pool(close, tst, isst)
    last = pool.iloc[-1]
    cols = list(close.columns)
    assert not last[cols[0]]  # ST 剔除
    assert not last[cols[1]]  # 上市不足 seasoning 剔除
    assert bool(last[cols[2]])  # 正常股票在池


def test_build_pool_excludes_non_main_board():
    close, amount, tst, isst, ind = _make_universe()
    close["sz.300001"] = close[close.columns[0]]
    amount["sz.300001"] = amount[amount.columns[0]]
    tst["sz.300001"] = tst[tst.columns[0]]
    isst["sz.300001"] = isst[isst.columns[0]]
    pool = build_pool(close, tst, isst)
    assert not pool.iloc[-1]["sz.300001"]  # 创业板剔除


# ---------------- PaperPortfolio 撮合 ----------------


def test_fees_floor_and_rates():
    f = fees(100.0, "buy", slip=0.0)
    assert f["佣金"] == 5.0  # max(100*万1.5, 最低5元)
    assert f["印花税"] == 0.0  # 买入无印花
    assert f["过户费"] == pytest.approx(100 * 0.00001)
    assert f["滑点"] == 0.0

    f2 = fees(1_000_000.0, "sell", slip=0.0015)
    assert f2["佣金"] == pytest.approx(1_000_000 * 0.00015)
    assert f2["印花税"] == pytest.approx(1_000_000 * 0.0005)
    assert f2["过户费"] == pytest.approx(1_000_000 * 0.00001)
    assert f2["滑点"] == pytest.approx(1_000_000 * 0.0015)


def test_buy_respects_cash_and_lot():
    pf = PaperPortfolio(100_000.0, slip=0.0015)
    prices = pd.Series({"A": 50.0, "B": 60.0, "C": 70.0})
    tradable = pd.Series(True, index=["A", "B", "C"])
    pf.rebalance({"A", "B", "C"}, prices, tradable)
    assert pf.shares == {"A": 600, "B": 500, "C": 400}  # 等权整手
    assert pf.cash >= 0


def test_sell_first_then_buy():
    pf = PaperPortfolio(200_000.0, slip=0.0)
    pf.shares = {"A": 500, "B": 300}
    pf.cash = 200_000.0
    prices = pd.Series({"A": 10.0, "B": 20.0, "C": 15.0})
    tradable = pd.Series(True, index=["A", "B", "C"])
    pf.rebalance({"B", "C"}, prices, tradable)  # A 清出, B 加至 5200, C 买入 7000
    assert "A" not in pf.shares
    assert pf.shares["B"] == 5200
    assert pf.shares["C"] == 7000
    assert pf.cash >= 0


def test_limit_up_blocks_buy():
    pf = PaperPortfolio(100_000.0, slip=0.0015)
    prices = pd.Series({"A": 10.0, "B": 10.0})
    tradable = pd.Series(True, index=["A", "B"])
    ret_exec = pd.Series({"A": 0.10, "B": 0.0})  # A 涨停(≥9.8%)
    pf.rebalance({"A", "B"}, prices, tradable, ret_exec)
    assert "A" in [c for c, _ in pf.blocked_buys]
    assert "A" not in pf.shares
    assert "B" in pf.shares


def test_limit_down_blocks_sell():
    pf = PaperPortfolio(50_000.0, slip=0.0)
    pf.shares = {"A": 500}
    prices = pd.Series({"A": 10.0, "B": 10.0})
    tradable = pd.Series(True, index=["A", "B"])
    ret_exec = pd.Series({"A": -0.10, "B": 0.0})  # A 跌停(≤-9.8%)
    pf.rebalance({"B"}, prices, tradable, ret_exec)
    assert "A" in [c for c, _ in pf.blocked_sells]
    assert pf.shares["A"] == 500  # 未卖出


def test_corp_action_dividend_credit():
    pf = PaperPortfolio(100_000.0, slip=0.0)
    pf.shares = {"A": 1000}
    pf.cash = 0.0
    pf.corp_action_f("A", raw_price=10.0, f_prev=1.0, f_now=1.2)
    # 除权缺口补回 = 1000*10*(1.2/1.0-1)*(1-10%红利税) = 1800
    assert pf.cash == pytest.approx(1800.0)
    assert pf.div_cash == pytest.approx(1800.0)
    # 因子下降(分红除权方向)不产生现金入账(credit 需 > 0)
    pf.corp_action_f("A", raw_price=10.0, f_prev=1.2, f_now=1.0)
    assert pf.cash == pytest.approx(1800.0)


# ---------------- Round35 流动性依赖滑点（口径 B） ----------------


def test_slip_for_amount_tiers():
    """冻结分档表: 金额越大滑点越低 (<Q20→40bp ... ≥Q80→5bp)。"""
    from research.paper_trade import slip_for_amount

    assert slip_for_amount(10_000_000) == 0.004  # < Q20
    assert slip_for_amount(30_000_000) == 0.0025  # Q20-40
    assert slip_for_amount(80_000_000) == 0.0015  # Q40-60
    assert slip_for_amount(200_000_000) == 0.001  # Q60-80
    assert slip_for_amount(500_000_000) == 0.0005  # ≥ Q80


def test_paper_portfolio_slip_by_amount():
    """slip_series 生效: 按股差异化滑点覆盖全局 slip(口径 B); 无 slip_series 用全局。"""
    pf = PaperPortfolio(100_000.0, slip=0.0015)
    pf.slip_series = pd.Series({"A": 0.004})  # A 档 40bp
    pf._order("A", "buy", 1000, 10.0)
    ta = pf.trades[-1]
    assert ta["price"] == pytest.approx(10 * 1.004, abs=1e-3)
    assert ta["滑点"] == pytest.approx(ta["amount"] * 0.004)

    pf2 = PaperPortfolio(100_000.0, slip=0.0015)  # 无 slip_series → 全局 15bp
    pf2._order("A", "buy", 1000, 10.0)
    t2 = pf2.trades[-1]
    assert t2["price"] == pytest.approx(10 * 1.0015, abs=1e-3)
    assert t2["滑点"] == pytest.approx(t2["amount"] * 0.0015)
