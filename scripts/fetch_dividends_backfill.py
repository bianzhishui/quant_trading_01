#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""全市场分红全历史补抓(akshare 东财) → 重建 data/round2/dividends.parquet。

动机: 现 dividends.parquet 仅 2120 只 × 每只 1 条(baostock 稀疏), 质量筛选
      "连续N年分红"需要全历史; 且 1074 只在市股完全缺失。低价股研究需全量。
源: akshare.stock_fhps_detail_em(东财, 一次返回全历史)。
     注意: 退市股接口报错(实测) → 退市股分红如实记录缺失, 研究时用扣非排雷替代。
口径: 仅收 方案进度=="实施分配"; date=除权除息日; cashBeforeTax=每10股派息/10(每股);
      stocksPs=送转总比例/10(每股)。
写: 全量替换 data/round2/dividends.parquet(现有为 baostock 稀疏数据, 无消费方, 替换安全)。
断点: 已写 parquet 的 code 集合; 每 print_every 只原子 flush。
用法: uv run python scripts/fetch_dividends_backfill.py [--limit N] [--codes 600000,600004]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config, load_config
from quant_trading_01.data_io import stock_basic, universe_codes

OUT_COLS = ["code", "date", "cashBeforeTax", "stocksPs"]


def _cfg():
    return get_config()


def fetch_one(code: str) -> pd.DataFrame:
    """抓单只全历史分红(东财); 退市股等接口不支持时抛异常由调用方记录。"""
    import akshare as ak

    symbol = code.split(".")[1]
    df = ak.stock_fhps_detail_em(symbol=symbol)
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OUT_COLS)
    df = df[df["方案进度"] == "实施分配"].copy()
    if len(df) == 0:
        return pd.DataFrame(columns=OUT_COLS)
    date = pd.to_datetime(df["除权除息日"], errors="coerce")
    out = pd.DataFrame(
        {
            "code": code,
            "date": date,
            "cashBeforeTax": pd.to_numeric(df["现金分红-现金分红比例"], errors="coerce")
            / 10.0,
            "stocksPs": pd.to_numeric(df["送转股份-送转总比例"], errors="coerce")
            / 10.0,
        }
    )
    return out.dropna(subset=["date"])


def main() -> None:
    ap = argparse.ArgumentParser(description="全市场分红全历史补抓(akshare 东财)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--codes", default=None, help="逗号分隔 6 位代码, 只抓这些(测试)")
    args = ap.parse_args()

    load_config(args.config)
    cfg = _cfg()
    pause = cfg.fetch.dividends_backfill.pause
    retry = cfg.fetch.dividends_backfill.retry
    print_every = cfg.fetch.dividends_backfill.print_every
    out_path = Path(cfg.fetch.dividends_backfill.out)
    progress_path = Path(cfg.fetch.dividends_backfill.progress)

    # 断点 = 本脚本(东财口径)已完成 code, 与现有 baostock 稀疏数据无关 → 全量重抓后替换
    done_codes = (
        set(json.loads(progress_path.read_text(encoding="utf-8")).get("codes", []))
        if progress_path.exists()
        else set()
    )
    # 东财分红接口对退市股不返回数据(实测报错) → 只抓在市股, 退市股分红如实记录缺失
    sb = stock_basic()
    od = sb["outDate"].astype(str).str.strip()
    delisted_codes = set(sb[~od.isin(["", "NaT", "nan", "None"])]["code"])
    todo = [
        c for c in universe_codes() if c not in done_codes and c not in delisted_codes
    ]
    print(
        f"主板总数 {len(universe_codes())}, 退市(接口不支持) {len(delisted_codes & set(universe_codes()))}, "
        f"东财口径已抓 {len(done_codes)}, 待抓 {len(todo)}",
        flush=True,
    )
    if args.codes:
        want = {c.strip() for c in args.codes.split(",")}
        todo = [c for c in todo if c.split(".")[1] in want]
    if args.limit:
        todo = todo[: args.limit]
    print(f"本次抓取 {len(todo)} 只", flush=True)

    new_rows: list[pd.DataFrame] = []
    n_ok = n_err = 0
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        ok = False
        for attempt in range(retry + 1):
            try:
                df = fetch_one(code)
                ok = True
                break
            except Exception as e:
                if attempt < retry:
                    time.sleep(pause * (2**attempt))
                else:
                    print(f"  ERR {code}: {type(e).__name__} {str(e)[:80]}", flush=True)
                    n_err += 1
        if not ok:
            continue
        if len(df):
            new_rows.append(df)
            n_ok += 1
        if i % print_every == 0:
            # 合并语义: 现有 parquet + 本次新抓, 断点续传不丢已抓
            prev = (
                pd.read_parquet(out_path)
                if out_path.exists()
                else pd.DataFrame(columns=OUT_COLS)
            )
            all_df = pd.concat([prev] + new_rows, ignore_index=True).drop_duplicates(
                subset=["code", "date"]
            )
            tmp = out_path.with_suffix(".parquet.tmp")
            all_df.to_parquet(tmp, index=False)
            tmp.replace(out_path)
            progress_path.write_text(
                json.dumps({"codes": sorted(set(all_df["code"]))}), encoding="utf-8"
            )
            print(
                f"  [{i}/{len(todo)}] 累计 {len(all_df)} 行 / {len(set(all_df['code']))} 只, "
                f"失败 {n_err}, 耗时 {time.time() - t0:.0f}s",
                flush=True,
            )
        time.sleep(pause)

    if new_rows:
        prev = (
            pd.read_parquet(out_path)
            if out_path.exists()
            else pd.DataFrame(columns=OUT_COLS)
        )
        all_df = pd.concat([prev] + new_rows, ignore_index=True)
        all_df = all_df.drop_duplicates(subset=["code", "date"]).sort_values(
            ["code", "date"]
        )
        tmp = out_path.with_suffix(".parquet.tmp")
        all_df.to_parquet(tmp, index=False)
        tmp.replace(out_path)
        progress_path.write_text(
            json.dumps({"codes": sorted(set(all_df["code"]))}), encoding="utf-8"
        )
    print(f"完成: 补 {n_ok}, 失败 {n_err}", flush=True)


if __name__ == "__main__":
    main()
