#!/usr/bin/env -S uv run --no-sync
# -*- coding: utf-8 -*-
"""增量补当日行情: 对宇宙内 code 只查询指定日, 追加进 full_daily/ 年分区。

用于日常收盘后补一根日K（fetch_full_market 按 code 增量, 不会自动补已有 code 的新日期）。

设计:
- 内存攒批 + 结尾一次性按年分区原子写(只重写受影响年份, 通常仅 1 个)
- 单只探测: 数据源未发布该日则秒退
- fail-fast: "用户未登录" 返回码 3(命令行退出码同值), 重跑即续

用法:
  命令行:  python scripts/fetch_daily_incremental.py [2026-09-04]
  导入调用: from scripts.fetch_daily_incremental import update_date
            rc = update_date("2026-09-04")   # 0=完成/无需, 3=会话失效
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quant_trading_01.config import get_config  # noqa: E402
from quant_trading_01.data_io import full_daily_codes, load_full_daily, write_full_daily  # noqa: E402

FIELDS = "date,code,close,pbMRQ,turn,amount,peTTM,tradestatus,isST"
KEEP = [
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


def _stage_path(date_s: str) -> Path:
    """Round 72: 断点续传用的 staging（data/fundamental/* 已 gitignore）。"""
    return Path(get_config().paths.fundamental) / (
        f"_stage_daily_{date_s.replace('-', '')}.parquet"
    )


def _stage_load(date_s: str) -> pd.DataFrame:
    p = _stage_path(date_s)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=KEEP)


def _stage_save(date_s: str, df: pd.DataFrame) -> None:
    df.drop_duplicates(subset=["date", "code"], keep="last").to_parquet(
        _stage_path(date_s), index=False
    )


def _merge_and_finish(date_s: str) -> int:
    """把 staging 合并进年分区并清理（写入语义与抓取口径均未变）。"""
    st = _stage_load(date_s)
    if st.empty:
        print(f"无新数据写入 ({date_s})", flush=True)
        return 0
    total = write_full_daily(st)  # 与既有年分区合并去重(语义不变)
    _stage_path(date_s).unlink(missing_ok=True)
    print(f"完成: {date_s} 现共 {total:,} 行 (按年分区原子写)", flush=True)
    return 0


def update_date(date_s: str) -> int:
    """补指定交易日的行情到年分区。返回 0=完成/无需补充, 3=会话失效(可续传)。

    Round 72 改造（用户要求仍走 daily_update 一键路径）:
      * 请求间隔取 `config.fetch.daily_incremental.pause`（默认 1.0s；原硬编码 0.1s
        会把出口 IP 打进 baostock 黑名单，实测 10-08 跑到 1000/3409 被封）；
      * 每 `stage_batch` 只落一次 staging → 重跑跳过已有/staged 的 code（断点续传）；
      * 会话失效/被限流 → **保存 staging 并返回 3**，重跑同一条命令即续；
      * 全部抓完才 `write_full_daily` 合并；抓取字段/过滤/写入语义一律未变。
    """
    import baostock as bs

    inc = get_config().fetch.daily_incremental
    print_every, pause, stage_batch = (
        inc.print_every,
        float(inc.pause),
        int(inc.stage_batch),
    )

    codes = sorted(full_daily_codes())
    have = set(
        load_full_daily(
            columns=["code"], filters=[("date", "==", pd.Timestamp(date_s))]
        )["code"]
    )
    staged = _stage_load(date_s)
    todo = [c for c in codes if c not in have and c not in set(staged["code"])]
    print(
        f"共 {len(codes)} 只, {date_s} 已有 {len(have)}, 已暂存 {len(staged)}, "
        f"待补 {len(todo)} (间隔 {pause}s)",
        flush=True,
    )
    if not todo:
        return _merge_and_finish(date_s)

    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    # 单只探测: 该日数据源是否已发布(避免整市查空)
    probe = bs.query_history_k_data_plus(
        codes[0],
        "date",
        start_date=date_s,
        end_date=date_s,
        frequency="d",
        adjustflag="2",
    )
    if not (probe.error_code == "0" and probe.next()):
        print(f"⚠️ 数据源尚未发布 {date_s} 的行情 (单只探测为空), 跳过本轮", flush=True)
        bs.logout()
        return 0

    pending: list[pd.DataFrame] = []
    fail = 0
    for i, c in enumerate(todo, 1):
        try:
            rs = bs.query_history_k_data_plus(
                c,
                FIELDS,
                start_date=date_s,
                end_date=date_s,
                frequency="d",
                adjustflag="2",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if rows:
                df = pd.DataFrame(rows, columns=rs.fields)
                for col in ["close", "pbMRQ", "turn", "amount", "peTTM"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["date"] = pd.to_datetime(df["date"])
                pending.append(df[df["tradestatus"] == "1"][KEEP])
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "用户未登录" in msg or "10001011" in msg:
                if pending:
                    staged = pd.concat([staged, *pending], ignore_index=True)
                    _stage_save(date_s, staged)
                print(
                    f"⚠️ baostock 会话失效/被限流（已处理 {i - 1} 只）—— 进度已暂存 "
                    f"{len(staged)} 只，**重跑同一条命令即可续传**",
                    flush=True,
                )
                bs.logout()
                return 3
            fail += 1
            if fail <= 10:
                print(f"  {c} 失败: {e}", flush=True)
        if pending and i % stage_batch == 0:
            staged = pd.concat([staged, *pending], ignore_index=True)
            _stage_save(date_s, staged)
            pending = []
        if i % print_every == 0:
            print(
                f"  [{i}/{len(todo)}] 已暂存 {len(staged) + len(pending)} 只 | 失败 {fail}",
                flush=True,
            )
        time.sleep(pause)
    bs.logout()
    if pending:
        staged = pd.concat([staged, *pending], ignore_index=True)
        _stage_save(date_s, staged)
    print(f"本轮暂存 {len(staged)} 只, 失败 {fail}", flush=True)
    return _merge_and_finish(date_s)


def main() -> None:
    date_s = sys.argv[1] if len(sys.argv) > 1 else "2026-09-04"
    sys.exit(update_date(date_s))


if __name__ == "__main__":
    main()
