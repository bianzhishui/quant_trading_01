# -*- coding: utf-8 -*-
"""Round 73: R72 review 修复（P1 登录崩栈 / P2 单只探测误判 / P3 中间洞）的测试。

判据见 docs/factor_round73_review_fix_plan.md：
  S1 登录失败不崩   S2 探测抽样   S3 中间洞必补   S5 质量门
全部用假 baostock / 假函数 + tmp_path，不联网、不碰真实数据文件。
"""

from __future__ import annotations

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
DATE = "2026-10-09"
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


# ---------------- S2 探测抽样（纯函数级） ----------------


class _ProbeBS:
    def __init__(self, has: set[str]):
        self.has = has
        self.probed: list[str] = []

    def query_history_k_data_plus(self, code, fields, **kw):
        self.probed.append(code)
        return _RS([[DATE]] if code in self.has else [])


def test_s2_抽样探测_任一有数据即视为已发布() -> None:
    bs = _ProbeBS(has={CODES[5]})  # 首只无数据, 第 6 只有
    assert fdi._probe_published(bs, CODES, DATE) is True
    assert bs.probed[-1] == CODES[5] and len(bs.probed) == 3, (
        f"应探测到第 6 只为止(等距抽样 [0,2,5,8,11]), 实际 {bs.probed}"
    )


def test_s2_判别力自证_旧写法只看首只必然误判() -> None:
    """同输入下：旧写法（只探 codes[0]）误判为未发布 → 整天静默跳过；新写法正确放行。"""
    bs = _ProbeBS(has={CODES[5]})
    old_published = bool(bs.has and CODES[0] in bs.has)  # 旧写法
    new_published = fdi._probe_published(_ProbeBS(has={CODES[5]}), CODES, DATE)
    assert old_published is False, "旧写法必然误判（227/3409 只 code 常无行情）"
    assert new_published is True, "新写法必须放行"
    assert old_published != new_published, "判据必须有判别力"


def test_s2_全部无数据则视为未发布() -> None:
    bs = _ProbeBS(has=set())
    assert fdi._probe_published(bs, CODES, DATE) is False


# ---------------- S1 登录失败不崩（端到端，走 update_date） ----------------


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
            "date": [pd.Timestamp("2026-10-08")] * len(CODES),
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


class _LoginFailBS:
    def __init__(self):
        self.queries: list[str] = []

    def login(self):
        return type("_L", (), {"error_code": "10001011", "error_msg": "黑名单用户"})()

    def logout(self):
        pass

    def query_history_k_data_plus(self, *a, **kw):
        self.queries.append(a[0] if a else "?")
        return _RS([])


def test_s1_登录被拒则返回3且零查询(monkeypatch, tmp_path) -> None:
    _universe(tmp_path)
    bs = _LoginFailBS()
    stub = _stub(tmp_path)
    monkeypatch.setitem(sys.modules, "baostock", bs)
    monkeypatch.setattr(fdi, "get_config", lambda: stub)
    monkeypatch.setattr(data_io, "get_config", lambda: stub)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    rc = fdi.update_date(DATE)  # 旧写法在这里抛 AssertionError
    assert rc == 3, "登录被拒必须优雅返回 3"
    assert bs.queries == [], "不得发起任何查询"
    assert not (tmp_path / "_stage_daily_20261009.parquet").exists(), (
        "不得留下空 staging"
    )


# ---------------- S3 中间洞必补 ----------------


def test_s3_backfill_missing_补中间交易日(monkeypatch) -> None:
    calls: list[str] = []
    state = {"have": "2026-10-08"}

    def fake_update(d: str) -> int:
        calls.append(d)
        if d == "2026-10-09":
            state["have"] = "2026-10-09"
        return 0

    monkeypatch.setattr(du, "update_date", fake_update)
    monkeypatch.setattr(du, "data_max_date", lambda: state["have"])

    out = du.backfill_missing("2026-10-10", "2026-10-08")
    assert "2026-10-09" in calls, "缺失的中间交易日必须被补"
    assert out == "2026-10-09"


def test_s3_main里backfill无条件调用() -> None:
    """结构断言：`backfill_missing` 必须在 main 顶层(缩进 4)调用, 而不是只在
    `if tgt > have:` 分支内(缩进 8) —— 否则中间洞会被永久跳过。"""
    src = (ROOT / "scripts" / "r5" / "daily_update.py").read_text()
    body = src[src.index("def main(") :]
    line = next(ln for ln in body.splitlines() if "backfill_missing(tgt, have)" in ln)
    assert line.startswith("    have = backfill_missing"), (
        f"必须在 main 顶层无条件调用, 实际缩进异常: {line!r}"
    )
