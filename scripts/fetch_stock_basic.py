#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""生产宇宙清单刷新 —— 由 src/fundamental.py 的 get_universe/get_stock_basic 迁移。

产出（低频季度/半年刷新，见运营手册 §349）：
  data/fundamental/stock_basic.parquet   全市场证券元数据(type=1 股票, 权威宇宙清单)
  data/fundamental/universe.parquet      hs300+zz500 成分并集(legacy 路径仍读)

用法:
  uv run python scripts/fetch_stock_basic.py            # 全量刷新(baostock)
  uv run python scripts/fetch_stock_basic.py --limit 3  # 试运行(仅 universe 限数无效, 见下)

⚠️ baostock 服务不稳定时不要连续重试(全历史大结果集 rs.next() 会挂起);
   query_stock_basic 全量查询在本环境可能挂起 —— 用已有清单 + 定期温和刷新,
   不要在 baostock 抖动期反复跑本脚本。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quant_trading_01.config import get_config  # noqa: E402


def _out_paths() -> tuple[Path, Path]:
    """(stock_basic, universe) 输出路径（惰性取 config）。"""
    p = get_config().paths
    return Path(p.stock_basic), Path(p.fundamental) / "universe.parquet"


def _ensure_session(max_attempts: int = 6) -> None:
    """登录并**验证会话可用**。

    baostock 服务端偶发"login 返回 success 但会话未建立"(报 用户未登录),
    高频使用后更明显。策略: 登录 → 1行验证查询 → 指数退避重试。
    """
    import baostock as bs

    delays = [1, 3, 8, 15, 30, 60]
    for i in range(max_attempts):
        lg = bs.login()
        if lg.error_code == "0":
            time.sleep(1.0)
            rs = bs.query_stock_basic(code="sh.600000")  # 1 行验证查询
            if rs.error_code == "0":
                return
            print(f"    会话验证失败({rs.error_msg})")
        else:
            print(f"    登录失败({lg.error_msg})")
        try:
            bs.logout()
        except Exception:
            pass
        if i < max_attempts - 1:
            d = delays[min(i, len(delays) - 1)]
            print(f"    退避 {d}s 后重试 ({i + 1}/{max_attempts})")
            time.sleep(d)
    raise RuntimeError("baostock 会话多次建立失败, 疑似限流, 请半小时后再试")


def _rows(rs) -> list[list]:
    out = []
    while rs.error_code == "0" and rs.next():
        out.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"查询失败: {rs.error_msg}")
    return out


def _retry(fn, tries: int = 4, pause: float = 3.0):
    import baostock as bs

    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    重试{i + 1}/{tries - 1}: {e}")
            time.sleep(pause)
            try:
                bs.logout()
            except Exception:
                pass
            try:  # 会话可能已失效(报"用户未登录"时), 重建会话
                _ensure_session()
            except Exception:
                pass


def get_universe() -> pd.DataFrame:
    """当前沪深300+中证500成分并集 → universe.parquet。注意首列是 updateDate, 按名取列。"""
    import baostock as bs

    _, univ_out = _out_paths()
    codes: dict[str, str] = {}
    hs300_set = set()
    for name, fn in [
        ("hs300", bs.query_hs300_stocks),
        ("zz500", bs.query_zz500_stocks),
    ]:
        rs = fn()
        rows = _rows(rs)
        i_code = list(rs.fields).index("code")
        i_name = list(rs.fields).index("code_name")
        for r in rows:
            codes[r[i_code]] = r[i_name]
            if name == "hs300":
                hs300_set.add(r[i_code])
    df = pd.DataFrame(sorted(codes.items()), columns=["code", "name"])
    df["bucket"] = df["code"].map(lambda c: "hs300" if c in hs300_set else "zz500")
    univ_out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(univ_out)
    print(f"成分股: {len(df)} 只 (hs300+zz500 并集) → {univ_out.name}")
    return df


def get_stock_basic() -> pd.DataFrame:
    """全部股票基本信息(一次全表), 过滤出股票类型 → stock_basic.parquet。"""
    import baostock as bs

    basic_out, _ = _out_paths()
    rs = bs.query_stock_basic()
    rows = _rows(rs)
    df = pd.DataFrame(rows, columns=list(rs.fields))
    df = df[df["type"] == "1"]  # 1=股票
    basic_out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(basic_out)
    print(f"stock_basic: {len(df)} 只股票 → {basic_out.name}")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(
        description="生产宇宙清单刷新 (stock_basic + universe)"
    )
    ap.add_argument("--limit", type=int, default=None, help="限制处理数量(试运行)")
    args = ap.parse_args()
    _ = args.limit  # 全表查询不支持限数(与 src/fundamental 一致); 保留参数兼容

    _ensure_session()
    try:
        uni = _retry(get_universe)
        basic = _retry(get_stock_basic)
        # universe 补充 ipoDate/status(与 src/fundamental download 一致)
        uni = uni.merge(basic[["code", "ipoDate", "status"]], on="code", how="left")
        _, univ_out = _out_paths()
        uni.to_parquet(univ_out)
        print("宇宙清单刷新完成")
    finally:
        import baostock as bs

        try:
            bs.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
