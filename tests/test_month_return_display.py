# -*- coding: utf-8 -*-
"""Round 63: `step` 控制台"月涨 +0.00%"显示 bug 的测试。

判据见 docs/factor_round63_mret_display_plan.md v1.0：
  I1 打印=CSV（结构断言）  I2 判别力自证（真实数字）  I3 数据零改动（结构）  I4 质量门

只读源码文本 + 纯算式，不跑 step、不碰数据文件。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "r5" / "paper_live.py"

# 2026-10-09 首次 step 的 60万 真实数字（monthly_funds_aum60w.csv）
POST_NAV = 594897.98
PREV_POST = 598087.91
CSV_MRET = -0.5334  # CSV 里写的 月涨幅%


def _step_body() -> str:
    src = SRC.read_text()
    start = src.index("def step(")
    end = src.index("\ndef ", start + 1)
    return src[start:end]


# ---------------- I2 判别力自证 ----------------


def test_i2_判别力自证_旧顺序必然打印0() -> None:
    # 旧代码：print 里再用已覆盖的 prev_post 做分母
    old_printed = (POST_NAV / POST_NAV - 1) * 100
    # 新代码：用覆盖前算好的 mret
    new_printed = (POST_NAV / PREV_POST - 1) * 100

    assert old_printed == 0.0, "旧顺序必然恒为 0"
    assert abs(new_printed - CSV_MRET) < 2e-3, (
        f"新顺序应等于 CSV 的 {CSV_MRET}，实际 {new_printed:.4f}"
    )
    assert abs(old_printed - new_printed) > 0.1, "判据必须有判别力"


# ---------------- I1 打印=CSV（结构） ----------------


def test_i1_print用mret且不再引用prev_post() -> None:
    body = _step_body()
    lines = [ln for ln in body.splitlines() if "月涨" in ln]
    assert lines, "step 内应有打印月涨的行"
    for ln in lines:
        assert "mret" in ln, f"打印应使用 mret：{ln.strip()}"
        assert "prev_post" not in ln, (
            f"打印不得再引用已被覆盖的 prev_post：{ln.strip()}"
        )


def test_i1_mret在覆盖prev_post之前计算() -> None:
    body = _step_body()
    i_calc = body.index("mret = (post_nav / prev_post - 1) * 100")
    i_overwrite = body.index("prev_post = post_nav")
    assert i_calc < i_overwrite, "mret 必须先于 prev_post 覆盖计算"


# ---------------- I3 数据零改动（结构） ----------------


def test_i3_写入CSV用的仍是同一个mret() -> None:
    body = _step_body()
    assert '"mret": mret,' in body, (
        "CSV 写入必须用同一个 mret 变量（而非重新展开表达式）"
    )


def test_i3_未改动其他账本字段() -> None:
    """纯显示修复：不应新增/删除任何 ledger 字段赋值（除 R64 的 bench_base）。"""
    body = _step_body()
    for field in (
        "last_signal",
        "last_exec",
        "shares",
        "cash",
        "total_fees",
        "last_blocked",
    ):
        assert f'led["{field}"]' in body, f"字段 {field} 的赋值不应被动过"
