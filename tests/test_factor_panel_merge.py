# -*- coding: utf-8 -*-
"""Round 61: `_factor_panel` 静态×live 合并去重修复的测试。

严格按 docs/factor_round61_factor_panel_dedup_plan.md v1.0 §3 判据：
  G1 复现与修复（真实数据：修复前必抛 ValueError，修复后正常返回）
  G2 取值零改动（两表重叠的 (code,date) 值逐位相等 —— 只有真有重叠样本才有判别力）
  G3 判别力自证（合成重复输入：旧写法必然抛错、新写法通过）

快速用例只用合成数据、不碰任何数据文件；真实数据用例挂在 `slow` marker 下
（仓库默认 `-m 'not slow'` 跳过，手动 `pytest -m slow` 跑）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.r5.paper_live import _factor_panel, _merge_factor_tables  # noqa: E402

STATIC_P = ROOT / "data" / "round2" / "adjust_factor.parquet"
LIVE_P = ROOT / "data" / "round2" / "adjust_factor_live.parquet"


def _static() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["sh.600000", "sh.600000", "sz.003008"],
            "date": ["2026-08-15", "2026-09-03", "2026-09-03"],
            "foreAdjustFactor": [1.0, 1.0, 1.0],
        }
    )


def _live() -> pd.DataFrame:
    # 与静态在 (sz.003008, 2026-09-03) 上重叠 —— 真实场景的复刻
    return pd.DataFrame(
        {
            "code": ["sz.003008", "sh.601008"],
            "date": ["2026-09-03", "2026-09-17"],
            "foreAdjustFactor": [1.0, 1.0],
        }
    )


def _old_panel(static: pd.DataFrame, live: pd.DataFrame, idx: pd.DatetimeIndex):
    """修复前的写法：concat 不去重 → groupby 后索引含重复标签 → reindex 抛错。"""
    both = pd.concat([static, live], ignore_index=True)
    both["date"] = pd.to_datetime(both["date"])
    for _c, g in both.groupby("code"):
        g = g.sort_values("date").set_index("date")["foreAdjustFactor"]
        g.reindex(idx)  # 重复标签在这里炸


# ---------------- G3 判别力自证（合成数据，快） ----------------


def test_g3_旧写法必然抛错_新写法通过() -> None:
    st, lv = _static(), _live()
    idx = pd.date_range("2026-08-01", "2026-10-10", freq="D")
    with pytest.raises(ValueError, match="duplicate labels"):
        _old_panel(st, lv, idx)  # 旧写法必违规

    merged = _merge_factor_tables(st, lv)
    assert not merged.duplicated(subset=["code", "date"]).any()  # 新写法 0 违规
    assert len(merged) == len(st) + len(lv) - 1  # 恰好去掉 1 条重叠


def test_g3_去重方向_live优先() -> None:
    st = pd.DataFrame(
        {"code": ["a"], "date": ["2026-09-03"], "foreAdjustFactor": [1.0]}
    )
    lv = pd.DataFrame(
        {"code": ["a"], "date": ["2026-09-03"], "foreAdjustFactor": [2.0]}
    )
    out = _merge_factor_tables(st, lv)
    assert len(out) == 1
    assert float(out.iloc[0]["foreAdjustFactor"]) == 2.0, "冲突时应取 live（新查）"


def test_边界_live为None或空() -> None:
    st = _static()
    assert _merge_factor_tables(st, None) is st
    assert (
        _merge_factor_tables(
            st, pd.DataFrame(columns=["code", "date", "foreAdjustFactor"])
        )
        is st
    )


def test_无重叠时不改变内容() -> None:
    st = _static()
    lv = pd.DataFrame(
        {"code": ["sh.601008"], "date": ["2026-09-17"], "foreAdjustFactor": [3.0]}
    )
    out = _merge_factor_tables(st, lv)
    assert len(out) == len(st) + 1
    assert set(out["code"]) == {"sh.600000", "sz.003008", "sh.601008"}


# ---------------- G1/G2 真实数据（slow） ----------------


@pytest.mark.slow
def test_g1_真实数据_修复前必抛_修复后正常() -> None:
    if not (STATIC_P.exists() and LIVE_P.exists()):
        pytest.skip("静态或 live 因子文件不存在")
    st, lv = pd.read_parquet(STATIC_P), pd.read_parquet(LIVE_P)
    both = pd.concat([st, lv], ignore_index=True)
    both["date"] = pd.to_datetime(both["date"])
    dup = both[both.duplicated(subset=["code", "date"], keep=False)]
    if dup.empty:
        pytest.skip("当前两表无重叠（判据无判别力，不虚报通过）")
    conflict_code = str(dup.iloc[0]["code"])

    idx = pd.date_range("2026-08-01", "2026-10-10", freq="D")
    with pytest.raises(ValueError, match="duplicate labels"):
        _old_panel(st, lv, idx)  # 修复前：用当前真实数据复现崩溃

    close = pd.DataFrame(
        index=idx, columns=["sz.003008", conflict_code, "sh.601008"], data=1.0
    )
    panel = _factor_panel(close)  # 修复后：正常返回
    assert panel.shape == (len(idx), close.shape[1])
    assert panel.isna().sum().sum() == 0


@pytest.mark.slow
def test_g2_重叠样本取值逐位相等() -> None:
    if not (STATIC_P.exists() and LIVE_P.exists()):
        pytest.skip("静态或 live 因子文件不存在")
    st, lv = pd.read_parquet(STATIC_P), pd.read_parquet(LIVE_P)
    st["date"], lv["date"] = pd.to_datetime(st["date"]), pd.to_datetime(lv["date"])
    m = st.merge(lv, on=["code", "date"], suffixes=("_s", "_l"))
    assert len(m) > 0, "必须真的存在重叠样本，否则本判据没有判别力"
    diff = (m["foreAdjustFactor_s"] - m["foreAdjustFactor_l"]).abs().max()
    assert diff == 0, f"重叠样本取值不一致(max diff={diff}) → 去重的 keep 方向有歧义"
