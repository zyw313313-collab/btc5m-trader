# BTC 5m Trader

[English](README.md) | 中文

一个用于研究和纸上交易的 BTC 5 分钟实时分析系统。项目连接 Binance
公开行情，实时计算 BTCUSDT 的价格、成交方向、盘口压力和短线预测，并在本地
网页仪表盘中展示交易决策、收盘预测、风险和历史记录。

> 重要：本项目不保证盈利。5 分钟级别的加密资产方向噪声很大，界面中的概率
> 不是经过充分校准的真实胜率。默认配置不会提交真实订单。

## 功能概览

- 接收 Binance BTCUSDT 实时成交、最优买卖盘、1 秒 K 线和已收盘的 5 分钟 K 线。
- WebSocket 不可用时，自动使用 REST 轮询作为备用数据源。
- 在本地 SQLite 中保存历史 5 分钟 K 线，用于训练和回测。
- 使用价格、成交量、RSI、EMA、ATR、波动率和时间特征训练在线逻辑模型。
- 提供可选的深度序列参考模型，用于对比研究，不默认参与交易决策。
- 单独计算当前 5 分钟周期的收盘方向预测。
- 分析主动买入/卖出成交压力、买卖一档盘口不平衡和短线动量。
- 将手续费、滑点、价差、数据延迟、预期收益和风险限制纳入决策。
- 提供 `WAIT`、`NO_TRADE`、`ENTER_UP`、`ENTER_DOWN`、`HOLD` 和 `CLOSE`
  等实时状态。
- 提供现货网格策略规划器。网格模块只生成纸上策略，不提交网格订单。
- 本地网页界面展示实时 K 线、AI 信号、收盘预测、盘口压力、网格价格、
  账户状态、纸上仓位和历史记录。

## 产品边界

Binance 现货账户和 UP/DOWN 预测市场不是同一个产品：

- Binance 现货 API 使用 BTCUSDT 的 `BUY` 和 `SELL`。
- 项目中的 UP/DOWN 预测市场目前是透明的纸上模拟，不是 Binance 真实预测
  市场下单适配器。
- `BTC_LIVE_TRADING=true` 只控制受保护的 Binance 现货交易，不会开启真实
  UP/DOWN 预测市场交易。

## Windows 快速开始

### 环境要求

- Windows PowerShell
- Python 3.11 或更高版本
- 可以访问 Binance 公开行情接口的网络环境

### 安装

```powershell
git clone https://github.com/zyw313313-collab/btc5m-trader.git
cd btc5m-trader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 启动实时仪表盘

```powershell
python -m btc5m.main serve
```

浏览器打开：

```text
http://127.0.0.1:8787
```

Windows 用户也可以双击项目根目录的：

```text
Start-BTC5M.cmd
```

该启动器会启动本地服务并打开仪表盘。项目已有桌面快捷方式时，也可以直接
双击桌面快捷方式。

## 实时计算逻辑

系统会持续刷新以下数据：

- 当前 5 分钟周期的开始时间、结束时间和倒计时。
- 周期开盘价、当前价格和价格变化百分比。
- 近 15 秒、60 秒主动买卖成交量不平衡。
- 最优买价、最优卖价、盘口数量不平衡和价差。
- 短线动量、波动率、RSI、EMA 和 ATR 等指标。
- 模型预测概率、收盘方向、置信度、预期收益和建议仓位。
- 手续费、滑点、价差和数据过期时间。

实时决策不是“只要 UP 概率高就买入”。默认规则如下：

| 状态 | 含义 |
| --- | --- |
| `WAIT` | 新周期开始后的观察阶段，默认前 30 秒不主动开仓 |
| `NO_TRADE` | 数据、价差、概率、成交压力、成本、时间或风险条件不满足 |
| `ENTER_UP` | UP 方向通过实时数据、市场压力和成本过滤 |
| `ENTER_DOWN` | DOWN 方向通过实时数据、市场压力和成本过滤 |
| `HOLD` | 已有仓位，当前信号没有明确失效 |
| `CLOSE` | 收盘预测反转、触发止盈/止损或接近结算且适合退出 |

通常只有同时满足以下条件，系统才会产生候选入场信号：

1. 行情数据新鲜，盘口价差没有超过限制。
2. 方向概率达到配置阈值，默认至少为 `64%`。
3. 模型、成交压力、盘口和短线动量中至少有足够数量的信号一致。
4. 扣除手续费和滑点后的预期收益为正，并达到最低 EV 要求。
5. 入场方向没有和清晰相反的 5 分钟收盘预测冲突。
6. 不在周期最后的禁止入场时间内，也没有触发熔断或仓位限制。

因此，系统可以给出“等待”“不要出手”“持有”或“平仓”建议，而不是每秒
强行给出买入方向。

## 5 分钟收盘预测

入场信号和收盘预测是两个不同问题：

- 入场信号：现在是否存在足够的短线优势。
- 收盘预测：当前 5 分钟周期结束时，相比开盘价更可能是 UP、DOWN，还是
  接近 50/50。

如果当前价格方向、成交压力、盘口方向和模型方向互相冲突，系统会降低置信度
或直接返回 `NO_TRADE`。收盘预测也会影响持仓的 `HOLD` 和 `CLOSE` 判断。

## 费用、滑点和收益计算

系统不使用未经调整的理论收益作为交易依据，而是考虑：

- Binance 现货手续费。
- 预测市场模拟手续费。
- 预计滑点。
- 买卖价差。
- 数据延迟导致的执行损耗。
- 仓位上限、最小下单金额和每日亏损限制。

主要参数位于 `.env.example`，例如：

```text
BTC_FEE_BPS=10
BTC_SLIPPAGE_BPS=5
BTC_PREDICTION_FEE_BPS=20
BTC_PREDICTION_SLIPPAGE_BPS=10
BTC_PREDICTION_DECISION_MIN_EV=0.01
BTC_PREDICTION_MAX_SPREAD_BPS=4
```

其中 `BPS` 是基点，`100 BPS = 1%`。实际使用时应根据账户费率、交易品种、
流动性和真实成交记录重新校准。

## 历史数据、训练和回测

在项目根目录执行：

```powershell
python -m btc5m.main backfill --limit 10000
python -m btc5m.main retrain
python -m btc5m.main backtest --limit 10000
```

可选的深度序列参考模型：

```powershell
python -m btc5m.main deep-train --limit 10000
```

历史数据库和模型文件保存在 `data/`，该目录已被 `.gitignore` 排除，不会上传
到 GitHub。

深度模型默认只作为参考，不会直接控制入场和退出。只有在按时间顺序划分的
测试数据上达到配置的准确率和 Brier score 门槛，并且明确设置：

```text
BTC_PREDICTION_DEEP_USE_FOR_DECISION=true
```

之后才允许它进入决策组合。深度学习模型不等于可靠预测器，必须先进行更长
时间的 walk-forward 测试、概率校准和扣除真实成本后的回测。

## 网格策略

网格模块用于现货研究和纸上规划：

```powershell
$env:BTC_GRID_ENABLED="true"
python -m btc5m.main serve
```

网格策略不是 UP/DOWN 收盘方向信号。它只会在市场适合震荡交易时显示网格计划，
并在以下情况自动暂停或不建议使用：

- 市场出现强趋势。
- 主动成交压力或盘口压力明显单边。
- 成交压力与盘口压力冲突。
- 买卖价差过宽或数据过期。
- 接近 5 分钟周期结束。

当前实现不会向 Binance 提交网格订单。

## Binance 账户连接

仪表盘提供 Binance Spot 账户连接表单。API Key 和 Secret 只保存在当前进程
内存中，不写入 SQLite，也不会由仪表盘接口返回。服务重启后需要重新输入。

建议：

- 优先使用 Binance Testnet。
- API Key 只开启读取和交易权限。
- 禁止提现权限。
- 尽可能限制允许访问的 IP。
- 不要把密钥写入 GitHub、README、Issue、聊天记录或源代码。

本地环境变量示例：

```powershell
$env:BINANCE_API_KEY="your_key"
$env:BINANCE_API_SECRET="your_secret"
$env:BTC_TESTNET="true"
$env:BTC_LIVE_TRADING="false"
python -m btc5m.main account
```

### 默认安全开关

```text
BTC_TESTNET=true
BTC_LIVE_TRADING=false
BTC_PREDICTION_MODE=paper
BTC_PREDICTION_AUTO_TRADING=false
BTC_GRID_ENABLED=false
BTC_PREDICTION_DEEP_USE_FOR_DECISION=false
```

不要在没有完成充分回测、Testnet 长时间运行和人工检查的情况下开启真实
交易。真实现货交易与真实 UP/DOWN 预测市场交易是两个不同的风险边界。

## 主要风险控制

- 单周期和单次交易金额上限。
- 同时活跃仓位限制。
- 最后若干秒禁止新入场。
- 最低概率优势和最低成本调整后 EV。
- 最大允许价差和数据过期检查。
- 每日最大交易次数和每日亏损上限。
- 连续亏损熔断，需要人工恢复。
- 概率明显反转、止盈、止损和临近结算时自动平仓判断。
- 自动交易默认关闭。
- 现货真实订单需要额外的环境开关和确认字符串。

这些是工程上的保护措施，不是盈利保证，也不能消除 API、网络、流动性、
模型失效和市场跳变风险。

## 测试

```powershell
python -m compileall -q btc5m tests
python -m unittest discover -s tests -v
```

测试覆盖特征生成、纸上执行、风险控制、深度模型审批、中性信号、市场压力
冲突、收盘预测冲突和网格暂停条件。

## 项目结构

```text
btc5m/
  engine.py             实时引擎和预测市场状态机
  market_analysis.py    成交压力、盘口和动量分析
  grid_strategy.py      纸上现货网格规划器
  deep_model.py         可选深度参考模型
  exchange.py           Binance REST 数据访问
  stream.py             Binance WebSocket 数据流
  trader.py             受保护的现货账户和纸上执行
  dashboard.py          本地 HTTP 仪表盘
  storage.py            SQLite 持久化
tests/                  单元测试和回归测试
RUNBOOK.md              运行和风险细节
REFERENCES.md           参考项目和产品边界
Start-BTC5M.cmd         Windows 一键启动脚本
```

## 许可证和安全

项目使用 MIT License，详见 [LICENSE](LICENSE)。

安全问题请先阅读 [SECURITY.md](SECURITY.md)，不要在公开 Issue 或 Pull
Request 中提交任何 API Key、Secret、Cookie、Token 或本地交易数据。
