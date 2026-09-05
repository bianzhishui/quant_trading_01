#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""Round 2 数据抓取：为 9 个因子补数据，全部断点续传。

产出到 data/round2/：
  daily_ext.parquet      长表: date, code, turn, amount, peTTM      (baostock 扩展字段)
  roe.parquet            长表: code, report_date, roe                (akshare 财务)
  margin.parquet         长表: date, code, margin_bal               (沪深两融, 月末采样)
  hsgt.parquet           长表: date, code, hold_ratio               (沪深港通持股占比)

每源独立进度文件，中断重跑自动跳过已完成代码/日期。
用法:
  uv run python research/fetch_round2_data.py --all
  uv run python research/fetch_round2_data.py --baostock   # 只跑某源
  uv run python research/fetch_round2_data.py --roe --limit 20   # 试跑限数
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.dividend_factor import load_all

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "round2"
ROOT_DIR = OUT_DIR.parent.parent
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _codes() -> list[str]:
    """直接从 universe.parquet 取 800 只代码（避免触发 load_all 的慢速 real 价计算）。"""
    u = pd.read_parquet(ROOT_DIR / "data" / "fundamental" / "universe.parquet")
    return [c for c in u["code"].tolist()
            if c.startswith(("sh.6", "sz.0", "sz.3"))]


# ---------------- baostock 扩展日线 ----------------
def _bs_daily(code: str, start: str, end: str) -> pd.DataFrame:
    import baostock as bs
    rs = bs.query_history_k_data_plus(
        code, "date,code,close,turn,amount,peTTM,tradestatus",
        start_date=start, end_date=end, frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(rs.error_msg)
    if not rows:
        return pd.DataFrame(columns=["date", "code", "close", "turn", "amount", "peTTM", "tradestatus"])
    df = pd.DataFrame(rows, columns=rs.fields)
    for c in ["close", "turn", "amount", "peTTM"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_baostock(start: str = "2013-01-01", limit: int | None = None) -> None:
    import baostock as bs
    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    frames: list[pd.DataFrame] = []
    done_f = OUT_DIR / "daily_ext.parquet"
    if done_f.exists():
        frames.append(pd.read_parquet(done_f))
        have = set(pd.read_parquet(done_f)["code"].unique())
    else:
        have = set()
    codes = [c for c in _codes() if c not in have]
    if limit:
        codes = codes[:limit]
    print(f"baostock: 待抓 {len(codes)} 只", flush=True)
    for i, c in enumerate(codes, 1):
        try:
            df = _bs_daily(c, start, "2026-09-03")
            df = df[df["tradestatus"] == "1"]
            frames.append(df[["date", "code", "close", "turn", "amount", "peTTM"]])
            if i % 25 == 0 or i == len(codes):
                tmp = pd.concat(frames, ignore_index=True)
                tmp.to_parquet(done_f)
                print(f"  [{i}/{len(codes)}] 累计 {tmp.shape[0]} 行", flush=True)
        except Exception as e:
            print(f"  {c} 失败: {e}", flush=True)
            time.sleep(1.0)
    bs.logout()
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(done_f)
    print("baostock 完成", flush=True)


# ---------------- ROE 财务 ----------------
def fetch_roe(limit: int | None = None) -> None:
    import akshare as ak
    frames: list[pd.DataFrame] = []
    done_f = OUT_DIR / "roe.parquet"
    if done_f.exists():
        frames.append(pd.read_parquet(done_f))
        have = set(frames[0]["code"].unique())
    else:
        have = set()
    codes = [c for c in _codes() if c not in have]
    if limit:
        codes = codes[:limit]
    print(f"ROE: 待抓 {len(codes)} 只", flush=True)
    for i, c in enumerate(codes, 1):
        try:
            f = ak.stock_financial_analysis_indicator(symbol=c[3:])
            if f is None or f.empty:
                continue
            roe = f[["日期", "净资产收益率(%)"]].copy()
            roe = roe.rename(columns={"日期": "report_date", "净资产收益率(%)": "roe"})
            roe["code"] = c
            roe = roe.dropna(subset=["roe"]).reset_index(drop=True)
            frames.append(roe[["code", "report_date", "roe"]])
            if i % 50 == 0 or i == len(codes):
                tmp = pd.concat(frames, ignore_index=True)
                tmp.to_parquet(done_f)
                print(f"  [{i}/{len(codes)}]", flush=True)
        except Exception as e:
            print(f"  {c} 失败: {e}", flush=True)
            time.sleep(1.0)
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(done_f)
    print("ROE 完成", flush=True)


# ---------------- 两融（月末采样） ----------------
def fetch_margin() -> None:
    import akshare as ak
    close, *_ = load_all()
    sig_days = [d for d in close.index]
    # 用月末交易日
    months = pd.Series(sig_days).groupby(pd.Series(sig_days).dt.to_period("M")).max().tolist()
    frames: list[pd.DataFrame] = []
    done_f = OUT_DIR / "margin.parquet"
    if done_f.exists():
        frames.append(pd.read_parquet(done_f))
        have = set(pd.to_datetime(frames[0]["date"]).dt.strftime("%Y%m%d"))
    else:
        have = set()
    dates = [d for d in months if d.strftime("%Y%m%d") not in have]
    print(f"两融: 待抓 {len(dates)} 个月末", flush=True)
    for i, d in enumerate(dates, 1):
        ymd = d.strftime("%Y%m%d")
        for mkt, fn in [("sse", ak.stock_margin_detail_sse), ("szse", ak.stock_margin_detail_szse)]:
            try:
                df = fn(date=ymd)
                if df is None or df.empty:
                    continue
                if mkt == "sse":
                    df = df.rename(columns={"标的证券代码": "code", "融资余额": "margin_bal"})
                    df["code"] = "sh." + df["code"].astype(str).str.zfill(6)
                else:
                    df = df.rename(columns={"证券代码": "code", "融资余额": "margin_bal"})
                    df["code"] = "sz." + df["code"].astype(str).str.zfill(6)
                df = df[["code", "margin_bal"]].copy()
                df["date"] = pd.Timestamp(d)
                frames.append(df[["date", "code", "margin_bal"]])
            except Exception as e:
                print(f"  {ymd} {mkt} 失败: {e}", flush=True)
                time.sleep(1.0)
        if i % 12 == 0 or i == len(dates):
            pd.concat(frames, ignore_index=True).to_parquet(done_f)
            print(f"  [{i}/{len(dates)}]", flush=True)
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(done_f)
    print("两融 完成", flush=True)


# ---------------- 北向持股 ----------------
def fetch_hsgt(limit: int | None = None) -> None:
    import akshare as ak
    frames: list[pd.DataFrame] = []
    done_f = OUT_DIR / "hsgt.parquet"
    if done_f.exists():
        frames.append(pd.read_parquet(done_f))
        have = set(frames[0]["code"].unique())
    else:
        have = set()
    codes = [c for c in _codes() if c not in have]
    if limit:
        codes = codes[:limit]
    print(f"北向: 待抓 {len(codes)} 只", flush=True)
    for i, c in enumerate(codes, 1):
        try:
            h = ak.stock_hsgt_individual_em(symbol=c[3:])
            if h is None or h.empty:
                continue
            h = h.rename(columns={"持股日期": "date", "持股数量占A股百分比": "hold_ratio"})
            h["date"] = pd.to_datetime(h["date"])
            h["code"] = c
            frames.append(h[["date", "code", "hold_ratio"]])
            if i % 50 == 0 or i == len(codes):
                tmp = pd.concat(frames, ignore_index=True)
                tmp.to_parquet(done_f)
                print(f"  [{i}/{len(codes)}]", flush=True)
        except Exception as e:
            print(f"  {c} 失败: {e}", flush=True)
            time.sleep(1.0)
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(done_f)
    print("北向 完成", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--baostock", action="store_true")
    ap.add_argument("--roe", action="store_true")
    ap.add_argument("--margin", action="store_true")
    ap.add_argument("--hsgt", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.all or a.baostock:
        fetch_baostock(limit=a.limit)
    if a.all or a.roe:
        fetch_roe(limit=a.limit)
    if a.all or a.margin:
        fetch_margin()
    if a.all or a.hsgt:
        fetch_hsgt(limit=a.limit)


if __name__ == "__main__":
    main()
