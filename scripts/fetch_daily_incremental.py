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

import contextlib
import datetime as dt
import io
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
        print(f"  {date_s} 已完整，无需写入", flush=True)
        return 0
    total = write_full_daily(st)  # 与既有年分区合并去重(语义不变)
    _stage_path(date_s).unlink(missing_ok=True)
    print(f"  ✅ {date_s} 完成: 现共 {total:,} 行 (按年分区原子写)", flush=True)
    return 0


def _probe_published(bs, codes: list[str], date_s: str, n: int = 5) -> bool:
    """探测该日行情是否已发布（Round 73）。

    旧写法只探 `codes[0]` —— 实测 227/3409 只 code 在某日常无行情（停牌/退市），
    首只一旦停牌就会误判"未发布"并**整天静默跳过**。
    改为**按步长抽样 n 只**（跨 sh./sz. 分散），**任一有数据**即视为已发布。
    """
    if not codes:
        return False
    # 等距抽样且两端都取到（`codes[::step][:n]` 会跳过近半、且覆盖不到尾部）
    k = min(n, len(codes))
    if k == 1:
        idx = [0]
    else:
        idx = [i * (len(codes) - 1) // (k - 1) for i in range(k)]
    for c in [codes[i] for i in idx]:
        r = bs.query_history_k_data_plus(
            c, "date", start_date=date_s, end_date=date_s, frequency="d", adjustflag="2"
        )
        if r.error_code == "0" and r.next():
            return True
    return False


def _login(bs):
    """登录并静音 baostock 自带的 "login success!" 打印（Round 75）。

    那两行是**库自己** print 的（baostock/login/loginout.py:86,152），不是我们的输出；
    混在流程里让人分不清哪条是自己的。错误信息仍从返回的 error_code/error_msg 读，不丢。
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return bs.login()


def _logout(bs) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        bs.logout()


def _days_txt(days: list[str]) -> str:
    wd = "一二三四五六日"
    return "、".join(f"{d[5:]}({wd[dt.date.fromisoformat(d).weekday()]})" for d in days)


def probe_dates(date_list: list[str]) -> list[str]:
    """一次性探测多日是否已发布（**只登录一次**，Round 75）。返回已发布的日期。"""
    if not date_list:
        return []
    import baostock as bs

    lg = _login(bs)
    if lg.error_code != "0":
        print(
            f"⚠️ baostock 登录被拒（error_code={lg.error_code}: {lg.error_msg}）",
            flush=True,
        )
        return []
    try:
        codes = sorted(full_daily_codes())
        return [d for d in date_list if _probe_published(bs, codes, d)]
    finally:
        _logout(bs)


def fill_days(cands: list[str], label: str = "缺失交易日") -> int:
    """候选自然日：一次探完 → 一行汇总 → 只抓已发布的。返回抓了几个交易日。

    Round 75: 旧写法对每个自然日各跑一次 update_date（各自 login/logout 并打印
    "共 3409 只…待补 3409"），回退 3 天就刷十几行噪音，把"到底要抓哪天、要多久"
    彻底淹没。
    """
    if not cands:
        return 0
    pub = probe_dates(cands)
    if not pub:
        print(f"  {label}: {_days_txt(cands)} 均无行情（非交易日/未发布）", flush=True)
        return 0
    miss = [d for d in cands if d not in pub]
    head = f"{_days_txt(miss)} 无行情 | " if miss else ""
    print(f"  {label}: {head}▶ 需补 {_days_txt(pub)}", flush=True)
    for d in pub:
        update_date(d)
    return len(pub)


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

    # Round 75: **先探测、再算 todo**。旧版顺序反了 —— 先打印"待补 3409 只",
    # 下一行却"跳过本轮", 让人以为要抓全市场。
    lg = _login(bs)
    if lg.error_code != "0":  # Round 73: 不再 assert(会把 daily_update 整个崩掉)
        print(
            f"⚠️ baostock 登录被拒（error_code={lg.error_code}: {lg.error_msg}）"
            f" —— 未发起任何请求；稍后重跑同一条命令即可",
            flush=True,
        )
        return 3
    if not _probe_published(bs, codes, date_s):
        _logout(bs)
        print(f"  {date_s} 无当日行情（非交易日或数据源未发布）", flush=True)
        return 0

    have = set(
        load_full_daily(
            columns=["code"], filters=[("date", "==", pd.Timestamp(date_s))]
        )["code"]
    )
    staged = _stage_load(date_s)
    todo = [c for c in codes if c not in have and c not in set(staged["code"])]
    if not todo:
        _logout(bs)
        return _merge_and_finish(date_s)
    eta = max(1, round(len(todo) * (pause + 0.6) / 60))
    print(
        f"  ▶ 补 {date_s}: 待补 {len(todo)} 只 | 间隔 {pause}s | 预计约 {eta} 分钟",
        flush=True,
    )

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
                _logout(bs)
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
    _logout(bs)
    if pending:
        staged = pd.concat([staged, *pending], ignore_index=True)
        _stage_save(date_s, staged)
    if fail:
        print(f"  （{fail} 只查询失败，已跳过）", flush=True)
    return _merge_and_finish(date_s)


def main() -> None:
    date_s = sys.argv[1] if len(sys.argv) > 1 else "2026-09-04"
    sys.exit(update_date(date_s))


if __name__ == "__main__":
    main()
