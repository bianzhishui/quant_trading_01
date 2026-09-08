#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""全市场行业映射抓取（~3194 只，baostock 单连接，断点续传）。
产出 data/round2/industry_full.parquet: code, industry
用法: uv run python research/fetch_full_industry.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from research.data_io import universe_codes  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = (
    Path(__file__).resolve().parent.parent / "data" / "round2" / "industry_full.parquet"
)
SRC = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fundamental"
    / "full_daily.parquet"
)


def main() -> None:
    import baostock as bs

    # 策略宇宙(含退市股): stock_basic type=1, sh.60/sz.00, status 不限
    codes = universe_codes()
    have = {}
    if OUT.exists():
        have = dict(zip(pd.read_parquet(OUT)["code"], pd.read_parquet(OUT)["industry"]))
    todo = [c for c in codes if c not in have]
    print(
        f"行业映射: 共 {len(codes)} 只, 已有 {len(have)}, 待抓 {len(todo)}", flush=True
    )
    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    rows = []
    for i, c in enumerate(todo, 1):
        for attempt in range(3):
            try:
                rs = bs.query_stock_industry(code=c)
                while rs.error_code == "0" and rs.next():
                    r = rs.get_row_data()
                    rows.append({"code": r[1], "industry": r[3]})
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  {c} 失败: {e}", flush=True)
                else:
                    time.sleep(2.0)
        if i % 500 == 0 or i == len(todo):
            new = pd.DataFrame(rows)
            if len(new):
                all_df = pd.concat(
                    [
                        pd.DataFrame(
                            [{"code": k, "industry": v} for k, v in have.items()]
                        ),
                        new,
                    ],
                    ignore_index=True,
                )
                all_df = all_df.drop_duplicates(subset=["code"])
                all_df.to_parquet(OUT)
                print(f"  [{i}/{len(todo)}] 累计 {len(all_df)} 只", flush=True)
    bs.logout()
    print("行业映射完成", flush=True)


if __name__ == "__main__":
    main()
