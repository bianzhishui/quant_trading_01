# 探索归档索引

> 本索引由 `research/archive_experiment.py` 维护。归档纪律（AGENTS.md）：
> 探索结束 → 在 plan 文档写 §0 结论 → 跑 `archive_experiment.py <脚本或单元>` → 本表登记。
> 状态：`✅ 通过并入生产` · `❌ 已否决` · `🟡 部分通过` · `⏸ 搁置` · `🛠 工具/演示`
>
> 已归档探索的完整清单（代码 + plan + 结论输出）见各单元目录；共享基座
> `reversal_factor.py` / `dividend_factor.py` 因被生产链（`paper_live`/`paper_trade`）依赖而**脚本留位**，
> 其 plan 与结论输出照常归档，详见对应单元。

| 单元 | 方向 | 状态 | 结论摘要 | 位置 | 归档日期 |
|---|---|---|---|---|---|
| convertible_double_low | 可转债双低 | ⏸ 搁置 | 可转债双低轮动（独立方向，结论见 plan §0） | archive/experiments/convertible_double_low/ | 2026-09-09 |
| dividend_factor | 高股息 | ⏸ 搁置 | 高股息四组对照：按失败处置协议记录（结论见 plan §0） | archive/experiments/dividend_factor/ | 2026-09-09 |
| etf_exploration | ETF 轮动 | ⏸ 搁置 | ETF 动量/低波轮动与候选研究（独立方向，失败处置见 plan §0） | archive/experiments/etf_exploration/ | 2026-09-09 |
| ew_base | 等权底仓 | ⏸ 搁置 | 等权底仓可行性评估（轻量，结论见 plan §0） | archive/experiments/ew_base/ | 2026-09-09 |
| fundamental_pipeline | 基本面数据管线 | ✅ 通过并入 | 基本面数据管线建成（src/fundamental.py → 已迁移 research/fetch_stock_basic.py 生产宇宙刷新）；高股息实验已归档 dividend_factor 单元 | archive/experiments/fundamental_pipeline/ | 2026-09-14 |
| grid_demo | 网格演示 | 🛠 工具/演示 | 网格交易演示（无 plan 文档） | archive/experiments/grid_demo/ | 2026-09-09 |
| migrate_full_daily_partitions | 年分区迁移工具 | 🛠 工具/演示 | 一次性迁移工具：full_daily.parquet 单文件 → 按年分区（已完成使命，R17 基建产物） | archive/experiments/migrate_full_daily_partitions/ | 2026-09-14 |
| reversal_short_term | 短期反转 | ❌ 已否决 | 短期反转否决（IC 不足 + 15bp 成本致命） | archive/experiments/reversal_short_term/ | 2026-09-09 |
| round03_combination | Amihud×动量组合 | ✅ 通过并入 | Amihud+中期动量等权组合确立为策略主体（+9.8pp，夏普0.91） | archive/experiments/round03_combination/ | 2026-09-09 |
| round04_risk_breakers | 风控·熔断/择时 | 🟡 部分通过 | 风控系列：4b 回撤熔断/4c 均线择时正交互补（部分通过）；4d 双熔断否决（防守过度，股灾恢复期钳制踏空） | archive/experiments/round04_risk_breakers/ | 2026-09-09 |
| round05_industry_neutral | R5 行业中性 | ✅ 通过并入 | R5 行业中性化升级为策略主体（行业内 alpha 真实存在） | archive/experiments/round05_industry_neutral/ | 2026-09-09 |
| round06_r5_ma | R5+均线择时 | ❌ 已否决 | R5+4c 均线择时叠加否决（择时代价占比过高） | archive/experiments/round06_r5_ma/ | 2026-09-09 |
| round07_fullmarket | 全市场扩池 | ✅ 通过并入 | 全市场扩池 R5：幸存者偏差仅 1.1pp，泛化成立 | archive/experiments/round07_fullmarket/ | 2026-09-09 |
| round08_live_validation | 实盘化验证 | ✅ 通过并入 | 实盘化验证：全口径成本下超额 +2.56pp，可执行 | archive/experiments/round08_live_validation/ | 2026-09-09 |
| round09_holdings_count | 持仓数量敏感度 | ⏸ 搁置 | 持仓数量敏感度实验：575 并非必须，结论见 plan §0 表 | archive/experiments/round09_holdings_count/ | 2026-09-09 |
| round10_paper_sim | 模拟盘程序 | ✅ 通过并入 | 模拟盘程序(paper_trade/paper_live) share级全口径回放 300万+4.37pp/600万+4.87pp, 真实可执行→已生产化(四账户运营); 脚本留位 research/ | archive/experiments/round10_paper_sim/ | 2026-09-14 |
| round11_fullbuy | 全选满仓 | ❌ 已否决 | 全选满仓变体否决（换手 2.2 倍 + 规则脆弱） | archive/experiments/round11_fullbuy/ | 2026-09-09 |
| round12_15_concentrated | 小资金规模研究 | ⏸ 搁置 | 小资金规模研究收束：20万不建议（费用吃光）/ 60万可行下限(+3.4~3.6pp) / 300万最优起点(+4.43pp) / 600万效率饱和(+4.72pp) | archive/experiments/round12_15_concentrated/ | 2026-09-09 |
| round16_crowding_timing | 拥挤度择时 | ❌ 已否决 | 拥挤度极值择时否决（风控五轮收束：压不住回撤且牺牲超额） | archive/experiments/round16_crowding_timing/ | 2026-09-09 |
| round17_delisted | 退市股宇宙基建 | ✅ 通过并入 | 退市股宇宙/年分区基建(R17): full_daily 年分区+3409只(含215退市股)+qfq回退 | archive/experiments/round17_delisted/ | 2026-09-13 |
| round18_factor_health | R5 因子失效监控 | ✅ 通过并入 | 因子失效监控实施(R18): 逐月末RankIC+μ±2σ带状态灯, 现行仪表盘(factor_health.py 留位 research/) | archive/experiments/round18_factor_health/ | 2026-09-14 |
| round19_concentrated200 | 小资金集中版·前200 | ❌ 已否决 | 60万 前200+满仓补买 +2.96pp/82%用/2.32%费 未达标; 集中度补买曲线闭合 100(+3.59)>150(+3.41)>200(+2.96), 最优仍为前100+补买; 补买对前200仅堆仓位不增超额 | archive/experiments/round19_concentrated200/ | 2026-09-09 |
| round20_extreme_scenario | 极端行情演练 | 🛠 工具/演示 | 极端行情回放演练(4场景): 满配极端段-20~-50%级回撤(印证风控收束); 60万现金缓冲减震约一半(S1差18pp/S3差17pp); S4扛住31-41交易日恢复全年+4~6%; S3微盘危机唯一跑输大盘——实操指南入运营手册§10.4 | archive/experiments/round20_extreme_scenario/ | 2026-09-09 |
| round21_tier1_screen | 梯队一筛选·4因子 | 🟡 部分通过 | 梯队一4因子筛选: 价格水平(低价股)单因子4/4通过(+3.0pp@15bp/换手1.1/三段全正/与Amihud截面-0.19)进候选池, 但Round22组合验证否决并入; 低beta/长期反转/下行波动未通过 | archive/experiments/round21_tier1_screen/ | 2026-09-09 |
| round22_price_combo | 价格水平组合验证 | ❌ 已否决 | 三因子(+价格水平)超额+4.20→-0.25pp崩塌, Jaccard44.8%向差分散(分散≠增强); 3/5维持R5, 价格水平降级单因子参考——单因子通过≠可并入(组合验证守门) | archive/experiments/round22_price_combo/ | 2026-09-09 |
| round23_limit_aware | 涨跌停阻塞验证 | ✅ 通过并入 | 涨跌停阻塞验证(S3-跟随): 阻塞损失-0.31pp@300万/-0.95pp@60万(四账户全≥-1.0pp), 三段全正策略结论不变; 结论并入生产Round24(引擎内置+实盘SOP入运营手册§8.7) | archive/experiments/round23_limit_aware/ | 2026-09-10 |
| round24_prod_limit_aware | 阻塞引擎内置 | ✅ 通过并入 | 生产引擎内置涨跌停阻塞(S3-跟随)+账本统一真实口径; 回测+账本口径一致 | archive/experiments/round24_prod_limit_aware/ | 2026-09-13 |
| round25_pead | PEAD业绩预告 | ❌ 已否决 | PEAD业绩预告后漂移: IC+0.003(t=0.46)极弱/分组不单调(Q3峰)/超额+0.4pp, 1/4未通过; 与中期动量IC序列相关+0.629强重叠(非独立信息源)——不进入组合验证, R5不变 | archive/experiments/round25_pead/ | 2026-09-10 |
| round26_weight_sensitivity | R5权重敏感性 | ⏸ 搁置 | R5权重敏感性: 50:50非最优且脆弱(邻域波动+3.17pp>0.5pp); Amihud权重单调递增超额(−0.37→+6.38pp)——Amihud是超额主源, 动量是稀释项; 生产不动(冻结), 是否调权重=用户决策点(需另开预注册+细扫防过拟合) | archive/experiments/round26_weight_sensitivity/ | 2026-09-10 |
| round27_weight_tuning | 权重细扫·无高原 | ⏸ 搁置 | 权重细扫0.55~0.80: 超额单调递增至0.80(+7.04pp)但无高原(双侧高原判据全❌); 端点0.80伪通过被双侧判据拦截(数据挖掘陷阱); 结论: 趋势真实但无稳健选择——由Round28扩展扫描+样本外验证接续 | archive/experiments/round27_weight_tuning/ | 2026-09-10 |
| round28_weight_tuning_oos | 权重样本外验证 | ✅ 通过并入 | 扩展扫描0.80~1.00顶点0.95(+7.49%)+样本外验证(训练14-21独立选权→验证22-26 超额差+6.5pp)+高原0.90~1.00波动0.15pp——四项全过; 用户批准折中w=0.85落地生产(保留15%动量缓冲), 账本重建 | archive/experiments/round28_weight_tuning_oos/ | 2026-09-10 |
| round30_shareholder | 股东户数/筹码集中 | ❌ 已否决 | 股东户数/筹码集中度: 单因子3/4(IC-0.02 t=-4.57极显著, 与Amihud/动量正交0.1级), 但等权三因子并入崩塌(+7.31→+3.62pp, 稀释Amihud主源)——正交≠可并入(R22教训重演); 不并入R5; 判据缺陷记录(①超额应为门禁) | archive/experiments/round30_shareholder/ | 2026-09-11 |
| round31_lhb | 龙虎榜席位结构 | ❌ 已否决 | 龙虎榜净买占比: 未通过(1/4)——机制假设被否定: 上榜后1/2/5日均值+0.32/+0.28/+0.37%(上榜=强势延续非散户追高看空); IC无效/分组U型/超额+0.3pp; 正交(-0.04)但无信号; 月度截面无预测力, 不进入组合验证 | archive/experiments/round31_lhb/ | 2026-09-11 |
| round32_execution_cost | 模拟盘滑点真实化 | ✅ 通过并入 | 模拟盘账本补上滑点15bp(账本真实化): 300万 replay_w 对照 slip=0 +8.78%→15bp +7.63%; 每省1bp实际成本≈超额+0.072pp(成本敏感度回测); 四账户从9月重新建仓含滑点 | archive/experiments/round32_execution_cost/ | 2026-09-13 |
| round33_backtest_slip | 回测滑点口径统一 | ✅ 通过并入 | 回测默认滑点0→15bp, 回测=运营=基准三口径统一; replay四账户重跑: 60/100/300/600万超额+2.83/+4.92/+6.08/+6.28%, 费用4.48/4.35/3.62/3.36%/年 | archive/experiments/round33_backtest_slip/ | 2026-09-13 |
| round34_config | 全量配置化 | ✅ 通过并入 | 全量配置化(R34): YAML+惰性读取+冻结校验, 判定6/6+复检全过; 扩展含fetch波/惰性全覆盖/R5窗口配置化/src迁移; config.py+default.yaml 留位 research/ | archive/experiments/round34_config/ | 2026-09-14 |
| round35_execution_cost | 执行成本模型评估 | ✅ 通过并入 | 执行成本模型评估: A固定15bp +7.57%维持生产口径; B流动性依赖 +7.02%(−0.55pp, 等权加权滑点21.1bp>15bp, flat低估小盘真实成本) 以 --slip-by-amount 监控并入; C VWAP否决(免费分钟源历史不足官方文档证实+第三方源不可低成本验证); 18测试通过 | archive/experiments/round35_execution_cost/ | 2026-09-16 |
| round36_shortterm_screen | 周频短线因子筛选 | 🟡 部分通过 | 周频短线因子筛选(5日持有,全市场非ST池,639期): F4低成交额5 通过(4/4)(IC−0.077 t=−10.8, 超额15bp+11.9pp/35bp+7.1pp, 三段全正, 换手10.3) 但与生产Amihud截面相关−0.85强同源, 正交残差IC−0.075显著, 控制市值后仍−0.060,B口径31.7bp成本存活+7.9pp→非成本/市值假象, 需组合验证守门(R22/R30协议); F3低换手5 部分通过(3/4,超额仅+1.3pp量级不足); 短反转/低波动/换手突变/短动量 否决(周频反转Q1接飞刀−12.6pp, 与月频对照更不可交易) | archive/experiments/round36_shortterm_screen/ | 2026-09-18 |
| round37_f4_combo | F4组合验证 | ⏸ 搁置 | F4低成交额5组合验证(140期,300万share级,15bp): B等权三因子未通过(核心门禁①超额仅+0.57pp<+1pp, 未崩塌但无增量, 与R30正交崩塌对照: 同源稀释无害/正交破坏互补); C(0.85Amihud+0.15F4) 4/5组合升级候选(+8.30%, 超额+1.10pp, 三段全正, 回撤/换手更优) 唯一失败⑤Jaccard 78.6%(同源高重叠属设计使然); 解释验证: C>纯Amihud1.0(+7.10%)→F4有真实短频增量非权重复现, 但本质是Amihud短频精化非新信息源; 维持R5生产, C为决策点(替换动量=改冻结选股逻辑须另预注册); 追加D臂(0.45A+0.15动量+0.4F4) 5/5全过(+8.65%, Jaccard70.2%), 权重扫描9点F4≥0.30高原(ew 9.7~10.4%/share级D1+9.09%D2+8.84%)→非尖峰, F4有真实增量获双重印证, 但仍须另开预注册落地 | archive/experiments/round37_f4_combo/ | 2026-09-18 |
| round38_weight_scan | 三因子权重扫描 | 🟡 部分通过 | 三因子权重最优配比扫描(35点ew_nav+share级复核+样本外R28协议): 样本外四项判据全过(w_train*=A0.40/M0.10/F40.50: 训练+9.80%→验证+12.62% vs A+10.32% 差+2.30pp, 网格内部, 全区间+10.40%≥A, 双侧高原0.49pp<0.5pp); 候选区间 [Amihud0.40~0.50×动量0.05~0.10×F4 0.40~0.50], share级最优点W1(0.50/0.05/0.45)超额+9.27%(三段全正/高原0.15pp最稳); F4增量三重独立证据确认(R36正交IC→R37解释验证→R38样本外); 本质=调整Amihud测量窗口(21日→5日)非新信息源, 代价=动量缓冲15%→5~10%风格年更脆弱; R5生产未动, 呈用户决策 | archive/experiments/round38_weight_scan/ | 2026-09-18 |
| round39_candidates | 同向但异法候选因子 | ❌ 已否决 | '同向但异法'候选因子验证(4因子月频筛+组合验证): C1低换手21/C2换手波动21std 部分通过(3/4, IC显著−0.084/−0.092 t≤−5.6, 单调完美, Jaccard 16.9%极异法, 但超额仅+1.7/+2.0%<3pp不进组合验证); C3市值代理 通过(4/4,+9.4%)但10%并入w* 组合验证3/5不并入(超额+0.24pp<+1pp, Jaccard 90.6%同法重复暴露→R22教训重演); C4短动量5/21 未通过(月频方向=反转, 高动量组−10.5%); 框架结论: 异法度是必要不充分条件, 最终裁判=组合增量门禁; 无新因子并入, R5/w*生产不变; 补验(2026-09-20): C1/C2正交残差IC显著(−0.049/−0.060)但10%并入w*组合验证双双3/5不并入(超额−0.49/−0.51pp, 并入后Jaccard 87%→异法度被主权重稀释), C3正交后+0.041仍显著但90.6%同法; 框架结论强化: 异法度+正交显著≠组合增益, 最终裁判=增量门禁, 三条件缺一即否决 | archive/experiments/round39_candidates/ | 2026-09-20 |
| screen01_factor_screen | 因子筛选·中期动量 | 🟡 部分通过 | Round 1 批量筛选：中期动量因子判定部分通过，入组合观察名单 | archive/experiments/screen01_factor_screen/ | 2026-09-09 |
| screen02_factor_screen | 因子筛选·Amihud | ✅ 通过并入 | Round 2 批量筛选：Amihud 非流动性首个全通过因子（+7.3pp） | archive/experiments/screen02_factor_screen/ | 2026-09-09 |
| weekday_effect | 周内效应 | ⏸ 搁置 | 周内效应检验（独立方向，无 plan 文档） | archive/experiments/weekday_effect/ | 2026-09-09 |
| yearly_breakdown | 年度分解工具 | 🛠 工具/演示 | 年度收益分解分析工具（无 plan 文档） | archive/experiments/yearly_breakdown/ | 2026-09-09 |
