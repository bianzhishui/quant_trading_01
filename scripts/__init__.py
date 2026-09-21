"""scripts —— 可执行脚本包（策略/运营/抓取入口）。

脚本间互调用走 `from scripts.X import Y`（模块级不读 sys.argv，见 AGENTS.md §5.6）；
共享框架从 `quant_trading_01.*` 导入。运行: python scripts/<name>.py [args]
"""
