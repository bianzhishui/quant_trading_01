# -*- coding: utf-8 -*-
"""A 股交易成本与规则常量（可按你的券商费率调整）。"""
from __future__ import annotations

COMMISSION_RATE = 2.5e-4   # 佣金万 2.5（买卖双向）
MIN_COMMISSION = 5.0       # 单笔最低佣金 5 元
STAMP_TAX_RATE = 5e-4      # 印花税 0.05%（仅卖出）
TRANSFER_FEE_RATE = 1e-5   # 过户费 0.001%（双边，沪市；简化为全市场）
SLIPPAGE = 1e-3            # 滑点 0.1%（市价单冲击）
LOT_SIZE = 100             # 一手 = 100 股，按手取整
INIT_CASH = 1_000_000.0    # 初始资金 100 万
# T+1：当日买入的股票当日不可卖 —— 引擎中通过“只卖 T-1 及更早的持仓”实现
