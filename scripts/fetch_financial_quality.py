#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""全市场质量财务补抓(akshare 同花顺摘要) → data/round2/financial_quality.parquet。

动机: 低价股"质量筛选"研究需要 净利润/扣非净利润/每股经营现金流/ROE/资产负债率;
      现 roe.parquet 仅覆盖 800 只, 三大报表全缺 → 本脚本补齐主板 3486 只(含退市股)。
源: akshare.stock_financial_abstract_ths(同花顺, 按报告期) —— 正常股+退市股都通(实测)。
解析: 同花顺返回 object 字符串('173.61亿'/'-2.08亿'/'3.28%'/'--') → float 统一解析。
输出: 长表 code/report_date/净利润/扣非净利润/营业总收入/基本每股收益/每股净资产/
      每股经营现金流/净资产收益率/资产负债率/销售净利率 (float64, 单位: 元/元/元/元/元/元/元/1/1/1)。
断点: 已写 parquet 的 (code) 集合自动跳过; 每 print_every 只原子 flush 一次。
用法: uv run python scripts/fetch_financial_quality.py [--limit N] [--codes 600000,600687]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_trading_01.config import get_config, load_config
from quant_trading_01.data_io import universe_codes

# 同花顺摘要列 → 统一输出列（顺序即输出列序）
FIELDS = [
    "净利润",
    "扣非净利润",
    "营业总收入",
    "基本每股收益",
    "每股净资产",
    "每股经营现金流",
    "净资产收益率",
    "资产负债率",
    "销售净利率",
]
OUT_COLS = [
    "code",
    "report_date",
    "net_profit",
    "deducted_profit",
    "revenue",
    "eps",
    "bps",
    "ocf_ps",
    "roe",
    "debt_ratio",
    "net_margin",
]


def _cfg():
    return get_config()


def _num(x) -> float:
    """同花顺字符串 → float: '173.61亿'→1.7361e10, '-2.08亿'→-2.08e8, '3.28%'→0.0328, '--'→nan。"""
    if x is None:
        return np.nan
    s = str(x).strip()
    if s in ("", "--", "-", "nan", "NaN", "None", "null"):
        return np.nan
    neg = False
    if s.startswith("-"):
        neg, s = True, s[1:]
    s = s.replace(",", "")
    mult = 1.0
    if s.endswith("亿"):
        mult, s = 1e8, s[:-1]
    elif s.endswith("万"):
        mult, s = 1e4, s[:-1]
    if s.endswith("%"):
        mult, s = mult / 100.0, s[:-1]
    try:
        v = float(s) * mult
    except ValueError:
        return np.nan
    return -v if neg else v


def fetch_one(code: str) -> pd.DataFrame:
    """抓单只(含退市)质量财务, 返回长表(OUT_COLS); 失败抛异常由调用方重试。

    个别股票同花顺返回列缺失(如 KeyError '扣非净利润') → 缺列字段填 NaN 容错。
    """
    import akshare as ak

    symbol = code.split(".")[1]
    df = ak.stock_financial_abstract_ths(symbol=symbol, indicator="按报告期")
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OUT_COLS)
    cols = {}
    for oc, c in zip(OUT_COLS[2:], FIELDS):
        cols[oc] = [_num(v) for v in df[c]] if c in df.columns else np.nan
    out = pd.DataFrame(
        {
            "code": code,
            "report_date": pd.to_datetime(df["报告期"].astype(str), errors="coerce"),
            **cols,
        }
    )
    return out.dropna(subset=["report_date"])


def load_existing() -> pd.DataFrame:
    p = Path(_cfg().fetch.financial_quality.out)
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame(columns=OUT_COLS)


def main() -> None:
    ap = argparse.ArgumentParser(description="全市场质量财务补抓(akshare 同花顺)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--limit", type=int, default=None, help="只抓前 N 只(测试)")
    ap.add_argument("--codes", default=None, help="逗号分隔 6 位代码, 只抓这些(测试)")
    args = ap.parse_args()

    load_config(args.config)
    cfg = _cfg()
    pause = cfg.fetch.financial_quality.pause
    retry = cfg.fetch.financial_quality.retry
    print_every = cfg.fetch.financial_quality.print_every
    out_path = Path(cfg.fetch.financial_quality.out)
    progress_path = Path(cfg.fetch.financial_quality.progress)

    existing = load_existing()
    done_codes = set(existing["code"]) if len(existing) else set()
    todo = [c for c in universe_codes() if c not in done_codes]
    print(
        f"主板总数 {len(universe_codes())}, 已抓 {len(done_codes)}, 待抓 {len(todo)}",
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
                    print(
                        f"  ERR {code}: {type(e).__name__} {str(e)[:100]}",
                        flush=True,
                    )
                    n_err += 1
        if not ok:
            continue
        new_rows.append(df)
        n_ok += 1
        if i % print_every == 0 and new_rows:
            all_df = pd.concat([existing] + new_rows, ignore_index=True)
            all_df = all_df.drop_duplicates(subset=["code", "report_date"])
            tmp = out_path.with_suffix(".parquet.tmp")
            all_df.to_parquet(tmp, index=False)
            tmp.replace(out_path)
            progress_path.write_text(
                json.dumps(
                    {
                        "n": len(set(all_df["code"])),
                        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                ),
                encoding="utf-8",
            )
            print(
                f"  [{i}/{len(todo)}] 累计 {len(all_df)} 行 / {len(set(all_df['code']))} 只, "
                f"失败 {n_err}, 耗时 {time.time() - t0:.0f}s",
                flush=True,
            )
        time.sleep(pause)

    if new_rows:
        all_df = pd.concat([existing] + new_rows, ignore_index=True)
        all_df = all_df.drop_duplicates(subset=["code", "report_date"]).sort_values(
            ["code", "report_date"]
        )
        tmp = out_path.with_suffix(".parquet.tmp")
        all_df.to_parquet(tmp, index=False)
        tmp.replace(out_path)
        progress_path.write_text(
            json.dumps(
                {
                    "n": len(set(all_df["code"])),
                    "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            ),
            encoding="utf-8",
        )
    print(f"完成: 补 {n_ok}, 失败 {n_err}", flush=True)


if __name__ == "__main__":
    main()
