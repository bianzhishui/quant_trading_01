# -*- coding: utf-8 -*-
"""baostock 结果集安全迭代（Round 78）。

背景
----
baostock 的 `rs.next()` 在**会话半断/被限流**时会**持续返回 True 但不前进**。
裸写法::

    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())

在这种状态下会**无限循环 + rows 无限增长** → 100% CPU 空转、永不结束
（实测 2026-10-23 `daily_update` 卡死 58 分钟、staging 零进度）。

注意：忙等**不抛异常**，所以任何 `try/except + 重试` 包装对它都无效——
必须靠**行数上限**或**墙钟超时**主动打断。

用法
----
::

    from quant_trading_01.bs_utils import fetch_rows

    rows = fetch_rows(rs, max_rows=200, timeout_s=30.0)

调用方负责：① 决定 `max_rows`（按该查询的合理上界）；② 捕获 `BaostockQueryError`
后决定跳过还是重试。
"""

from __future__ import annotations

import contextlib
import signal


class BaostockQueryError(RuntimeError):
    """baostock 查询异常基类。"""


class QueryTimeout(BaostockQueryError):
    """查询墙钟超时（含 next() 忙等）。"""


class QueryTooManyRows(BaostockQueryError):
    """返回行数超过调用方设定的上界（防止忙等导致的无限增长）。"""


@contextlib.contextmanager
def time_limit(seconds: float):
    """给一段代码加墙钟上限；超时抛 QueryTimeout。

    仅在**主线程**有效（`signal` 语义限制）。本项目所有调用都在主线程。
    """
    if not seconds or seconds <= 0:
        yield
        return

    def _handler(signum, frame):  # noqa: ARG001
        raise QueryTimeout(f"查询超时(>{seconds}s)")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def fetch_rows(rs, *, max_rows: int, timeout_s: float) -> list[list[str]]:
    """安全读完 baostock 结果集，返回行列表。

    与裸 `while rs.error_code == "0" and rs.next()` 的差别只有两点：
    ① 行数超过 `max_rows` → 立即抛 `QueryTooManyRows`；
    ② 整体受 `timeout_s` 墙钟保护 → 超时抛 `QueryTimeout`。
    读取结束后仍检查 `error_code`（保持各调用点原有的失败语义）。
    """
    rows: list[list[str]] = []
    with time_limit(timeout_s):
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
            if len(rows) > max_rows:
                raise QueryTooManyRows(f"返回行数超过上界 {max_rows}")
    if rs.error_code != "0":
        raise BaostockQueryError(f"baostock 查询失败: {rs.error_msg}")
    return rows
