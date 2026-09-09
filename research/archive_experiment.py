#!/usr/bin/env python3
"""探索归档工具：把已结束探索从 research/ 移入 archive/experiments/。

用法:
    .venv/bin/python research/archive_experiment.py <脚本名或单元名> [--dry-run]
    .venv/bin/python research/archive_experiment.py round16_crowding_timing --dry-run

流程（设计见 docs/archive_design_plan.md §8）:
    1. 解析依赖闭包（research.X import 递归展开，命中白名单即停）
    2. git mv 脚本 + plan 文档 → archive/experiments/<unit>/
    3. 改写闭包内互 import（research.X → X，同目录可导入）
    4. 搬结论输出（output/ 前缀匹配 csv/png）并 git add 入库
    5. 生成单元 README.md + 更新 archive/INDEX.md
    6. 校验：py_compile + 静态 import 目标检查；失败自动回滚
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date

ARCHIVE = "archive/experiments"

# 永不归档白名单：生产链 + 共享基座（被生产链依赖，脚本留位 research/）
KEEP = {
    "data_io",
    "fetch_corporate_actions",
    "fetch_daily_incremental",
    "fetch_full_industry",
    "fetch_full_market",
    "fetch_round2_data",
    "migrate_full_daily_partitions",
    "paper_live",
    "paper_trade",
    "daily_update",
    "plot_daily_gains",
    "scenario_ytd",
    "export_holdings",
    "reversal_factor",  # 基座：paper_live/paper_trade 依赖 ew_nav/build_pool
    "dividend_factor",  # 基座：paper_trade 依赖 month_last_days/metrics
}

# 归档单元表：脚本/plan/输出前缀/状态/结论摘要（结论来自 plan §0 与 README 探索表）
UNITS = [
    {
        "name": "screen01_factor_screen",
        "scripts": ["factor_screen_round1.py"],
        "plans": ["factor_screen_round1_plan.md"],
        "outputs": ["factor_screen_round1", "factor_corr_crosssec", "factor_corr_ic"],
        "status": "🟡 部分通过",
        "conclusion": "Round 1 批量筛选：中期动量因子判定部分通过，入组合观察名单",
    },
    {
        "name": "screen02_factor_screen",
        "scripts": ["factor_screen_round2.py"],
        "plans": ["factor_screen_round2_plan.md"],
        "outputs": [
            "factor_screen_round2",
            "factor_corr_crosssec_round2",
            "factor_corr_ic_round2",
        ],
        "status": "✅ 通过并入",
        "conclusion": "Round 2 批量筛选：Amihud 非流动性首个全通过因子（+7.3pp）",
    },
    {
        "name": "round03_combination",
        "scripts": ["factor_round3_combination.py"],
        "plans": ["factor_round3_combination_plan.md"],
        "outputs": ["factor_round3"],
        "status": "✅ 通过并入",
        "conclusion": "Amihud+中期动量等权组合确立为策略主体（+9.8pp，夏普0.91）",
    },
    {
        "name": "round04_risk_breakers",
        "scripts": [
            "factor_round4.py",
            "factor_round4b.py",
            "factor_round4c.py",
            "factor_round4d.py",
        ],
        "plans": [
            "factor_round4_plan.md",
            "factor_round4b_drawdown_breaker_plan.md",
            "factor_round4c_trend_breaker_plan.md",
            "factor_round4d_dual_breaker_plan.md",
        ],
        "outputs": [
            "factor_round4",
            "factor_round4b",
            "factor_round4c",
            "factor_round4d",
        ],
        "status": "🟡 部分通过",
        "conclusion": (
            "风控系列：4b 回撤熔断/4c 均线择时正交互补（部分通过）；"
            "4d 双熔断否决（防守过度，股灾恢复期钳制踏空）"
        ),
    },
    {
        "name": "round05_industry_neutral",
        "scripts": ["factor_round5.py"],
        "plans": ["factor_round5_industry_neutral_plan.md"],
        "outputs": ["factor_round5"],
        "status": "✅ 通过并入",
        "conclusion": "R5 行业中性化升级为策略主体（行业内 alpha 真实存在）",
    },
    {
        "name": "round06_r5_ma",
        "scripts": ["factor_round6.py"],
        "plans": ["factor_round6_r5_ma_plan.md"],
        "outputs": ["factor_round6"],
        "status": "❌ 已否决",
        "conclusion": "R5+4c 均线择时叠加否决（择时代价占比过高）",
    },
    {
        "name": "round07_fullmarket",
        "scripts": ["factor_round7_fullmarket_validate.py"],
        "plans": ["factor_round7_fullmarket_validate_plan.md"],
        "outputs": ["factor_round7"],
        "status": "✅ 通过并入",
        "conclusion": "全市场扩池 R5：幸存者偏差仅 1.1pp，泛化成立",
    },
    {
        "name": "round08_live_validation",
        "scripts": ["factor_round8_live_validation.py"],
        "plans": ["factor_round8_live_validation_plan.md"],
        "outputs": ["factor_round8"],
        "status": "✅ 通过并入",
        "conclusion": "实盘化验证：全口径成本下超额 +2.56pp，可执行",
    },
    {
        "name": "round09_holdings_count",
        "scripts": ["factor_round9_holdings_count.py"],
        "plans": ["factor_round9_holdings_count_plan.md"],
        "outputs": ["factor_round9"],
        "status": "⏸ 搁置",
        "conclusion": "持仓数量敏感度实验：575 并非必须，结论见 plan §0 表",
    },
    {
        "name": "round11_fullbuy",
        "scripts": ["factor_round11_fullbuy.py"],
        "plans": ["factor_round11_fullbuy_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": "全选满仓变体否决（换手 2.2 倍 + 规则脆弱）",
    },
    {
        "name": "round12_15_concentrated",
        "scripts": [
            "factor_round12_concentrated.py",
            "factor_round13_concentrated_fill.py",
            "factor_round14_concentrated_industry.py",
            "factor_round15_20w.py",
        ],
        "plans": [
            "factor_round12_concentrated_plan.md",
            "factor_round13_concentrated_fill_plan.md",
            "factor_round14_concentrated_industry_plan.md",
            "factor_round15_20w_plan.md",
        ],
        "outputs": [],
        "status": "⏸ 搁置",
        "conclusion": (
            "小资金规模研究收束：20万不建议（费用吃光）/ 60万可行下限(+3.4~3.6pp) / "
            "300万最优起点(+4.43pp) / 600万效率饱和(+4.72pp)"
        ),
    },
    {
        "name": "round16_crowding_timing",
        "scripts": ["factor_round16_crowding_timing.py"],
        "plans": ["factor_round16_crowding_timing_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": "拥挤度极值择时否决（风控五轮收束：压不住回撤且牺牲超额）",
    },
    {
        "name": "reversal_short_term",
        "scripts": [],  # reversal_factor.py 是共享基座，脚本留位 research/
        "plans": ["reversal_factor_plan.md"],
        "outputs": ["reversal_factor"],
        "status": "❌ 已否决",
        "conclusion": "短期反转否决（IC 不足 + 15bp 成本致命）",
    },
    {
        "name": "dividend_factor",
        "scripts": [],  # dividend_factor.py 是共享基座，脚本留位 research/
        "plans": ["dividend_factor_plan.md"],
        "outputs": ["dividend_factor"],
        "status": "⏸ 搁置",
        "conclusion": "高股息四组对照：按失败处置协议记录（结论见 plan §0）",
    },
    {
        "name": "convertible_double_low",
        "scripts": ["convertible_double_low.py"],
        "plans": ["convertible_double_low_plan.md"],
        "outputs": ["convertible_double_low"],
        "status": "⏸ 搁置",
        "conclusion": "可转债双低轮动（独立方向，结论见 plan §0）",
    },
    {
        "name": "ew_base",
        "scripts": ["ew_base.py"],
        "plans": ["ew_base_plan.md", "ew_base_execution.md"],
        "outputs": ["ew_base"],
        "status": "⏸ 搁置",
        "conclusion": "等权底仓可行性评估（轻量，结论见 plan §0）",
    },
    {
        "name": "etf_exploration",
        "scripts": ["etf_momentum.py", "etf_lowvol_replica.py", "etf_candidates.py"],
        "plans": ["etf_momentum_plan.md"],
        "outputs": ["etf_momentum", "etf_lowvol_replica"],
        "status": "⏸ 搁置",
        "conclusion": "ETF 动量/低波轮动与候选研究（独立方向，失败处置见 plan §0）",
    },
    {
        "name": "weekday_effect",
        "scripts": ["weekday_effect.py"],
        "plans": [],
        "outputs": ["weekday_effect"],
        "status": "⏸ 搁置",
        "conclusion": "周内效应检验（独立方向，无 plan 文档）",
    },
    {
        "name": "grid_demo",
        "scripts": ["grid_demo.py"],
        "plans": [],
        "outputs": [],
        "status": "🛠 工具/演示",
        "conclusion": "网格交易演示（无 plan 文档）",
    },
    {
        "name": "yearly_breakdown",
        "scripts": ["yearly_breakdown.py"],
        "plans": [],
        "outputs": [],
        "status": "🛠 工具/演示",
        "conclusion": "年度收益分解分析工具（无 plan 文档）",
    },
    {
        "name": "round19_concentrated200",
        "scripts": ["factor_round19_concentrated200.py"],
        "plans": ["factor_round19_concentrated200_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": (
            "60万 前200+满仓补买 +2.96pp/82%用/2.32%费 未达标; 集中度补买曲线闭合"
            " 100(+3.59)>150(+3.41)>200(+2.96), 最优仍为前100+补买; 补买对前200仅堆仓位不增超额"
        ),
    },
    {
        "name": "round20_extreme_scenario",
        "scripts": ["extreme_scenario.py"],
        "plans": ["factor_round20_extreme_scenario_plan.md"],
        "outputs": [],
        "status": "🛠 工具/演示",
        "conclusion": (
            "极端行情回放演练(4场景): 满配极端段-20~-50%级回撤(印证风控收束); "
            "60万现金缓冲减震约一半(S1差18pp/S3差17pp); S4扛住31-41交易日恢复全年+4~6%; "
            "S3微盘危机唯一跑输大盘——实操指南入运营手册§10.4"
        ),
    },
    {
        "name": "round21_tier1_screen",
        "scripts": ["factor_round21_tier1_screen.py"],
        "plans": ["factor_round21_tier1_screen_plan.md"],
        "outputs": [],
        "status": "🟡 部分通过",
        "conclusion": (
            "梯队一4因子筛选: 价格水平(低价股)单因子4/4通过(+3.0pp@15bp/换手1.1/三段全正/"
            "与Amihud截面-0.19)进候选池, 但Round22组合验证否决并入; "
            "低beta/长期反转/下行波动未通过"
        ),
    },
    {
        "name": "round22_price_combo",
        "scripts": ["factor_round22_price_combo.py"],
        "plans": ["factor_round22_price_combo_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": (
            "三因子(+价格水平)超额+4.20→-0.25pp崩塌, Jaccard44.8%向差分散(分散≠增强); "
            "3/5维持R5, 价格水平降级单因子参考——单因子通过≠可并入(组合验证守门)"
        ),
    },
]

SCRIPT_TO_UNIT = {s: u["name"] for u in UNITS for s in u["scripts"]}
IMPORT_RE = re.compile(r"(?:from\s+research\.(\w+)\s+import|import\s+research\.(\w+))")

# 索引"方向"列展示名
DIRECTIONS = {
    "screen01_factor_screen": "因子筛选·中期动量",
    "screen02_factor_screen": "因子筛选·Amihud",
    "round03_combination": "Amihud×动量组合",
    "round04_risk_breakers": "风控·熔断/择时",
    "round05_industry_neutral": "R5 行业中性",
    "round06_r5_ma": "R5+均线择时",
    "round07_fullmarket": "全市场扩池",
    "round08_live_validation": "实盘化验证",
    "round09_holdings_count": "持仓数量敏感度",
    "round11_fullbuy": "全选满仓",
    "round12_15_concentrated": "小资金规模研究",
    "round16_crowding_timing": "拥挤度择时",
    "reversal_short_term": "短期反转",
    "dividend_factor": "高股息",
    "convertible_double_low": "可转债双低",
    "ew_base": "等权底仓",
    "etf_exploration": "ETF 轮动",
    "weekday_effect": "周内效应",
    "grid_demo": "网格演示",
    "yearly_breakdown": "年度分解工具",
    "round19_concentrated200": "小资金集中版·前200",
    "round20_extreme_scenario": "极端行情演练",
    "round21_tier1_screen": "梯队一筛选·4因子",
    "round22_price_combo": "价格水平组合验证",
}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def is_tracked(path: str) -> bool:
    return git("ls-files", "--error-unmatch", "--", path).returncode == 0


def parse_imports(script_path: str) -> set[str]:
    """解析脚本对 research 其他模块的引用（模块名集合）。"""
    with open(script_path, encoding="utf-8") as f:
        text = f.read()
    return {m.group(1) or m.group(2) for m in IMPORT_RE.finditer(text)}


def dependency_closure(scripts: list[str]) -> set[str]:
    """递归展开 research.X 依赖，剔除白名单，返回闭包内的探索脚本（模块名，不带 .py）。"""
    closure = {s[:-3] if s.endswith(".py") else s for s in scripts}
    frontier = list(closure)
    while frontier:
        s = frontier.pop()
        for dep in parse_imports(os.path.join("research", f"{s}.py")):
            if dep in KEEP or dep in closure:
                continue
            if os.path.exists(os.path.join("research", f"{dep}.py")):
                closure.add(dep)
                frontier.append(dep)
    return closure


def find_unit(target: str) -> dict:
    """按脚本名或单元名定位归档单元（脚本名允许省略 factor_ 前缀）。"""
    if target in SCRIPT_TO_UNIT:
        name = SCRIPT_TO_UNIT[target]
    else:
        matches = {
            s
            for s in SCRIPT_TO_UNIT
            if s == target
            or s == f"factor_{target}"
            or s.endswith(target)
            or s.endswith(f"{target}.py")
        }
        if len(matches) == 1:
            name = SCRIPT_TO_UNIT[next(iter(matches))]
        elif len(matches) > 1:
            raise SystemExit(f"脚本名有歧义: {target} -> {sorted(matches)}")
        else:
            name = target
    for u in UNITS:
        if u["name"] == name:
            return u
    raise SystemExit(
        f"未找到单元或脚本: {target}\n可用单元: {', '.join(u['name'] for u in UNITS)}"
    )


def rewrite_closure_imports(unit_dir: str, scripts: set[str]) -> None:
    """闭包内互 import 改写：research.X → X（同目录可导入）。scripts 为模块名。"""
    for script in sorted(scripts):
        path = os.path.join(unit_dir, f"{script}.py")
        with open(path, encoding="utf-8") as f:
            text = f.read()

        def repl(m: re.Match) -> str:
            mod = m.group(1) or m.group(2)
            if mod in scripts:
                return m.group(0).replace(f"research.{mod}", mod)
            return m.group(0)

        new_text = IMPORT_RE.sub(repl, text)
        if new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            print(f"  [import 改写] {path}")


def collect_outputs(unit_name: str, outputs: list[str]) -> list[str]:
    """收集 output/ 下归属本单元的结论型文件。

    归属判定用全局最长前缀（跨单元），避免 screen01 的 factor_corr_crosssec
    抢走 factor_corr_crosssec_round2（属 screen02）。
    """
    global_prefixes = sorted(
        {p for u in UNITS for p in u["outputs"]}, key=len, reverse=True
    )

    def longest_prefix_owner(fname: str) -> tuple[str, str] | None:
        for p in global_prefixes:
            if fname.startswith(p):
                owner = next(u["name"] for u in UNITS if p in u["outputs"])
                return p, owner
        return None

    files = []
    for f in sorted(os.listdir("output")):
        path = os.path.join("output", f)
        if not os.path.isfile(path):
            continue
        lp = longest_prefix_owner(f)
        if lp and lp[1] == unit_name:
            files.append(path)
    return files


def render_readme(
    unit: dict, scripts: set[str], plans: list[str], outs: list[str]
) -> str:
    main = next((f"{s}.py" for s in sorted(scripts) if s in unit["scripts"]), None)
    run_cmd = (
        f".venv/bin/python archive/experiments/{unit['name']}/{main}   # cwd=仓库根"
        if main
        else "（脚本留位 research/，无需复现命令）"
    )
    lines = [
        f"# {unit['name']} — 已归档探索",
        "",
        f"> 由 `research/archive_experiment.py` 于 {date.today().isoformat()} 归档。",
        "> 结论摘要与状态来自 plan §0 / README 探索表，以 plan 文档为准。",
        "",
        f"- **状态**：{unit['status']}",
        f"- **结论摘要**：{unit['conclusion']}",
        f"- **归档日期**：{date.today().isoformat()}",
        f"- **相关脚本**：{', '.join(sorted(scripts)) or '（无，脚本留位=共享基座）'}",
        f"- **plan 文档**：{', '.join(plans) or '（无）'}",
        f"- **结论输出**：{', '.join(os.path.basename(p) for p in outs) or '（无）'}",
        f"- **复现命令**：`{run_cmd}`",
        "- **数据依赖**：`data/fundamental/full_daily.parquet`、`data/round2/` 等；"
        "依赖的共享基座 `research/reversal_factor.py` / `research/dividend_factor.py` "
        "因被生产链依赖而留位，import 路径不变。",
    ]
    return "\n".join(lines) + "\n"


def update_index(unit: dict) -> None:
    index_path = "archive/INDEX.md"
    with open(index_path, encoding="utf-8") as f:
        text = f.read()
    row = (
        f"| {unit['name']} | {DIRECTIONS.get(unit['name'], unit['name'])} | "
        f"{unit['status']} | {unit['conclusion']} | "
        f"archive/experiments/{unit['name']}/ | {date.today().isoformat()} |"
    )
    # 去掉占位行与同单元旧行（幂等），追加新行后按单元名排序
    body_lines = [
        ln
        for ln in text.splitlines()
        if not ln.startswith("| 暂无已归档探索")
        and not ln.startswith(f"| {unit['name']} |")
    ]
    insert_at = next(
        i for i, ln in enumerate(body_lines) if "---" in ln and ln.startswith("|")
    )
    header = body_lines[: insert_at + 1]
    table = body_lines[insert_at + 1 :]
    table = [ln for ln in table if ln.strip()]
    table.append(row)
    table.sort(key=lambda ln: ln.split("|")[1].strip())
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header + table) + "\n")
    print(f"  [索引更新] archive/INDEX.md (+{unit['name']})")


def verify(unit_dir: str, scripts: set[str]) -> None:
    """校验：py_compile + 静态 import 目标存在性。scripts 为模块名。"""
    for script in sorted(scripts):
        path = os.path.join(unit_dir, f"{script}.py")
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", path], capture_output=True, text=True
        )
        if r.returncode != 0:
            raise RuntimeError(f"py_compile 失败: {path}\n{r.stderr}")
    # 静态 import 检查：research.X 目标须存在；闭包内裸模块须同目录存在
    for script in sorted(scripts):
        path = os.path.join(unit_dir, f"{script}.py")
        for dep in parse_imports(path):
            if dep in scripts and not os.path.exists(
                os.path.join(unit_dir, f"{dep}.py")
            ):
                raise RuntimeError(f"闭包内依赖缺失: {path} -> {dep}")
            if dep not in scripts and not os.path.exists(
                os.path.join("research", f"{dep}.py")
            ):
                raise RuntimeError(f"留位依赖缺失: {path} -> research/{dep}.py")
    print("  [校验通过] py_compile + 依赖存在性 OK")


def main() -> int:
    ap = argparse.ArgumentParser(description="探索归档工具")
    ap.add_argument("target", help="脚本名或单元名")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不落盘")
    args = ap.parse_args()

    unit = find_unit(args.target)
    closure = dependency_closure(unit["scripts"])
    # 闭包可能命中其他单元脚本（如 round13 → round12）：并入其 plan 文档
    unit_mods = {s[:-3] if s.endswith(".py") else s for s in unit["scripts"]}
    plans = list(unit["plans"])
    for script in sorted(closure - unit_mods):
        owner = SCRIPT_TO_UNIT.get(script)
        if owner:
            for p in next(u for u in UNITS if u["name"] == owner)["plans"]:
                if p not in plans:
                    plans.append(p)
            print(f"  [闭包并入] {script} 属单元 {owner}，已并入其 plan 文档")
    outs = collect_outputs(unit["name"], unit["outputs"])

    unit_dir = os.path.join(ARCHIVE, unit["name"])
    print(f"== 归档单元: {unit['name']} ==")
    print(
        f"  脚本(闭包 {len(closure)}): {', '.join(sorted(closure)) or '（脚本留位）'}"
    )
    print(f"  plan 文档: {', '.join(plans) or '（无）'}")
    print(f"  结论输出: {', '.join(os.path.basename(p) for p in outs) or '（无）'}")
    if args.dry_run:
        print("  [dry-run] 未执行任何变更")
        return 0

    os.makedirs(unit_dir, exist_ok=True)
    moved: list[tuple[str, str]] = []
    index_path = "archive/INDEX.md"
    index_backup = (
        open(index_path, encoding="utf-8").read()
        if os.path.exists(index_path)
        else None
    )
    try:
        # 1. 移动脚本（git mv，保留历史）
        for script in sorted(closure):
            src, dst = (
                os.path.join("research", f"{script}.py"),
                os.path.join(unit_dir, f"{script}.py"),
            )
            if is_tracked(src):
                git("mv", src, dst)
            else:
                os.rename(src, dst)
            moved.append((src, dst))
        # 2. 移动 plan 文档（git mv）
        for plan in plans:
            src, dst = os.path.join("docs", plan), os.path.join(unit_dir, plan)
            if os.path.exists(src):
                if is_tracked(src):
                    git("mv", src, dst)
                else:
                    os.rename(src, dst)
                moved.append((src, dst))
        # 3. 改写闭包内互 import
        rewrite_closure_imports(unit_dir, closure)
        # 4. 搬结论输出（untracked，用 rename）并 git add 入库
        for src in outs:
            dst = os.path.join(unit_dir, os.path.basename(src))
            os.rename(src, dst)
            moved.append((src, dst))
            git("add", dst)
        # 5. 生成 README + 更新 INDEX
        readme = os.path.join(unit_dir, "README.md")
        with open(readme, "w", encoding="utf-8") as f:
            f.write(render_readme(unit, closure, plans, outs))
        git("add", os.path.join(unit_dir, "README.md"))
        git("add", os.path.join(unit_dir, "*.py"))
        git("add", os.path.join(unit_dir, "*.md"))
        update_index(unit)
        git("add", "archive/INDEX.md")
        # 6. 校验
        verify(unit_dir, closure)
    except Exception as e:  # noqa: BLE001 — 回滚后重抛
        print(f"  [错误] {type(e).__name__}: {e}\n  回滚中…")
        git("reset", "-q")
        git("restore", "-q", "--worktree", "--", "research/", "docs/")
        # archive 下副本删除；output 文件反向归位
        for src, dst in reversed(moved):
            if os.path.exists(dst):
                if os.path.dirname(src) == "output":
                    os.rename(dst, src)
                else:
                    os.remove(dst)
        readme_p = os.path.join(unit_dir, "README.md")
        if os.path.exists(readme_p):
            os.remove(readme_p)
        if index_backup is not None:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(index_backup)
        if os.path.isdir(unit_dir) and not os.listdir(unit_dir):
            os.rmdir(unit_dir)
        print("  已回滚（research/docs 还原、output 归位、INDEX/README 清理）")
        return 1
    print(f"== 完成: {unit_dir} ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
