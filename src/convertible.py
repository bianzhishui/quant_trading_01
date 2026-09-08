#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""可转债数据管线 — 东财价值分析历史 × 全历史发行名单。

download: bond_zh_cov 快照(universe) + 逐债 bond_zh_cov_value_analysis
          [日期,收盘价,纯债价值,转股价值,纯债溢价率,转股溢价率], 断点续传
merge:    分片 → value_analysis.parquet (长表)
status:   进度报告

用法: uv run python -m src.convertible download [--limit N] | merge | status
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import akshare as ak

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "convertible"
SHARD_DIR = DATA_DIR / "shards"
SHARD_SIZE = 50
SLEEP = 0.35  # 限速: 东财 datacenter 端点礼貌节奏

_COLS = ["date", "close", "pb_value", "conv_value", "pb_premium", "premium", "code"]


def _state_path() -> Path:
    return DATA_DIR / "state.json"


def _load_state() -> dict:
    if _state_path().exists():
        return json.loads(_state_path().read_text())
    return {"done": []}


def _save_state(st: dict) -> None:
    _state_path().write_text(json.dumps(st, ensure_ascii=False))


def get_universe() -> pd.DataFrame:
    """东财发行快照 → universe.parquet (全历史名单, 含退市/未上市)。"""
    df = ak.bond_zh_cov()
    keep = {
        "债券代码": "code",
        "债券简称": "name",
        "申购日期": "issue_date",
        "上市时间": "list_date",
        "正股代码": "stock_code",
        "正股简称": "stock_name",
        "发行规模": "issue_size",
        "信用评级": "rating",
    }
    out = df[list(keep)].rename(columns=keep)
    out["issue_date"] = pd.to_datetime(out["issue_date"], errors="coerce")
    out["list_date"] = pd.to_datetime(out["list_date"], errors="coerce")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(DATA_DIR / "universe.parquet")
    return out


def download_one(code: str) -> pd.DataFrame:
    va = ak.bond_zh_cov_value_analysis(symbol=code)
    va = va.rename(
        columns={
            "日期": "date",
            "收盘价": "close",
            "纯债价值": "pb_value",
            "转股价值": "conv_value",
            "纯债溢价率": "pb_premium",
            "转股溢价率": "premium",
        }
    )
    va["date"] = pd.to_datetime(va["date"])
    for c in ("close", "pb_value", "conv_value", "pb_premium", "premium"):
        va[c] = pd.to_numeric(va[c], errors="coerce")
    va = va.dropna(subset=["close"])  # 上市前/退市后的空行
    va["code"] = code
    return va[_COLS]


def download(limit: int | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHARD_DIR.mkdir(exist_ok=True)
    uni_path = DATA_DIR / "universe.parquet"
    if uni_path.exists():
        uni = pd.read_parquet(uni_path)
    else:
        uni = get_universe()
        print(f"快照已保存: {len(uni)} 只")
    codes = uni["code"].tolist()
    st = _load_state()
    done = set(st["done"])
    pending = [c for c in codes if c not in done]
    if limit:
        pending = pending[:limit]
    print(f"[转债价值分析] 总 {len(codes)}, 已完成 {len(done)}, 待下载 {len(pending)}")
    buf: list[pd.DataFrame] = []
    t0, ok_n = time.time(), 0
    for n, code in enumerate(pending, 1):
        for attempt in range(3):
            try:
                df = download_one(code)
                if len(df):
                    buf.append(df)
                done.add(code)
                ok_n += 1
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    {code} 3次失败跳过: {str(e)[:80]}")
                else:
                    time.sleep(2.0 * (attempt + 1))
        if len(buf) >= SHARD_SIZE:
            idx = len(list(SHARD_DIR.glob("batch_*.parquet")))
            pd.concat(buf, ignore_index=True).to_parquet(
                SHARD_DIR / f"batch_{idx:03d}.parquet"
            )
            buf = []
            st["done"] = sorted(done)
            _save_state(st)
        if n % 50 == 0 or n == len(pending):
            speed = n / max(time.time() - t0, 1)
            eta = (len(pending) - n) / max(speed, 0.1) / 60
            print(f"    {n}/{len(pending)} ({speed:.1f}只/秒, 剩余约{eta:.0f}分钟)")
        time.sleep(SLEEP)
    if buf:
        idx = len(list(SHARD_DIR.glob("batch_*.parquet")))
        pd.concat(buf, ignore_index=True).to_parquet(
            SHARD_DIR / f"batch_{idx:03d}.parquet"
        )
    st["done"] = sorted(done)
    _save_state(st)
    print(f"完成: 本次成功 {ok_n}/{len(pending)}, 累计 {len(done)}")


def merge() -> None:
    shards = sorted(SHARD_DIR.glob("batch_*.parquet"))
    if not shards:
        print("无分片可合并")
        return
    df = pd.concat([pd.read_parquet(p) for p in shards], ignore_index=True)
    df = df.drop_duplicates(subset=["code", "date"]).sort_values(["code", "date"])
    n0, b0 = len(df), df["code"].nunique()
    # QC1: 老式分离交易债(404/115/126开头)在东财为垃圾数据(价格0.001~155乱跳), 全部剔除
    df = df[~df["code"].str.startswith(("404", "115", "126"))]
    # QC2: 面值100的品种, <10元必为数据错误(真实 distressed 底部≈18元, 保留)
    df = df[df["close"] >= 10]
    n1, b1 = len(df), df["code"].nunique()
    print(f"QC: 剔除老式分离债/垃圾行 {b0 - b1} 只, {n0 - n1:,} 行")
    out = DATA_DIR / "value_analysis.parquet"
    df.to_parquet(out)
    uni = pd.read_parquet(DATA_DIR / "universe.parquet")
    print(
        f"已合并 {out.name}: {len(df):,} 行, {df['code'].nunique()} 只, "
        f"{df['date'].min().date()} ~ {df['date'].max().date()}"
    )
    # 质检: 违约退市债样本 123015(蓝盾) 必须在且尾部完整
    d = df[df["code"] == "123015"]
    if len(d):
        print(
            f"质检 123015(蓝盾,违约退市): {len(d)} 行, "
            f"至 {d['date'].max().date()}, 最后收盘 {d['close'].iloc[-1]} (预期≈26.9)"
        )
    else:
        print("质检 警告: 123015 缺失!")
    missing = set(uni["code"]) - set(df["code"])
    print(f"快照中有而序列缺失: {len(missing)} 只 (未上市/未发行属正常)")


def status() -> None:
    st = _load_state()
    uni_path = DATA_DIR / "universe.parquet"
    total = len(pd.read_parquet(uni_path)) if uni_path.exists() else "?"
    shards = sorted(SHARD_DIR.glob("batch_*.parquet")) if SHARD_DIR.exists() else []
    merged = DATA_DIR / "value_analysis.parquet"
    print(
        f"universe: {total} 只 | state 已完成: {len(st['done'])} | "
        f"分片: {len(shards)} 个 | 合并文件: {'有' if merged.exists() else '无'}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="可转债数据管线")
    ap.add_argument("cmd", choices=["download", "merge", "status"])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "download":
        download(limit=args.limit)
    elif args.cmd == "merge":
        merge()
    else:
        status()


if __name__ == "__main__":
    main()
