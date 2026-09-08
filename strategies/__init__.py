# -*- coding: utf-8 -*-
"""策略集合。每个策略是一个函数：输入行情 DataFrame，输出“目标仓位权重”序列（0~1）。

约定（很重要，避免未来函数）：
- 权重在每根 K 线的**收盘时刻**计算，只能用到截至当日的数据；
- 回测引擎会自动把权重延后一根 K 线、用次日开盘价撮合。
"""

from .dual_ma import dual_moving_average

__all__ = ["dual_moving_average"]
