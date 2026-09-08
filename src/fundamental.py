# -*- coding: utf-8 -*-
"""基本面数据管线：baostock → parquet，支持断点续传。

下载内容（对应当前沪深300+中证500成分，约800只）：
  1. 成分列表 + 股票基本信息(ipoDate/type/status)  → universe.parquet / stock_basic.parquet
  2. 全历史日线 close/pbMRQ/tradestatus/isST       → daily_*.parquet 分片
  3. 分年度现金分红(每股税前, 按实施年聚合)         → dividends_*.parquet 分片

断点续传：data/fundamental/state.json 记录已完成代码；
每 100 只落一个分片，中断后重跑自动跳过已完成部分。

用法:
  uv run python -m src.fundamental status          # 查看进度
  uv run python -m src.fundamental download --limit 3   # 试运行3只(测速)
  uv run python -m src.fundamental download        # 全量(后台1~2h)
  uv run python -m src.fundamental merge           # 合并分片为最终表
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import baostock as bs
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "fundamental"
STATE_FILE = DATA_DIR / "state.json"
SHARD_SIZE = 100
DIV_YEARS = list(range(2011, 2027))
DAILY_FIELDS = "date,code,close,pbMRQ,tradestatus,isST"


# ---------------- 基础设施 ----------------
def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"daily_done": [], "div_done": {}, "shards": []}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _ensure_session(max_attempts: int = 6) -> None:
    """登录并**验证会话可用**。

    baostock 服务端偶发"login 返回 success 但会话未建立"(报 用户未登录),
    高频使用后更明显。策略: 登录 → 1行验证查询 → 指数退避重试。
    """
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


def _logged():
    """装饰器: 确保函数运行期间处于 baostock 已验证登录态。"""

    def deco(fn):
        def wrapper(*a, **kw):
            _ensure_session()
            try:
                return fn(*a, **kw)
            finally:
                try:
                    bs.logout()
                except Exception:
                    pass

        return wrapper

    return deco


def _rows(rs) -> list[list]:
    out = []
    while rs.error_code == "0" and rs.next():
        out.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"查询失败: {rs.error_msg}")
    return out


def _retry(fn, tries: int = 4, pause: float = 3.0):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    重试{i + 1}/{tries - 1}: {e}")
            time.sleep(pause)
            try:  # 会话可能已失效(报"用户未登录"时), 重建会话
                _ensure_session()
            except Exception:
                pass


# ---------------- 数据获取 ----------------
def get_universe() -> pd.DataFrame:
    """当前沪深300+中证500成分并集。注意: 返回首列是 updateDate, 必须按名取列。"""
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
    df.to_parquet(DATA_DIR / "universe.parquet")
    print(f"成分股: {len(df)} 只 (hs300+zz500 并集)")
    return df


def get_stock_basic() -> pd.DataFrame:
    """全部股票基本信息(一次全表), 过滤出股票类型。"""
    rs = bs.query_stock_basic()
    rows = _rows(rs)
    df = pd.DataFrame(rows, columns=list(rs.fields))
    df = df[df["type"] == "1"]  # 1=股票
    df.to_parquet(DATA_DIR / "stock_basic.parquet")
    print(f"stock_basic: {len(df)} 只股票")
    return df


def download_daily(code: str, start: str, end: str) -> pd.DataFrame:
    rows = _rows(
        bs.query_history_k_data_plus(
            code,
            DAILY_FIELDS,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="2",
        )
    )
    df = pd.DataFrame(rows, columns=DAILY_FIELDS.split(","))
    for col in ("close", "pbMRQ"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def download_dividend_year(code: str, year: int) -> pd.DataFrame:
    rows = _rows(bs.query_dividend_data(code=code, year=str(year), yearType="operate"))
    if not rows:
        return pd.DataFrame(columns=["code", "year", "cash_ps_total", "n_records"])
    df = pd.DataFrame(
        rows,
        columns=bs.query_dividend_data(
            code=code, year=str(year), yearType="operate"
        ).fields,
    )
    cash = pd.to_numeric(df["dividCashPsBeforeTax"], errors="coerce").fillna(0.0)
    return pd.DataFrame(
        {
            "code": [code],
            "year": [year],
            "cash_ps_total": [float(cash.sum())],
            "n_records": [len(df)],
        }
    )


# ---------------- 主流程 ----------------
def download_adjust_factor(code: str) -> pd.DataFrame:
    # 从2005年起查: 价格数据从2010年起, 需要此前最后一次事件的因子水平,
    # 否则2010年初~首个事件日的因子缺失
    rs = bs.query_adjust_factor(
        code=code, start_date="2005-01-01", end_date="2026-12-31"
    )
    rows = _rows(rs)
    df = pd.DataFrame(rows, columns=list(rs.fields))
    for col in ("foreAdjustFactor", "backAdjustFactor", "adjustFactor"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@_logged()
def download_adjust_factors(limit: int | None = None) -> None:
    """全池复权因子(每股1次调用) → adjust_factor.parquet。"""
    out = DATA_DIR / "adjust_factor.parquet"
    if out.exists():
        print("adjust_factor.parquet 已存在, 跳过 (删除后可重下)")
        return
    uni = pd.read_parquet(DATA_DIR / "universe.parquet")
    codes = uni["code"].tolist()
    if limit:
        codes = codes[:limit]
    print(f"[复权因子] 共 {len(codes)} 只")
    buf, ok, t0 = [], [], time.time()
    for n, code in enumerate(codes, 1):
        try:
            df = _retry(lambda: download_adjust_factor(code))
            if len(df):
                buf.append(df)
            ok.append(code)
        except Exception as e:
            print(f"    {code} 复权因子失败(跳过): {e}")
        if n % 100 == 0 or n == len(codes):
            speed = n / max(time.time() - t0, 1)
            eta = (len(codes) - n) / max(speed, 0.1) / 60
            print(
                f"    复权因子 {n}/{len(codes)} ({speed:.1f}只/秒, 剩余约{eta:.0f}分钟)"
            )
    if buf:
        pd.concat(buf, ignore_index=True).to_parquet(out)
        print(f"已保存 {out.name}: {sum(len(b) for b in buf)} 行")


@_logged()
def download(limit: int | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()

    print("[1/4] 成分与基本信息...")
    uni = _retry(get_universe)
    basic = _retry(get_stock_basic)
    codes = uni["code"].tolist()
    if limit:
        codes = codes[:limit]

    uni = uni.merge(basic[["code", "ipoDate", "status"]], on="code", how="left")
    uni.to_parquet(DATA_DIR / "universe.parquet")

    # ---- 日线 ----
    todo_daily = [c for c in codes if c not in set(state["daily_done"])]
    print(f"[2/4] 日线: 待下载 {len(todo_daily)}/{len(codes)}")
    buf, ok, t0 = [], [], time.time()
    for n, code in enumerate(todo_daily, 1):
        try:
            df = _retry(lambda: download_daily(code, "2010-01-01", "2026-12-31"))
            buf.append(df)
            ok.append(code)
        except Exception as e:
            print(f"    {code} 日线失败(跳过): {e}")
        if len(buf) >= SHARD_SIZE or n == len(todo_daily):
            if buf:
                k = len(state["shards"])
                pd.concat(buf, ignore_index=True).to_parquet(
                    DATA_DIR / f"daily_shard_{k:03d}.parquet"
                )
                state["daily_done"] += ok
                state["shards"].append(f"daily_shard_{k:03d}.parquet")
                _save_state(state)
                buf, ok = [], []
            speed = n / max(time.time() - t0, 1)
            eta = (len(todo_daily) - n) / max(speed, 0.1) / 60
            print(
                f"    日线 {n}/{len(todo_daily)}  ({speed:.1f}只/秒, "
                f"剩余约{eta:.0f}分钟)"
            )

    # ---- 分红 ----
    div_done = state.get("div_done", {})
    todo_div = [c for c in codes if c not in div_done]
    print(f"[3/4] 分红({len(DIV_YEARS)}年/只): 待下载 {len(todo_div)}/{len(codes)}")
    buf, ok, t0 = [], [], time.time()
    for n, code in enumerate(todo_div, 1):
        years_df = []
        try:
            for y in DIV_YEARS:
                years_df.append(_retry(lambda y=y: download_dividend_year(code, y)))
            buf.append(pd.concat(years_df, ignore_index=True))
            ok.append(code)
        except Exception as e:
            print(f"    {code} 分红失败(跳过): {e}")
        if len(buf) >= SHARD_SIZE or n == len(todo_div):
            if buf:
                k = len(state["shards"])
                pd.concat(buf, ignore_index=True).to_parquet(
                    DATA_DIR / f"dividends_shard_{k:03d}.parquet"
                )
                state["shards"].append(f"dividends_shard_{k:03d}.parquet")
                for c in ok:
                    div_done[c] = DIV_YEARS[-1]
                state["div_done"] = div_done
                _save_state(state)
                buf, ok = [], []
            speed = n / max(time.time() - t0, 1)
            eta = (len(todo_div) - n) / max(speed, 0.1) / 60
            print(
                f"    分红 {n}/{len(todo_div)}  ({speed:.1f}只/秒, 剩余约{eta:.0f}分钟)"
            )

    print("[4/4] 完成。运行 merge 生成最终表。")


def merge() -> None:
    """合并分片 → daily.parquet / dividends.parquet。（只读本地文件，无需登录）"""
    daily, divid = [], []
    for f in sorted(DATA_DIR.glob("daily_shard_*.parquet")):
        daily.append(pd.read_parquet(f))
    for f in sorted(DATA_DIR.glob("dividends_shard_*.parquet")):
        divid.append(pd.read_parquet(f))
    if daily:
        d = pd.concat(daily, ignore_index=True).drop_duplicates(["date", "code"])
        d.to_parquet(DATA_DIR / "daily.parquet")
        print(f"daily.parquet: {len(d)} 行, {d['code'].nunique()} 只")
    if divid:
        v = pd.concat(divid, ignore_index=True).drop_duplicates(["code", "year"])
        v.to_parquet(DATA_DIR / "dividends.parquet")
        print(f"dividends.parquet: {len(v)} 行, {v['code'].nunique()} 只")


def status() -> None:
    state = _load_state()
    print(f"日线已完成: {len(state['daily_done'])} 只")
    print(f"分红已完成: {len(state.get('div_done', {}))} 只")
    print(f"分片数: {len(state['shards'])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="基本面数据管线")
    ap.add_argument("cmd", choices=["download", "merge", "status", "adjust"])
    ap.add_argument("--limit", type=int, default=None, help="限制下载股票数(试运行)")
    args = ap.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "download":
        download(limit=args.limit)
    elif args.cmd == "merge":
        merge()
    elif args.cmd == "adjust":
        download_adjust_factors(limit=args.limit)
    else:
        status()
