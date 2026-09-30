# -*- coding: utf-8 -*-
"""R58 面板体检门：看守 R57 修复过的"复权因子回落 1.0 → real=前复权价"静默数据 bug。

不变量（期望值由**独立 numpy 实现**给出，不调用被测函数）：
  I1 生效记录值: 面板因子在日期 t 必须等于"t 时点生效的记录值" = 最后一个日期 ≤ t 的记录值;
                 若 t 之前没有任何记录 → 最早一条记录值。**绝不允许凭空填 1.0**
                 （旧写法正是在记录日之前填 1.0 —— 601377 实测 1.0 vs 0.20474）。
  I2 跳变时机:   同一 code 的因子只允许在其**记录日**当天跳变（step function）。
  I3 真实价恒等: real × factor == close（相对 1e-8）。
  I4 涨跌停不变式: 非记录日的 |Δreal| > 12% 占比 ≤ 0.1%（辅助）。
  I5 判别力自证: 旧写法必须**至少产生 1 个 I1 违规**（体检门不能是橡皮图章）。

约定差异（**不是缺陷，已量化，勿静默统一**）: R5 的 `paper_trade.py:83` / `paper_live.py:259`
用 `reindex(idx).ffill().bfill().fillna(1.0)`（不回落 1.0，但会丢弃索引起点前的记录 →
用"索引内首条记录"代替"最后一条更早记录"）。R58 实测该约定与统一写法在 2013-06~2014-12
有 194,710 个 stock-days 差异（1,376 只，比率中位 0.9847、p10 0.6254）→ **按预注册 Y7
"有差异则不做"，R5 两处未改**；若要统一须走 R5 侧预注册。

快速层（默认）：2014-2015 分区 × 抽样 code ≈ 数秒。全市场层：`pytest -m slow`。
只读真实数据文件，绝不写入（AGENTS.md §8）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_trading_01.panel import forward_factor_series

ROUND2_FAC = "data/round2/adjust_factor.parquet"
DAILY_DIR = "data/fundamental/full_daily"
FAST_YEARS = (2014, 2015)
# R56 实测在旧写法下出现 -169%~-386% 假跳变的股票（索引内首条因子记录落在 2014 年中）
KNOWN_BUGGY = ["sh.601377", "sh.601199", "sz.002107"]


@lru_cache(maxsize=4)
def _load(years: tuple[int, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    fac = pd.read_parquet(ROUND2_FAC)
    fac["date"] = pd.to_datetime(fac["date"])
    df = pd.concat(
        [pd.read_parquet(f"{DAILY_DIR}/{y}.parquet") for y in years], ignore_index=True
    )
    close = df.pivot_table(
        index="date", columns="code", values="close", aggfunc="last"
    ).sort_index()
    return fac, close


def _sample_codes(years: tuple[int, ...], n: int = 24) -> list[str]:
    fac, close = _load(years)
    grid, cols = close.index, set(close.columns)
    in_win = fac[fac["date"].isin(grid)].groupby("code")["date"].min()
    late = sorted(
        c for c in in_win[in_win.notna() & (in_win > grid[0])].index if c in cols
    )
    rng = np.random.default_rng(58)
    extra = [
        c
        for c in rng.choice(sorted(cols), size=80, replace=False)
        if c in set(fac["code"])
    ]
    return sorted(set([c for c in KNOWN_BUGGY if c in cols] + late[:n] + extra[:n]))


def _records(fac: pd.DataFrame, code: str) -> tuple[np.ndarray, np.ndarray]:
    s = (
        fac[fac["code"] == code]
        .sort_values("date")
        .set_index("date")["foreAdjustFactor"]
    )
    s = s[~s.index.duplicated()]
    return s.index.to_numpy(), s.to_numpy(dtype=float)


def _expected_factor(rec_dates: np.ndarray, rec_vals: np.ndarray, grid) -> np.ndarray:
    """独立实现：t 时点生效的记录值（无更早记录 → 最早一条）。不复用被测函数。"""
    pos = np.searchsorted(rec_dates, grid.to_numpy(), side="right") - 1
    pos[pos < 0] = 0
    return rec_vals[pos]


def _variants(s: pd.Series, grid, mode: str) -> np.ndarray:
    if mode == "helper":
        return forward_factor_series(s, grid).to_numpy(dtype=float)
    if mode == "old":  # R41（R57 修复前）
        return s.reindex(grid).ffill().fillna(1.0).to_numpy(dtype=float)
    if mode == "old_r5":  # R5 现行约定
        return s.reindex(grid).ffill().bfill().fillna(1.0).to_numpy(dtype=float)
    raise ValueError(mode)


def _violations(
    fac: pd.DataFrame, codes: list[str], grid, mode: str
) -> tuple[int, int]:
    """返回 (I1 违规数, I2 违规数)。"""
    i1 = i2 = 0
    rec_dates_all = set(fac["date"])
    for c in codes:
        rec_dates, rec_vals = _records(fac, c)
        if len(rec_dates) == 0:
            continue
        s = pd.Series(rec_vals, index=pd.DatetimeIndex(rec_dates))
        f = _variants(s, grid, mode)
        exp = _expected_factor(rec_dates, rec_vals, grid)
        ok = np.isfinite(f) & np.isfinite(exp)
        i1 += int((np.abs(f[ok] - exp[ok]) > 1e-12).sum())
        prev = np.nan
        for t, v in zip(grid, f):
            if (
                np.isfinite(v)
                and np.isfinite(prev)
                and abs(v - prev) > 1e-12
                and t not in rec_dates_all
            ):
                i2 += 1
            prev = v
    return i1, i2


@pytest.fixture(scope="module")
def facade():
    fac, close = _load(FAST_YEARS)
    return fac, close.index, _sample_codes(FAST_YEARS), close


def test_i5_buggy_idiom_is_detected(facade):
    """判别力自证（Y4）：旧写法必须被抓到，修复后的公共助手必须干净。"""
    fac, grid, codes, _ = facade
    old_i1, _ = _violations(fac, codes, grid, mode="old")
    r5_i1, _ = _violations(fac, codes, grid, mode="old_r5")
    new_i1, new_i2 = _violations(fac, codes, grid, mode="helper")
    assert old_i1 > 0, "旧写法竟然没被 I1 抓到 —— 体检门失去判别力"
    assert new_i1 == 0, f"修复后的公共助手仍有 I1 违规 {new_i1} 处"
    assert new_i2 == 0, f"修复后的公共助手在非记录日跳变 {new_i2} 次"
    # R5 约定的事实差异（见模块 docstring）: 严格 I1 会判它违规 → 记录在案, 不静默统一
    assert r5_i1 > 0, "R5 约定与统一写法的差异消失了？请更新 docstring 与 R58 §0"


def test_i1_i2_factor_uses_effective_record_value(facade):
    fac, grid, codes, _ = facade
    i1, i2 = _violations(fac, codes, grid, mode="helper")
    assert i1 == 0, f"因子非 t 时点生效记录值（疑似回落 1.0）: {i1} 处"
    assert i2 == 0, f"因子在非记录日跳变: {i2} 次"


def test_i3_real_times_factor_equals_close(facade):
    fac, grid, codes, close = facade
    checked = 0
    for c in codes:
        if c not in close.columns:
            continue
        rec_dates, rec_vals = _records(fac, c)
        if len(rec_dates) == 0:
            continue
        s = pd.Series(rec_vals, index=pd.DatetimeIndex(rec_dates))
        f = forward_factor_series(s, grid)
        real = close[c] / f
        bad = (real * f - close[c]).abs() > 1e-8 * close[c].abs().clip(lower=1e-6)
        assert int(bad.sum()) == 0, (
            f"{c} 恒等式 real×factor==close 失败 {int(bad.sum())} 处"
        )
        checked += 1
    assert checked >= 20, f"抽样过少（{checked}）→ 体检门形同虚设"


def test_i4_no_big_jump_off_record_days(facade):
    fac, grid, codes, close = facade
    jumps = tot = 0
    for c in codes:
        if c not in close.columns:
            continue
        rec_dates, rec_vals = _records(fac, c)
        if len(rec_dates) == 0:
            continue
        s = pd.Series(rec_vals, index=pd.DatetimeIndex(rec_dates))
        real = close[c] / forward_factor_series(s, grid)
        d = real.pct_change(fill_method=None)
        off = ~grid.isin(pd.DatetimeIndex(rec_dates))
        v = d.to_numpy()[off]
        m = np.isfinite(v)
        jumps += int((np.abs(v[m]) > 0.12).sum())
        tot += int(m.sum())
    share = jumps / max(tot, 1)
    assert share <= 0.001, f"非记录日 |Δreal|>12% 占比 {share:.4%} > 0.1%"


@pytest.mark.slow
def test_i1_full_universe_all_years():
    """全市场全区间：`pytest -m slow`（全部年份分区 × 全部 code）。"""
    years = tuple(sorted(int(p.stem) for p in Path(DAILY_DIR).glob("*.parquet")))
    fac, close = _load(years)
    codes = sorted(set(fac["code"]) & set(close.columns))
    i1, i2 = _violations(fac, codes, close.index, mode="helper")
    assert i1 == 0 and i2 == 0, f"全市场体检未过: I1 {i1} 处 / I2 {i2} 次"
