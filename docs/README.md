# docs — 项目文档目录

存放设计文档、研究方案、决策记录（与代码分离，research/ 只放可执行脚本）。

| 文档 | 类型 | 状态 |
|---|---|---|
| [etf_momentum_plan.md](etf_momentum_plan.md) | 策略研究方案（预注册） | 已实施，判定=未通过（§0 归档） |
| [fundamental_pipeline_plan.md](fundamental_pipeline_plan.md) | 基建方案 | 已实施（管线+高股息实验数据就绪） |
| [dividend_factor_plan.md](dividend_factor_plan.md) | 策略研究方案（预注册） | 已实施，判定=未通过（§0 归档，含归因读数） |
| [ew_base_plan.md](ew_base_plan.md) | 可行性评估（预注册） | 已实施，机械判定=成立，实用建议=中证500/1000 指数产品（§0 归档） |
| [ew_base_execution.md](ew_base_execution.md) | **核心层构造方案（执行版）** | **现行有效**——唯一通过验证的持仓方案 |
| [convertible_double_low_plan.md](convertible_double_low_plan.md) | 策略研究方案（预注册） | 已实施，判定=部分通过（②③过线，④30bp压测差0.2pp未过） |
| [reversal_factor_plan.md](reversal_factor_plan.md) | 策略研究方案（预注册） | 已实施，判定=未通过（②④过线，①强度不足、③成本后超额+0.8pp未过） |
| [factor_candidates.md](factor_candidates.md) | **因子候选池索引（持续更新）** | 现行有效——三梯队 26 个候选因子 + 检验顺序 + 避坑清单 |
| [factor_screen_round1_plan.md](factor_screen_round1_plan.md) | 策略研究方案（预注册） | 已实施，判定=中期动量部分通过(3/4)进观察名单；BP/低波动/距52周高点未通过 |
| [factor_top10.md](factor_top10.md) | **因子精选清单（10 个可用）** | 现行有效——覆盖 10 个独立信息源 + 数据补全清单 + 检验顺序 |
| [factor_screen_round2_plan.md](factor_screen_round2_plan.md) | 策略研究方案（预注册） | 已实施，判定=**Amihud 通过(4/4) 进入组合候选池**；反转/中期动量部分通过；低换手/EP/股息连续性/两融/北向/ROE 未通过；小市值暂缓（§0 归档） |
| [factor_round3_combination_plan.md](factor_round3_combination_plan.md) | 策略研究方案（预注册） | 已实施，判定=**C 臂（Amihud+中期动量等权打分）通过(4/4)，确立为策略主体**；反转在组合中再次确认不可用（§0 归档） |
| [factor_round4_plan.md](factor_round4_plan.md) | 策略研究方案（预注册） | 已实施，判定=**R4a（剔除合成分极端5%）未通过(2/4)**——回撤主因是市场级股灾（2015），选股层改不动，转向风控层熔断（§0 归档） |
| [factor_round4b_drawdown_breaker_plan.md](factor_round4b_drawdown_breaker_plan.md) | 策略研究方案（预注册） | 已实施，判定=**R4b（C+回撤熔断）部分通过(3/4)**——2015 急跌压到 −27%、2018 阴跌反成新低 −41%；夏普升 0.98 但超额 −4.1pp；策略主体仍为满仓 C（§0 归档） |
| [factor_round4c_trend_breaker_plan.md](factor_round4c_trend_breaker_plan.md) | 策略研究方案（预注册） | 已实施，判定=**R4c（C+均线择时）部分通过(3/4)**——2018 阴跌 −22.3%（补上 4b 的洞）、2022/2024 均大幅改善，但 2015 顶部急跌滞后（−51.5%）；与 4b 互补（§0 归档） |
| [factor_round4d_dual_breaker_plan.md](factor_round4d_dual_breaker_plan.md) | 策略研究方案（预注册） | 已实施，判定=**R4d（双熔断叠加）未通过(2/4)**——两套信号在股灾恢复期互相钳制、踏空反弹，防守过度；风控层研究收束，最终策略主体=满仓 C（§0 归档） |
| [factor_round5_industry_neutral_plan.md](factor_round5_industry_neutral_plan.md) | 策略研究方案（预注册） | 已实施，判定=**R5（行业内排名）通过(4/4)**——行业内 alpha 真实存在（+5.7pp），行业中性化采纳为默认策略；行业 beta 贡献 4.0pp 恰压 N4 边界（§0 归档） |
| [factor_round6_r5_ma_plan.md](factor_round6_r5_ma_plan.md) | 策略研究方案（预注册） | 已实施，判定=**R5+4c（R5+均线择时）未通过(2/4)**——R5 超额已薄买不起均线择时；当前池最终默认保留 R5（§0 归档） |
| [factor_round7_fullmarket_validate_plan.md](factor_round7_fullmarket_validate_plan.md) | 策略研究方案（预注册） | 已实施，判定=**全市场 R5 通过(4/4)**——扩池 3194 只后超额 +4.6pp，幸存者偏差贡献仅 1.1pp，策略泛化成立、超额真实；全市场 R5 定为最终策略（§0 归档） |
| [factor_round8_live_validation_plan.md](factor_round8_live_validation_plan.md) | 策略研究方案（预注册） | 已实施，判定=**实盘化验证通过(4/4)**——流动性依赖成本 s=40bp 下超额 +2.56pp、flat70bp 贴线 +0.09pp、可交易性极佳（AUM5000万 p95<1%）、阻塞损失 0.18pp；附模拟盘起点持仓（575 只）；自检修正成本口径（§0 归档） |
| [factor_round9_holdings_count_plan.md](factor_round9_holdings_count_plan.md) | 策略研究方案（预注册） | 已实施，判定=**持仓数量敏感度未通过(2/4)**——减少持仓数恶化 alpha（超额@15bp 4.65→0.90，前2% 真实成本 −2.97%）；575 是 alpha 最优点；持仓数由 1 手约束的资金量决定（≥300万满仓/100-300万前10%/ <100万难跑）（§0 归档） |
| [strategy_final_spec.md](strategy_final_spec.md) | 最终策略规格（权威） | 全市场 R5 完整可执行规格 + 业绩 + 边界 + 实盘指引（定稿） |
| [strategy_investment_plan.md](strategy_investment_plan.md) | 实盘投资方案（可执行手册） | 账户/工具/费率/建仓/月度调仓/成本/监控全流程；含"待券商确认项"清单 |
| [factor_round10_paper_sim_plan.md](factor_round10_paper_sim_plan.md) | 模拟盘程序（预注册） | 已实施，判定=**真实可执行**——share级全口径回放 300万超额 +4.37pp / 600万 +4.87pp（真实价/1手/现金/分红/费率税全含）；**§5 长期运行系统 paper_live.py（300万/600万账本, 月度自动调仓, 基准归一跟踪超额）已交付**；程序 research/paper_trade.py + paper_live.py（§0/§5 归档） |

## 约定

- **命名**：`{主题}_{类型}.md`，如 `etf_momentum_plan.md`、`grid_findings.md`
- **研究方案类文档**遵循预注册原则：回测实施前写死假设/规则/判定标准，
  实施后修改必须升版本号并注明原因
- 研究结论若已成文，在主 README 的对应章节加一行链接指向这里
