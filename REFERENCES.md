# 参考项目取用说明

## 已吸收

- `ccxt/ccxt`: 可选的交易所统一适配层。项目新增 `btc5m/ccxt_adapter.py`，统一账户、余额、市场规则、行情和现货市价单接口。
- `YicunAI/Pnlclaw-community`: 借鉴本地优先、行情/策略/纸上交易/风险控制分层，以及回测必须单独验证手续费和滑点的结构。
- `txbabaxyz/polyrec`: 借鉴实时数据记录、指标面板、信号和 P/L 可观测性。

## 未直接复用

- Polymarket/Kalshi 项目交易的是二元预测合约，具有独立的市场生命周期、订单簿和结算规则，不能直接当作 Binance BTC 现货下单模块。
- 这些仓库的策略结果、收益数字和 API 密钥配置不应直接复制到本项目。

本项目保留原生 Binance REST 客户端作为回退，`BTC_USE_CCXT=true` 时才启用 CCXT。

## Binance 产品边界

- Binance Spot API 用于 BTCUSDT 行情、账户余额和受保护的现货 BUY/SELL。
- Binance Prediction Markets 是独立产品，不能使用 Spot `/api/v3/order`
  直接下 UP/DOWN 合约单。
- 当前实现先提供完整纸上预测市场层；真实预测市场执行需要按官方钱包、
  市场和订单接口单独实现并经过测试，不把未验证的端点伪装成可用功能。
