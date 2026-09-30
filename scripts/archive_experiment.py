#!/usr/bin/env python3
"""探索归档工具：把已结束探索从 scripts/ 移入 archive/experiments/。

用法:
    .venv/bin/python scripts/archive_experiment.py <脚本名或单元名> [--dry-run]
    .venv/bin/python scripts/archive_experiment.py round16_crowding_timing --dry-run

流程（设计见 docs/archive_design_plan.md §8）:
    1. 解析依赖闭包（scripts./quant_trading_01. import 递归展开，命中白名单即停）
    2. git mv 脚本 + plan 文档 → archive/experiments/<unit>/
    3. 改写闭包内互 import（scripts.X → X，同目录可导入；quant_trading_01.* 基座留位不变）
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

# 永不归档白名单：生产链 + 共享基座（被生产链依赖；脚本在 scripts/，基座在 src/quant_trading_01/）
KEEP = {
    "config",  # 配置系统(Round 34, 全仓共享基座)
    "data_io",
    "fetch_corporate_actions",
    "fetch_daily_incremental",
    "fetch_full_industry",
    "fetch_full_market",
    "fetch_round2_data",
    "fetch_stock_basic",  # 生产宇宙清单刷新（季度低频, src/fundamental 迁移）
    "data_loader",  # 共享基座：dividend_factor 基准 lazy / 归档复现 / tests
    "paper_live",
    "paper_trade",
    "daily_update",
    "plot_daily_gains",
    "scenario_ytd",
    "export_holdings",
    "reversal_factor",  # 基座：paper_live/paper_trade 依赖 ew_nav/build_pool
    "dividend_factor",  # 基座：paper_trade 依赖 month_last_days/metrics
    # P3 生产链(Round 41-47 定稿上线)
    "factor_round41_low_price",  # 基座：P3 选股 build_sets/load_data, paper_live_p3 依赖
    "paper_live_p3",
    "daily_update_p3",
    "plot_daily_gains_p3",
    "scenario_ytd_p3",  # P3 场景回放(份额级): paper_live_p3 同族, plot_daily_gains_p3 引用
    # 低价股数据维护生产链(round2 财务/分红/真实价)
    "fetch_financial_quality",
    "fetch_dividends_backfill",
    "fetch_delisted_dividends",
    "fetch_delisted_daily",
    "fetch_delisted_raw_price",
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
        "scripts": [],  # reversal_factor.py 是共享基座，留位 src/quant_trading_01/
        "plans": ["reversal_factor_plan.md"],
        "outputs": ["reversal_factor"],
        "status": "❌ 已否决",
        "conclusion": "短期反转否决（IC 不足 + 15bp 成本致命）",
    },
    {
        "name": "dividend_factor",
        "scripts": [],  # dividend_factor.py 是共享基座，留位 src/quant_trading_01/
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
        "name": "migrate_full_daily_partitions",
        "scripts": ["migrate_full_daily_partitions.py"],
        "plans": [],
        "outputs": [],
        "status": "🛠 工具/演示",
        "conclusion": "一次性迁移工具：full_daily.parquet 单文件 → 按年分区（已完成使命，R17 基建产物）",
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
    {
        "name": "round23_limit_aware",
        "scripts": ["factor_round23_limit_aware.py"],
        "plans": ["factor_round23_limit_aware_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": (
            "涨跌停阻塞验证(S3-跟随): 阻塞损失-0.31pp@300万/-0.95pp@60万(四账户全≥-1.0pp), "
            "三段全正策略结论不变; 结论并入生产Round24(引擎内置+实盘SOP入运营手册§8.7)"
        ),
    },
    {
        "name": "round25_pead",
        "scripts": [
            "factor_round25_pead.py",
            "fetch_earnings_forecast.py",
        ],
        "plans": ["factor_round25_pead_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": (
            "PEAD业绩预告后漂移: IC+0.003(t=0.46)极弱/分组不单调(Q3峰)/超额+0.4pp, 1/4未通过; "
            "与中期动量IC序列相关+0.629强重叠(非独立信息源)——不进入组合验证, R5不变"
        ),
    },
    {
        "name": "round26_weight_sensitivity",
        "scripts": ["factor_round26_weight_sensitivity.py"],
        "plans": ["factor_round26_weight_sensitivity_plan.md"],
        "outputs": [],
        "status": "⏸ 搁置",
        "conclusion": (
            "R5权重敏感性: 50:50非最优且脆弱(邻域波动+3.17pp>0.5pp); Amihud权重单调递增超额"
            "(−0.37→+6.38pp)——Amihud是超额主源, 动量是稀释项; 生产不动(冻结), "
            "是否调权重=用户决策点(需另开预注册+细扫防过拟合)"
        ),
    },
    {
        "name": "round27_weight_tuning",
        "scripts": ["factor_round27_weight_tuning.py"],
        "plans": ["factor_round27_weight_tuning_plan.md"],
        "outputs": [],
        "status": "⏸ 搁置",
        "conclusion": (
            "权重细扫0.55~0.80: 超额单调递增至0.80(+7.04pp)但无高原(双侧高原判据全❌); "
            "端点0.80伪通过被双侧判据拦截(数据挖掘陷阱); 结论: 趋势真实但无稳健选择"
            "——由Round28扩展扫描+样本外验证接续"
        ),
    },
    {
        "name": "round28_weight_tuning_oos",
        "scripts": ["factor_round28_weight_tuning_oos.py"],
        "plans": ["factor_round28_weight_tuning_oos_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": (
            "扩展扫描0.80~1.00顶点0.95(+7.49%)+样本外验证(训练14-21独立选权→验证22-26 "
            "超额差+6.5pp)+高原0.90~1.00波动0.15pp——四项全过; 用户批准折中w=0.85落地生产"
            "(保留15%动量缓冲), 账本重建"
        ),
    },
    {
        "name": "round30_shareholder",
        "scripts": [
            "factor_round30_shareholder.py",
            "factor_round30_shareholder_combo.py",
            "fetch_shareholder_count.py",
        ],
        "plans": ["factor_round30_shareholder_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": (
            "股东户数/筹码集中度: 单因子3/4(IC-0.02 t=-4.57极显著, 与Amihud/动量正交0.1级), "
            "但等权三因子并入崩塌(+7.31→+3.62pp, 稀释Amihud主源)——正交≠可并入(R22教训重演); "
            "不并入R5; 判据缺陷记录(①超额应为门禁)"
        ),
    },
    {
        "name": "round31_lhb",
        "scripts": ["factor_round31_lhb.py", "fetch_lhb.py"],
        "plans": ["factor_round31_lhb_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": (
            "龙虎榜净买占比: 未通过(1/4)——机制假设被否定: 上榜后1/2/5日均值+0.32/+0.28/+0.37%"
            "(上榜=强势延续非散户追高看空); IC无效/分组U型/超额+0.3pp; 正交(-0.04)但无信号; "
            "月度截面无预测力, 不进入组合验证"
        ),
    },
    {
        "name": "round17_delisted",
        "scripts": [],  # 基建轮: 改动在生产代码(full_daily 年分区/退市股宇宙/data_io), 脚本留位
        "plans": ["factor_round17_delisted_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": (
            "退市股宇宙/年分区基建(R17): full_daily 年分区+3409只(含215退市股)+qfq回退"
        ),
    },
    {
        "name": "round24_prod_limit_aware",
        "scripts": [],  # 基建轮: 改动在生产代码(paper_trade.rebalance 阻塞), 脚本留位
        "plans": ["factor_round24_prod_limit_aware_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": (
            "生产引擎内置涨跌停阻塞(S3-跟随)+账本统一真实口径; 回测+账本口径一致"
        ),
    },
    {
        "name": "round32_execution_cost",
        "scripts": [],  # 基建轮: 改动在生产代码(paper_live 滑点), 脚本留位
        "plans": ["factor_round32_execution_cost_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": (
            "模拟盘账本补上滑点15bp(账本真实化): 300万 replay_w 对照 slip=0 +8.78%→15bp +7.63%; "
            "每省1bp实际成本≈超额+0.072pp(成本敏感度回测); 四账户从9月重新建仓含滑点"
        ),
    },
    {
        "name": "round33_backtest_slip",
        "scripts": [],  # 基建轮: 改动在生产代码(paper_trade/scenario_ytd 默认滑点), 脚本留位
        "plans": ["factor_round33_backtest_slip_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": (
            "回测默认滑点0→15bp, 回测=运营=基准三口径统一; replay四账户重跑: "
            "60/100/300/600万超额+2.83/+4.92/+6.08/+6.28%, 费用4.48/4.35/3.62/3.36%/年"
        ),
    },
    {
        "name": "round35_execution_cost",
        "scripts": [],  # 基建轮: 改动在生产代码(paper_trade/paper_live 按股滑点), 脚本留位
        "plans": ["factor_round35_execution_cost_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": (
            "执行成本模型评估: A固定15bp +7.57%维持生产口径; B流动性依赖 +7.02%"
            "(−0.55pp, 等权加权滑点21.1bp>15bp, flat低估小盘真实成本) 以 --slip-by-amount "
            "监控并入; C VWAP否决(免费分钟源历史不足官方文档证实+第三方源不可低成本验证); 18测试通过"
        ),
    },
    {
        "name": "round36_shortterm_screen",
        "scripts": ["factor_screen_round36_shortterm.py"],
        "plans": ["factor_round36_shortterm_screen_plan.md"],
        "outputs": [
            "round36_shortterm_summary",
            "round36_F4低成交额5",
            "round36_F3低换手5_ic",
        ],
        "status": "🟡 部分通过",
        "conclusion": (
            "周频短线因子筛选(5日持有,全市场非ST池,639期): F4低成交额5 通过(4/4)"
            "(IC−0.077 t=−10.8, 超额15bp+11.9pp/35bp+7.1pp, 三段全正, 换手10.3) 但"
            "与生产Amihud截面相关−0.85强同源, 正交残差IC−0.075显著, 控制市值后仍−0.060,"
            "B口径31.7bp成本存活+7.9pp→非成本/市值假象, 需组合验证守门(R22/R30协议); "
            "F3低换手5 部分通过(3/4,超额仅+1.3pp量级不足); 短反转/低波动/换手突变/短动量 否决"
            "(周频反转Q1接飞刀−12.6pp, 与月频对照更不可交易)"
        ),
    },
    {
        "name": "round37_f4_combo",
        "scripts": ["factor_round37_f4_combo.py"],
        "plans": ["factor_round37_f4_combo_plan.md"],
        "outputs": ["round37_f4_combo_summary"],
        "status": "⏸ 搁置",
        "conclusion": (
            "F4低成交额5组合验证(140期,300万share级,15bp): B等权三因子未通过(核心门禁①"
            "超额仅+0.57pp<+1pp, 未崩塌但无增量, 与R30正交崩塌对照: 同源稀释无害/正交破坏互补); "
            "C(0.85Amihud+0.15F4) 4/5组合升级候选(+8.30%, 超额+1.10pp, 三段全正, 回撤/换手更优) "
            "唯一失败⑤Jaccard 78.6%(同源高重叠属设计使然); 解释验证: C>纯Amihud1.0(+7.10%)→"
            "F4有真实短频增量非权重复现, 但本质是Amihud短频精化非新信息源; 维持R5生产, "
            "C为决策点(替换动量=改冻结选股逻辑须另预注册; 建议0.85A+0.10动量+0.05F4微调路径)"
        ),
    },
    {
        "name": "round38_weight_scan",
        "scripts": ["factor_round38_weight_scan.py"],
        "plans": ["factor_round38_weight_scan_plan.md"],
        "outputs": ["round38_weight_scan_summary"],
        "status": "🟡 部分通过",
        "conclusion": (
            "三因子权重最优配比扫描(35点ew_nav+share级复核+样本外R28协议): 样本外四项判据全过"
            "(w_train*=A0.40/M0.10/F40.50: 训练+9.80%→验证+12.62% vs A+10.32% 差+2.30pp, "
            "网格内部, 全区间+10.40%≥A, 双侧高原0.49pp<0.5pp); 候选区间 "
            "[Amihud0.40~0.50×动量0.05~0.10×F4 0.40~0.50], share级最优点W1(0.50/0.05/0.45)"
            "超额+9.27%(三段全正/高原0.15pp最稳); F4增量三重独立证据确认(R36正交IC→R37解释"
            "验证→R38样本外); 本质=调整Amihud测量窗口(21日→5日)非新信息源, 代价=动量缓冲"
            "15%→5~10%风格年更脆弱; R5生产未动, 呈用户决策"
        ),
    },
    {
        "name": "round39_candidates",
        "scripts": ["factor_round39_candidates.py"],
        "plans": ["factor_round39_candidates_plan.md"],
        "outputs": ["round39_candidates_summary"],
        "status": "❌ 已否决",
        "conclusion": (
            "'同向但异法'候选因子验证(4因子月频筛+组合验证): C1低换手21/C2换手波动21std "
            "部分通过(3/4, IC显著−0.084/−0.092 t≤−5.6, 单调完美, Jaccard 16.9%极异法, "
            "但超额仅+1.7/+2.0%<3pp不进组合验证); C3市值代理 通过(4/4,+9.4%)但10%并入w* "
            "组合验证3/5不并入(超额+0.24pp<+1pp, Jaccard 90.6%同法重复暴露→R22教训重演); "
            "C4短动量5/21 未通过(月频方向=反转, 高动量组−10.5%); 框架结论: 异法度是必要不充分"
            "条件, 最终裁判=组合增量门禁; 无新因子并入, R5/w*生产不变"
        ),
    },
    {
        "name": "round41_low_price_quality",
        "scripts": [],  # factor_round41_low_price.py 是共享基座(paper_live_p3 依赖), 留位 scripts/
        "plans": ["factor_round41_low_price_quality_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": "低价股研究起点: 子区间2-3元甜蜜区/0-2元重灾区, 低价整体跑赢全市场; P3链起点",
    },
    {
        "name": "round42_low23_quality",
        "scripts": ["factor_round42_low23_quality.py"],
        "plans": ["factor_round42_low23_quality_plan.md"],
        "outputs": [],
        "status": "✅ 通过",
        "conclusion": "2-3元+质量筛选预注册通过(全样本19.8%/0.86/-40.6%)",
    },
    {
        "name": "round43_outsample",
        "scripts": ["factor_round43_outsample.py"],
        "plans": ["factor_round43_outsample_plan.md"],
        "outputs": [],
        "status": "✅ 通过",
        "conclusion": "样本外5/5: 验证段12.0%/+3.2pp; 训练段2-3元即最优, 选择偏差减轻",
    },
    {
        "name": "round44_improve",
        "scripts": ["factor_round44_improve.py"],
        "plans": ["factor_round44_improve_plan.md"],
        "outputs": [],
        "status": "✅ 通过",
        "conclusion": "V1区间上移2.3-3.2: 验证段16.0%/0.78/-25.4%",
    },
    {
        "name": "round45_holding_period",
        "scripts": ["factor_round45_holding_period.py"],
        "plans": ["factor_round45_holding_period_plan.md"],
        "outputs": [],
        "status": "✅ 通过并入",
        "conclusion": "月频>>买入持有(16% vs 2.2%): 换血是超额主来源; 买入持有正期望(胜率74-78%)非最优",
    },
    {
        "name": "round46_maximize",
        "scripts": ["factor_round46_maximize.py"],
        "plans": ["factor_round46_maximize_plan.md"],
        "outputs": [],
        "status": "✅ 通过",
        "conclusion": "收益更大化收敛: P3=3.0-4.0元 验证段18.6%/0.93/-25.0%",
    },
    {
        "name": "round47_combine_boundary",
        "scripts": ["factor_round47_combine_boundary.py"],
        "plans": ["factor_round47_combine_boundary_plan.md"],
        "outputs": [],
        "status": "✅ 定稿",
        "conclusion": "组合无增益+4元边界失效, P3定稿并上线模拟盘八账户(2026-09-01)",
    },
    {
        "name": "round49_event_momentum",
        "scripts": ["factor_round49_event_momentum.py"],
        "plans": ["factor_round49_event_momentum_plan.md"],
        "outputs": [],
        "status": "❌ 已否决",
        "conclusion": "涨停事件动量否决(E1胜率44.7%<50%): 1-2日动量为正但5日胜率转负, 可交易(换手)子集5日胜率43%多数亏, 暴涨在买不进的缩量/一字; 游资打板=对手盘负和, 数据终结叙事",
    },
    {
        "name": "round50_p3_optimize",
        "scripts": ["factor_round50_p3_optimize.py"],
        "plans": ["factor_round50_p3_optimize_plan.md"],
        "outputs": [],
        "status": "❌ 未达标",
        "conclusion": "P3 优化空间封闭(R50): 经营现金流质量否决(验证段 -0.4/-0.8pp, 全样本 -4.7~-5.2pp) + 双周频否决(-3.05pp@45bp, 换手翻倍) + 阻塞口径验证段稳健(全样本 +1.8pp/年 高估, 集中 2014-17); 行业上限探查即否决(大类 HHI 0.05-0.08 已分散); 剩余空间仅框架外(扩池/行业排序补位)",
    },
    {
        "name": "round51_p3_risk_value",
        "scripts": ["factor_round51_p3_risk_value.py"],
        "plans": ["factor_round51_p3_risk_value_plan.md"],
        "outputs": [],
        "status": "🟡 部分通过",
        "conclusion": "A1 低波60 唯一通过且超 X0 集中度对照(回撤 -25.0%→-21.6%, 年化 18.2%→19.8%, 夏普 0.91→1.03, Calmar 0.73→0.92), 三段中两段胜(2014-17 +48.1% vs +44.5%, 2022-26 +17.1% vs +14.3%, 2018-21 略输 0.5pp), 13 年 12 年不败仅 2021 输 5.8pp; 其余 11 变体未达标: 低IVOL/半方差差 0.7-0.8pp, 低PB 边际(年化+1.9pp/夏普+0.099 双重差一丝), 低MAX 收益最好但回撤未改善, 低PE/低应计反向, 波动率倒数加权降回撤不足但零成本改善夏普, 波动率目标仓位(择时)第 6 次失败(仅 2014-17 降回撤 14pp); 判据②符号更正已披露且不改变任何判定; §0.1 确定性修正: reindex(list(set)) 平局按 PYTHONHASHSEED 抖动致全样本年化最大差 1.3pp(验证段稳定), 已改 sorted(S) 并撤回'牛市跑输'判断; 生产采纳须另行批准",
    },
    {
        "name": "round52_p3_composite",
        "scripts": ["factor_round52_p3_composite.py"],
        "plans": ["factor_round52_p3_composite_plan.md"],
        "outputs": [],
        "status": "❌ 未达标",
        "conclusion": "P3 池内多因子合成打分(首次引入打分机制)全部未达标: 绑定判据为'不劣于单因子 A1'——Z1-Z4 合成抬高收益(Z4 年化 20.2% vs A1 19.8%, 夏普 1.04)但回撤恶化 1.5-1.8pp(-23.1~-23.4% vs -21.6%), Calmar 0.85-0.87 全面低于 A1 0.92, 净效应=用回撤换一点收益, 与'提收益+降回撤'目标相反; Z5 取 50% 回撤 -19.3%(改善 5.7pp)但年化仅 +0.3pp/45bp 持平/持仓 26 只(<30 下限); 探查预测被证实(vol/ivol 秩相关 0.917 → Z2≈Z1, 增量仅来自低PB, 而低PB 自身回撤不及低波); A1 仍为唯一可用候选; 自校验双重通过(Z0=R50, A1=R51 逐位一致); 生产采纳须另行批准",
    },
    {
        "name": "round53_p3_a1_share_level",
        "scripts": ["factor_round53_p3_a1_share_level.py"],
        "plans": ["factor_round53_p3_a1_share_level_plan.md"],
        "outputs": [],
        "status": "🟡 部分通过",
        "conclusion": "A1 低波60 份额级八账户验证(主窗口 2021-2026): 八账户全部不劣于现冻结 P3——10万-600万 年化 +0.63~+1.86pp(随规模递减)、回撤改善 +2.45~+3.13pp、夏普 +0.06~+0.10, 买不起1手 0.0%; 3万账户是执行失败而非策略表现(66.5 目标仅持 35.0只=52.6%、47.3% 目标买不起1手、现金 49.1%、累计费用 35%、年化 -3.99%), A1 修复到 +8.09%(持仓率 99.7%)→ 该 +12.08pp 是'从不可执行到可执行'而非 alpha; 600万 份额级仅 +0.63pp(等权口径 +1.6pp)说明 1手取整/阻塞/现金拖累吃掉约 1pp; 主窗口可信性已验证(600万 S0 -24.96% vs 等权 -25.0%); 全样本窗口作废(口径缺陷): 份额级回撤 -95% vs 等权 -45.54%、累计费用 117-165%, 根因 scenario_ytd_p3 未接入 R48 的 eval_prices(raw.ffill()) 估值口径(已量化证据, 修正须另轮预注册); 生产采纳/3万账户处置须另行批准",
    },
    {
        "name": "round55_p3_keep_scan",
        "scripts": ["factor_round55_p3_keep_scan.py"],
        "plans": ["factor_round55_p3_keep_scan_plan.md"],
        "outputs": [],
        "status": "✅ 通过（维持现状）",
        "conclusion": "P3 低波截断比例 70% 平台性敏感性验证(7 档 0.40-1.00 一次跑完全报, 同一数据版本): 训练段 2014-2021 年化 0.60/0.70/0.80 = +26.82%/+26.79%/+26.65%(极差 0.17pp), 最优-次优 0.03pp → 70% 在平台顶, 非幸运尖峰(A1✅A2✅); 验证段 0.70 +17.28% 比 P0 +14.43% 高 2.85pp 且回撤改善 3.41pp(B1✅), 距验证段最优 0.50(+18.45%) 仅 1.17pp(B2✅); A3([0.5,0.9] 回撤极差≤3pp) ❌ 实测 3.94pp —— 失败源于回撤随截断加深单调改善(0.50 -40.81%→0.90 -44.76%, 机械必然非悬崖), 且 A3 判据本身设计不当(把'平台'写成宽范围极差), 按纪律保留 ❌ 不改判据; 不支持改到 0.50(训练段反低 1.8pp 且月均仅 30.6 只、44.6% 月份<30 只分散度显著恶化); 顺带量化 R54 已知代价: 0.70 档 30.4%(45/148)个月持仓<30 只; §0.2 预注册锚点未通过并如实处理: R51 归档实现 vs R55 新实现同数据净值逐位一致(最大差 0.000e+00)→实现无口径错误, 差异来自数据版本漂移(2026 分区 09-30 09:41 重写, 末端 09-22/09-24/09-29 复现 18.88%/18.51%/18.39% 全部≠记录 18.2%), 本轮记录数据指纹并提示历史轮次绝对数不可精确复现; 零生产改动",
    },
    {
        "name": "round56_p3_eval_fix",
        "scripts": ["factor_round56_p3_eval_fix.py"],
        "plans": ["factor_round56_p3_eval_fix_plan.md"],
        "outputs": [],
        "status": "🟡 部分通过",
        "conclusion": "修 scenario_ytd_p3 估值口径(R48 eval_prices) + 份额级重跑: V1 口径锚点完美通过——活窗口(scenario 2026-09-01→09-29, 600万)与生产账本每日 CSV 逐位一致(首日与逐日相对差均 0.0000%, 5,990,057.13 与 5,759,191.15 完全相同, 持仓 36 只), 证明生产与研究回放估值口径现已统一; V2 主窗口回归与 R53 记录值逐位相同(16 个单元 |Δ年化| 最大 0.00%, 八账户 S1≥S0 符号不变, 3万 仍为执行失败形态) => R53 主窗口结论对估值口径稳健、生产采纳(A1=0.70)成立; V3 全样本未通过: 600万 S0 回撤 -75.93%(判据 ∈[-55%,-35%] 未过)、累计费用 133% 本金(判据 ≤15% 未过)、S1 不劣于 S0 仅 1/8 => 全样本份额级维持不可用; 根因(§0.2, 代码级): factor_round41_low_price.py:84 `fac_ser = s.reindex(close.index).ffill().fillna(1.0)` —— reindex 先丢掉索引起点(2013-06-01)之前的因子记录, 再 ffill 无从填充 -> 因子回落 1.0 -> real=close(前复权价非真实价), 直到该股窗口内首条因子记录才切换; 实测 2014-06-17 sh.601199 +386.26%(3.21 vs 15.69)、sh.601377 +169.48%(2.97 vs 8.16)、sz.002107 切换日 +334.72%, 远超 ±10% 涨跌停; 份额级用该面板成交估值 -> 2014 +491.56%(等权 +89.00%)、2015 年内回撤 -62.90%(等权 -10.67%), 2016 年起两口径吻合(各年 ≤±3.7pp); 影响范围: 2014-2015 每月池内 4.0%-17.1% 标的因子未生效(合计 430 个标的人次), 因子表 3123 只中 1563 只首条记录晚于 2014-01-01; 受影响既往结论加注: R41-R47 全样本 +20.5%/分年代 2014-17 +44.5%、R51 的 2014-17 +48.1%、R55 三段 2014-17 数字均因入池污染需 R57 重算, 不应再引用为低价股证据; 主窗口 2021-2026 不受影响 => R51/R53/R54/R55 主窗口结论与生产采纳(A1=0.70)依然成立; §0.4 自我更正: V3b'累计费用≤15%本金'判据本身错误(Σ费用/初始本金随持有期与复利增长, 粗算 ~25% 年化复利下期望≈98%, 实测 133% 同量级) => R53 把累计费用 117-165% 当缺陷特征同样错误, R53 真正的红旗是回撤 -93~-95%(本轮降到 -75.9% 仍不合理); 零生产改动, 修复仅动研究回放路径, 生产账本无需重建",
    },
    {
        "name": "round57_real_fix",
        "scripts": ["factor_round57_real_fix.py"],
        "plans": ["factor_round57_real_fix_plan.md"],
        "outputs": [],
        "status": "✅ 通过（修复成立；另暴露空池月口径问题待 R58）",
        "conclusion": "修 真实价 因子前向填充 bug + 重算受影响年份 + 重跑全样本份额级。根因(R56 定位): factor_round41_low_price.py:84 `fac_ser = s.reindex(close.index).ffill().fillna(1.0)` 先 reindex 再 ffill → 索引起点(2013-06-01)前的复权因子记录被丢弃 → 因子回落 1.0 → real=close(前复权价非真实价), 直到该股索引内首条因子记录才切换。改动(一行): u=close.index.union(s.index); fac_ser=s.reindex(u).ffill().reindex(close.index).bfill().fillna(1.0)。判定(预注册 §3 阈值未改): W1a ✅ 改动 ⊂ {t<该股索引内首条因子记录日}(越界 0; 改动 411,793/11,048,569=3.73%); W1b ✅ t≥fr 逐位相同(最大绝对差 0.000e+00); W1c 比率 p10/p50/p90=1.012/1.225/3.090(2016 后 112,046 个=1.006/1.067/1.677); W2 ❌ 作废(判据设计错误: fr 当日即除权日, 10送10 真实价腰斩属正常, 真实收益=前复权 close 比值与修复无关; 对照 修后 85.78% vs 修前 26.26%); W3 ✅ 非因子变动日 |Δ|>12% 占比 0.0012%(修前 0.0036%, 判据 ≤0.1%); W4c P0 2022-26 ✅ 逐位一致(+14.43%/-25.00%), A1 ❌(+16.22% vs R55 记录 +17.28%: 2021 后上市股票 real 修正使池微变, 低波截断放大); W5 ❌ 主窗口最大偏差 2.37e-03(0.24pp 年化)——plan 前提假设错(2016 后仍有 112,046 个 stock-days 被改), 但 16 个单元符号与量级全不变; W6a ❌ 600万 S0 全样本回撤 -69.19%(成因已定位, 非数据面板); W6b ❌ 13 年中仅 2014 未过(-7.95pp, 其余 ≤4.02pp); W6c ✅ 8/8 账户 S1 不劣于 S0; W7 ✅ ruff 0 错误 + pytest 26 passed + output/ 生产账本零改动。修复效果(决定性): 逐年份额级-等权差 2014 +402.55pp→-7.95pp、2015 -124.92pp→-3.85pp, 其余 11 年基本不变; 全样本年化 份额级 +15.67% vs 等权 +15.73%(差 0.06pp)。年代重算(等权, 旧→新): P0 全样本 +20.36%→+15.73%(-4.63pp)/2014-17 +44.51%→+26.72%(-17.79pp)/2018-21 +8.67%→+8.81%/2022-26 不变; A1 全样本 +21.29%→+16.27%/2014-17 +46.98%→+27.55%。入池: 2013-06~2016 池规模旧均值 23.4→新 15.0, 剔除 330 标的人次/新增 37 → 旧池约 36% 是被错价误入的伪低价股(真价 8-15 元、前复权 3-4 元), 这正是 2014-17 段 +44.5% 的主因。被替代旧数字(不得再引用): 手册 P3 全样本 +20.5%→+15.7%、分年代 +44.5/+8.7/+14.7→+26.7/+8.8/+14.4、R51 A1 全样本 +22.2%→+16.3%、R55 三段(0.70 +48.11/+8.24/+17.28→+27.55/+7.75/+16.22); 保留不变: 主窗口 2021-2026 全部结论(R51/R53/R54/R55, 仅微动 ≤0.24pp, P0 2022-26 逐位一致)+ 生产采纳 A1=0.70 + 七账户账本。新增发现(非本轮预注册范围): 修复后全区间恰好 5 个空池月 2015-04/05/06/07/08(狂牛市低价股集体涨出 3-4 元带; 2015 年池仅 5 只), 空池月两口径行为不同——份额级=PaperPortfolio.rebalance(n==0 直接 return)=生产 paper_live_p3 继续持有, 等权 ew_nav 空集=持币 0%(2015-04~08 恰好 +0.00% x5) → 2015 年内回撤 份额级 -50.67% vs 等权 -13.12% → 全样本 DD -69.19% vs -45.61% => 等权历史回撤低估真实尾部, 份额级才是与生产一致的权威口径; R58 待定权威定义并复核 R50 阻塞结论(R50 的 2014-17 数字建立在污染池上)。",
    },
    {
        "name": "round58_pool_policy",
        "scripts": ["factor_round58_pool_policy.py"],
        "plans": ["factor_round58_pool_policy_plan.md"],
        "outputs": [],
        "status": "✅ 通过（空池月口径已裁定 + R50 修正 + 体检门落地；Y2/Y6 未达标如实记录）",
        "conclusion": '空池月口径裁定 + 面板体检门 + R50 阻塞复核 + 2014 残余归因。零策略/参数/账本改动(唯一生产改动=step 空池月仅打印告警)。背景: R57 修复真实价面板后暴露"份额级(生产)继续持有 vs 等权研究口径清仓持币"在空池月分歧, 导致历史回撤口径不确定。核心结论(Y3): 全区间恰好 5 个空池月 2015-04-01/05-04/06-01/07-01/08-03(P0 与 A1 相同; 狂牛市中低价股集体涨出 3-4 元带, 2015 年池仅 5 只)。权威口径裁定 = **空池月维持现有持仓, 不调仓不清仓**(引擎 PaperPortfolio.rebalance 在 n==0 直接 return, 与生产 paper_live_p3 一致)。四口径全样本: 等权 cash +15.73%/-45.61%(旧报告口径, 低估尾部); 等权 hold(生产行为) P0 +16.53%/-65.52%、A1 +17.68%/-64.60%; 份额级 600万 S0 +15.67%/-69.19%、A1(生产采纳) +16.90%/-68.43%。空池月让年化略升(+0.8pp P0/+1.4pp A1)但回撤骤深约 20pp; 2018-21 与 2022-26 两段在 cash/hold 下逐位相同 → R51/R53/R54/R55 主窗口结论与 A1=0.70 不受口径选择影响。Y5 R50 复核(修复后的池, 600万 S0 份额级): 验证段 2021-2026 -0.27pp/年(旧 -0.2 一致); 全样本 +0.44pp/年(旧 +1.8 → 高估 4 倍); 2014-17 约 +1.7pp/年(旧 +7.4 → 作废, 建立在污染池上); 逐年阻塞影响 2014 +3.11pp/2015 +3.63pp/2016 后 <=±1.9pp。Y2 ❌ 判据作废(设计错误): 用"新开窗口 run_scenario_p3(2015-04-01,…) 起跑"当"延续序列"比 —— 空池月起跑首月即空池 → 全程空仓 0.00%, 不可比; 补充测量(不重判): 同一延续序列 2015-05~08 等权 hold -16.34% vs 份额级 -11.27%(差 5.07pp)、等权 cash 0.00%(差 11.27pp) → hold 把失真减半但仍非逐位一致, 权威口径=份额级, 等权仅作趋势参考。Y6 ❌ 2014 残差未完全解释: -7.95pp =(无阻塞-等权)-4.83pp +(阻塞)-3.11pp, 1手取整 0.000%, 残差 4.83pp > 预注册 2pp → 如实记为待查(整手权重漂移/无法按目标权重成交/现金拖累/分红税 10% 等未列入项; 同量级在别的年份是 ±1.5~1.9pp)。Y4 面板体检门: 新增 tests/test_data_panel.py 四条非循环不变量 I1(面板因子在 t 必须等于 t 时点生效的记录值, 期望值由独立 numpy searchsorted 给出)/I2(因子仅在记录日跳变)/I3(real×factor==close)/I4(非记录日 |Δreal|>12% ≤0.1%) + **I5 判别力自证**(旧写法必须违规、helper 必须 0 违规、R5 约定差异写成断言) → 默认 4s, pytest -m slow 加跑全市场层 19s; 教训: R57-W2 曾写过无判别力的判据, 本轮把"判据必须有判别力"本身变成断言。Y7 X6: 新增公共助手 src/quant_trading_01/panel.py forward_factor_series(并集 ffill 再 reindex, 无静默 1.0 兜底), P3 侧(R41 factor_round41_low_price.py)已切换并与 R57 内联写法**逐位等价**(最大绝对差 0.000e+00); **R5 两处按预注册"有差异则不做"回退** —— 统一写法 vs R5 现行约定 reindex(idx).ffill().bfill() 在 2013-06~2014-12 有 194,710 个 stock-days 差异(1,376 只, 比率中位 0.9847/p10 0.6254) → 非等价重构, 若强改会动 R5 早年历史数字; R5 面板口径统一留 R59+(须 R5 侧预注册+回归)。X1 ew_nav 增 empty_mode(默认 cash 保持既有引用逐位不变, hold=与生产一致)。X8 paper_live_p3 step 遇空池月仅打印告警, 交易/估值逻辑零改动。Y1 ✅ 生产不变: 运营窗口 2026-09-01→09-29 七账户回放 vs 生产账本逐日最大相对差 3.92e-08, output/ 零改动, pytest 30 passed + ruff 0。被修正/作废旧结论: 手册 R50 的 +1.8pp/年 → +0.44pp/年、2014-17 +7.4pp/年 → +1.7pp/年(作废); 手册 \'等权 -45.6% 作回撤参考\' → 勿再作承受力依据(权威 -68.4% A1/-69.2% S0 份额级, 生产行为口径 -64.6%/-65.5% 等权 hold)。保留不变: 主窗口 2021-2026 全部结论 + 生产采纳 A1=0.70 + 七账户账本 + R57 全部数字。代价: 测量脚本 288s; pytest 2s→4s(默认)/21s(含 slow); 未重抓数据。',
    },
]

# 探索脚本在 scripts/；共享基座在 src/quant_trading_01/（KEEP 内）；闭包互 import 为 scripts.X
SCRIPT_TO_UNIT = {s: u["name"] for u in UNITS for s in u["scripts"]}
IMPORT_RE = re.compile(
    r"(?:from\s+(?:research|scripts|quant_trading_01)\.(\w+)\s+import"
    r"|import\s+(?:research|scripts|quant_trading_01)\.(\w+))"
)
# 脚本位置与基座位置（闭包解析/存在性检查）
SCRIPTS_DIR = "scripts"
BASES_DIR = "src/quant_trading_01"

# 归档后脚本位于 archive/experiments/<unit>/（比 scripts/ 深 2 层）
# → 仓库根推导须由 `Path(__file__).resolve().parent.parent` 改为 `parents[3]`，否则归档脚本不可运行
REPO_ROOT_RE = re.compile(r"Path\(__file__\)\.resolve\(\)(?:\.parent){2,}")


def rewrite_repo_root_paths(unit_dir: str, scripts: set[str]) -> None:
    """重写移入归档单元的脚本的仓库根推导深度（保证归档副本可直接运行）。"""
    for script in sorted(scripts):
        path = os.path.join(unit_dir, f"{script}.py")
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        new_text = REPO_ROOT_RE.sub("Path(__file__).resolve().parents[3]", text)
        if new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)


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
    "migrate_full_daily_partitions": "年分区迁移工具",
    "round19_concentrated200": "小资金集中版·前200",
    "round20_extreme_scenario": "极端行情演练",
    "round21_tier1_screen": "梯队一筛选·4因子",
    "round22_price_combo": "价格水平组合验证",
    "round23_limit_aware": "涨跌停阻塞验证",
    "round25_pead": "PEAD业绩预告",
    "round26_weight_sensitivity": "R5权重敏感性",
    "round27_weight_tuning": "权重细扫·无高原",
    "round28_weight_tuning_oos": "权重样本外验证",
    "round30_shareholder": "股东户数/筹码集中",
    "round31_lhb": "龙虎榜席位结构",
    "round17_delisted": "退市股宇宙基建",
    "round24_prod_limit_aware": "阻塞引擎内置",
    "round32_execution_cost": "模拟盘滑点真实化",
    "round33_backtest_slip": "回测滑点口径统一",
    "round35_execution_cost": "执行成本模型评估",
    "round36_shortterm_screen": "周频短线因子筛选",
    "round37_f4_combo": "F4组合验证",
    "round38_weight_scan": "三因子权重扫描",
    "round39_candidates": "同向但异法候选因子",
    "round50_p3_optimize": "P3 优化空间验证",
    "round51_p3_risk_value": "P3 风险维度与未用因子验证",
    "round52_p3_composite": "P3 池内多因子合成打分",
    "round53_p3_a1_share_level": "A1 份额级八账户落地验证",
    "round55_p3_keep_scan": "P3 低波截断比例 70% 平台性敏感性",
    "round56_p3_eval_fix": "scenario_ytd_p3 估值口径修复 + 全样本份额级重跑",
    "round57_real_fix": "真实价 因子前向填充 bug 修复 + 受影响年份重算 + 全样本份额级重跑",
    "round58_pool_policy": "空池月口径裁定 + 面板体检门 + R50 阻塞复核 + 2014 残余归因",
}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def is_tracked(path: str) -> bool:
    return git("ls-files", "--error-unmatch", "--", path).returncode == 0


def parse_imports(script_path: str) -> set[str]:
    """解析脚本对 scripts/quant_trading_01 其他模块的引用（模块名集合）。"""
    with open(script_path, encoding="utf-8") as f:
        text = f.read()
    return {m.group(1) or m.group(2) for m in IMPORT_RE.finditer(text)}


def dependency_closure(scripts: list[str]) -> set[str]:
    """递归展开 scripts./quant_trading_01. 依赖，剔除白名单，返回闭包内的探索脚本（模块名，不带 .py）。

    基座（src/quant_trading_01 内）不在闭包内（留位）；scripts/ 内的探索脚本入闭包。
    """
    closure = {s[:-3] if s.endswith(".py") else s for s in scripts}
    frontier = list(closure)
    while frontier:
        s = frontier.pop()
        for dep in parse_imports(os.path.join(SCRIPTS_DIR, f"{s}.py")):
            if dep in KEEP or dep in closure:
                continue
            if os.path.exists(os.path.join(SCRIPTS_DIR, f"{dep}.py")):
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
    """闭包内互 import 改写：scripts.X → X（同目录可导入）；quant_trading_01.* 基座不变。scripts 为模块名。"""
    for script in sorted(scripts):
        path = os.path.join(unit_dir, f"{script}.py")
        with open(path, encoding="utf-8") as f:
            text = f.read()

        def repl(m: re.Match) -> str:
            mod = m.group(1) or m.group(2)
            if mod in scripts:
                return m.group(0).replace(f"scripts.{mod}", mod)
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
    main = next(
        (
            f"{s}.py"
            for s in sorted(scripts)
            # UNITS 登记可能带 .py 后缀，此处统一按"无扩展名"比较
            if s in {p[:-3] if p.endswith(".py") else p for p in unit["scripts"]}
        ),
        None,
    )
    run_cmd = (
        f".venv/bin/python archive/experiments/{unit['name']}/{main}   # cwd=仓库根"
        if main
        else "（脚本留位 scripts/，无需复现命令）"
    )
    lines = [
        f"# {unit['name']} — 已归档探索",
        "",
        f"> 由 `scripts/archive_experiment.py` 于 {date.today().isoformat()} 归档。",
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
        "依赖的共享基座 `src/quant_trading_01/reversal_factor.py` / "
        "`src/quant_trading_01/dividend_factor.py` 因被生产链依赖而留位，import 路径不变。",
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
    # 静态 import 检查：闭包外依赖（基座/KEEP）须在 src/quant_trading_01 或 scripts/ 存在；闭包内裸模块须同目录存在
    for script in sorted(scripts):
        path = os.path.join(unit_dir, f"{script}.py")
        for dep in parse_imports(path):
            if dep in scripts and not os.path.exists(
                os.path.join(unit_dir, f"{dep}.py")
            ):
                raise RuntimeError(f"闭包内依赖缺失: {path} -> {dep}")
            if dep not in scripts and not (
                os.path.exists(os.path.join(BASES_DIR, f"{dep}.py"))
                or os.path.exists(os.path.join(SCRIPTS_DIR, f"{dep}.py"))
            ):
                raise RuntimeError(
                    f"留位依赖缺失: {path} -> {dep}（须在 {BASES_DIR} 或 {SCRIPTS_DIR}）"
                )
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
                os.path.join(SCRIPTS_DIR, f"{script}.py"),
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
        # 3.5 重写仓库根推导深度（脚本移入归档目录后 parent.parent 会指错）
        rewrite_repo_root_paths(unit_dir, closure)
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
        git("restore", "-q", "--worktree", "--", "scripts/", "src/", "docs/")
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
        print("  已回滚（scripts/src/docs 还原、output 归位、INDEX/README 清理）")
        return 1
    print(f"== 完成: {unit_dir} ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
