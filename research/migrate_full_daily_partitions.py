#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""一次性迁移: full_daily.parquet 单文件 → full_daily/ 按年分区。

用法:
  python research/migrate_full_daily_partitions.py --target /tmp/mig_test   # 试运行(写/tmp)
  python research/migrate_full_daily_partitions.py --real                   # 正式迁移(先备份)
迁移后自动做行级一致性校验(行数/股票数/逐值比对), 校验不过不改真实文件。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.data_io import FULL_DIR, FULL_FILE  # noqa: E402

INDEX_COLS = None  # 动态识别 __index_level_* 垃圾列


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    drop = [c for c in df.columns if str(c).startswith("__index_level")]
    return df.drop(columns=drop, errors="ignore")


def migrate(src: Path, dst_dir: Path) -> pd.DataFrame:
    """读单文件 → 按年原子写分区。返回清洗后的源帧(供校验)。"""
    df = _clean(pd.read_parquet(src))
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    dst_dir.mkdir(parents=True, exist_ok=True)
    for year, g in df.groupby("year"):
        p = dst_dir / f"{int(year)}.parquet"
        part = (
            g.drop(columns=["year"])
            .drop_duplicates(subset=["date", "code"])
            .sort_values("date")
        )
        tmp = p.with_suffix(".parquet.tmp")
        part.to_parquet(tmp, index=False)
        os.replace(tmp, p)
        print(
            f"  year={int(year)}: {len(part):,} 行 / {part['code'].nunique()} 只",
            flush=True,
        )
    return df


def verify(src: Path, dst_dir: Path) -> None:
    """行级一致性: 旧单文件(清洗后) vs 分区并集, 逐值比对。"""
    old = _clean(pd.read_parquet(src)).reset_index(drop=True)
    parts = [pd.read_parquet(p) for p in sorted(dst_dir.glob("*.parquet"))]
    new = (
        pd.concat(parts, ignore_index=True)
        .drop_duplicates(subset=["date", "code"])
        .sort_values(["date", "code"])
        .reset_index(drop=True)
    )
    old_s = old.sort_values(["date", "code"]).reset_index(drop=True)
    assert len(old_s) == len(new), f"行数不一致: {len(old_s)} vs {len(new)}"
    assert set(old_s["code"]) == set(new["code"]), "code 集合不一致"
    assert list(old_s.columns) == list(new.columns), f"列不一致: {list(new.columns)}"
    pd.testing.assert_frame_equal(old_s, new, check_exact=True)
    print(
        f"✅ 校验通过: {len(new):,} 行 / {new['code'].nunique()} 只 / "
        f"{new['date'].min().date()} → {new['date'].max().date()}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--target", default=None, help="试运行目标目录(写/tmp等, 不动真实数据)"
    )
    ap.add_argument("--real", action="store_true", help="正式迁移(先备份单文件)")
    args = ap.parse_args()

    if args.target:
        print(f"[试运行] {FULL_FILE} → {args.target}")
        migrate(FULL_FILE, Path(args.target))
        verify(FULL_FILE, Path(args.target))
        print("试运行通过(未动真实数据)")
        return
    if args.real:
        bak = FULL_FILE.with_suffix(".parquet.singlefile.bak")
        shutil.copy2(FULL_FILE, bak)
        print(f"[备份] {bak.name} ({bak.stat().st_size / 1e6:.0f} MB)", flush=True)
        print(f"[正式迁移] {FULL_FILE} → {FULL_DIR}")
        migrate(FULL_FILE, FULL_DIR)
        verify(bak, FULL_DIR)
        print("正式迁移完成; 单文件保留为 .singlefile.bak 回滚点")
        return
    ap.error("需要 --target 或 --real")


if __name__ == "__main__":
    main()
