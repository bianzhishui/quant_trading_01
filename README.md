# quant_trading_01 — A 股量化交易学习项目

个人 A 股量化的起步骨架：**baostock/akshare 免费数据 + 本地事件式回测引擎（含 A 股规则）+ 双均线策略示例**。

## 快速开始

本项目使用 **uv** 管理 Python 环境与依赖（锁文件 `uv.lock` 保证可复现）。

```bash
# 安装 uv（一次性；macOS）
brew install uv          # 或: curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建/同步环境（按 uv.lock 精确还原依赖，自动建 .venv）
uv sync

# 运行
uv run run_backtest.py --synthetic                  # 离线演示（合成随机行情）
uv run run_backtest.py                              # 贵州茅台真实日线 双均线回测（带缓存）
uv run run_backtest.py --symbol 300750 --short 10 --long 120   # 换标的/参数

# 测试
uv run pytest                                       # 引擎正确性单元测试 (4项)
```

> 提示：`run_backtest.py` 的 shebang 已改为 `uv run`，也可直接 `./run_backtest.py --synthetic`。
>
> 数据源：首选 **baostock**（稳定、免费、含前复权），失败时自动兜底 **akshare**(东方财富源)。

## 目录结构

```
run_backtest.py        回测入口脚本（shebang 已指向 uv run）
pyproject.toml         项目与依赖声明
uv.lock                依赖锁文件（保证环境可复现）
src/
  data_loader.py       baostock(首选)+akshare(兜底) 取数 + CSV 本地缓存 (+ 合成数据)
  backtest.py          事件式回测引擎
  costs.py             A股费用与规则常量（佣金/印花税/T+1/一手100股）
strategies/
  dual_ma.py           双均线择时策略示例
tests/
  test_backtest.py     引擎正确性单元测试 (uv run pytest)
data/                  行情缓存（自动生成）
output/                回测图表与成交明细（自动生成）
```

## 引擎处理的 A 股关键约束

| 规则 | 处理方式 |
|---|---|
| **T+1** | 每日先卖后买，当日买入次日才能卖 |
| **信号延迟** | T 日收盘计算权重 → T+1 开盘价撮合，杜绝未来函数 |
| **涨跌停** | 开盘价触及 ±limit% 视为无法成交并计数（主板10%/创业科创20%自动判断）|
| **成本** | 佣金万2.5(最低5元) + 卖出印花税0.05% + 过户费 + 0.1%滑点 |
| **整手交易** | 按 100 股取整；调仓死区 2%，避免微量换手 |

引擎正确性已由单元测试验证：信号严格 T+1 开盘执行、清仓后买卖股数一致、NaN 权重安全。

## 已知简化（后续可自行扩展）

- 单标的支持；多股票组合需要改造为逐日循环多列权重矩阵
- 不支持做空、融资融券、分红送转再投资（前复权价已隐含分红收益）
- 分钟级回测需换数据源与撮合逻辑
- ETF 回测被多扣了卖出印花税（现实中 ETF 免印花税），结果略保守

## research/ — 市场规律研究

```bash
uv run python research/weekday_effect.py               # 沪深300 星期效应
uv run python research/weekday_effect.py --symbol 000905   # 中证500 交叉验证
```

四层验证框架：描述统计 → 显著性检验(Welch t + 置换检验, Bonferroni 校正) →
分年代稳定性 → 可交易性(扣成本)。任何"市场规律"都应过这四关再谈利用。

已完成的发现（2005~2026，三指数交叉验证）：
**周四负效应**在 2005-2018 显著存在（中证500 上 -15~-20bp/天），
但 2019 年后衰减至 ≈0 —— 与 2016 年新股信用申购改革（周四预缴款制度终结）的时间线吻合。
一个"曾被文献记录、后被制度变迁消灭"的活样本。

## 学习路线建议

1. 先 `--synthetic` 跑通，读懂 `backtest.py` 的逐日循环
2. 拉真实数据，观察策略 vs 买入持有 vs 沪深300
3. 改造策略：把 `strategies/dual_ma.py` 的权重逻辑换成你自己的想法（动量、轮动、多因子…）
4. 加参数扫描看过拟合：同一策略在不同 (short, long) 下表现差异越大越危险
5. 用聚宽/米筐模拟盘验证 3 个月后再考虑 QMT 实盘

## 常用后续工具

- **Backtrader**：更完整的开源回测框架
- **Tushare Pro**：更稳定的数据源（积分制）
- **QLib**（微软）：机器学习量化研究平台
- **QMT/PTrade**：券商程序化实盘接口（有资金门槛，后期再说）
