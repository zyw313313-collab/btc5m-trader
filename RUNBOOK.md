# BTC 5m system runbook

The project lives at `D:\btc5m-trader`.

## Install

```powershell
cd D:\btc5m-trader
python -m pip install -r requirements.txt
python -m pip install -r requirements-ccxt.txt
```

CCXT is optional. The native Binance REST client remains the default.

## Prepare data

```powershell
python -m btc5m.main backfill --limit 10000
python -m btc5m.main retrain
python -m btc5m.main backtest --limit 10000
```

The backtest must be positive after fees and slippage before considering live
orders. The current model is not at that threshold.

## Deep reference model

Train the optional sequence MLP after backfilling:

```powershell
python -m btc5m.main deep-train --limit 10000
```

The model is reference-only by default. It is allowed into the decision
ensemble only when calibration is complete, enough time-ordered train/test
samples are present, test accuracy is at least
`BTC_PREDICTION_DEEP_MIN_TEST_ACCURACY` (default `0.55`), test Brier score is
at most `BTC_PREDICTION_DEEP_MAX_TEST_BRIER` (default `0.245`), and
`BTC_PREDICTION_DEEP_USE_FOR_DECISION=true`.

The local training run on September 4, 2026 used 9,973 samples and produced
test accuracy `49.7%`, so the model remains unapproved and does not control
entries or exits.

## Paper real-time mode

```powershell
$env:BTC_TESTNET="true"
$env:BTC_LIVE_TRADING="false"
$env:BTC_WEBSOCKET="true"
python -m btc5m.main serve
```

Open `http://127.0.0.1:8787`. The service consumes closed Binance kline events,
reconnects the WebSocket, and uses REST polling only if the WebSocket client is
unavailable.

The dashboard includes a live candlestick chart, prediction history, order
history, paper equity, drawdown, and a separate five-minute UP/DOWN paper
prediction market. The prediction market has round timing, lock price,
synthetic odds, paper positions, early close, settlement, and risk controls.
The current round also exposes fee/slippage-adjusted EV, effective odds, and
fractional Kelly sizing. The active-position view only shows positions that are
still open.
The account form connects to Binance Spot without writing credentials to disk.
Credentials are held only in process memory and must be entered again after
restart.

## Real-time five-minute decision rules

The dashboard's `实时出手决策` panel is recalculated from the live combined
WebSocket stream. It uses the candle model as a baseline and overlays recent
aggressive trade imbalance, best-bid/best-ask size imbalance, short momentum,
spread, data freshness, fees, and configured slippage.

The default decision state machine is:

- `WAIT` / 观察: the first 30 seconds of every round. No new position is opened.
- `NO_TRADE` / 禁止交易: stale or insufficient data, spread above 4 bps,
  probability edge below 64%, fewer than two agreeing signals, negative
  expected value after cost, or the final 30 seconds.
- `ENTER_UP` or `ENTER_DOWN` / 出手: only when live data is fresh, the
  direction probability is at least 64%, at least two of model/order-flow/
  book/momentum agree, and cost-adjusted EV is at least 1%.
- `HOLD` / 继续持有: an active position remains aligned with the current
  real-time probability and has not reached a risk exit.
- `CLOSE` / 平仓: the probability has clearly reversed, take-profit or
  stop-loss is reached, or the position is profitable near settlement.

These are conservative execution gates, not a guarantee of the next candle's
direction. The displayed confidence is a signal-strength score and is not a
statistically calibrated probability until a much larger walk-forward sample
has been collected.

The entry signal and the close forecast are intentionally different:

- Entry probability answers: "Is there enough short-lived edge to enter now?"
- Close forecast answers: "Is this five-minute round more likely to settle UP,
  DOWN, or remain too close to call?"
- Entry is rejected when the market-flow direction disagrees with the model,
  when aggressive trades and top-of-book pressure conflict, or when the
  selected entry direction conflicts with a clear opposite close forecast.
- A high UP entry probability must therefore not be interpreted as a
  permanent UP bias. If the current price is below the round open, the close
  forecast receives a DOWN penalty; if the market pressure does not confirm
  the entry, the action is `NO_TRADE`.

Market-pressure inputs:

- `trade_imbalance_15s` and `trade_imbalance_60s`: aggressive buyer versus
  seller quote-volume imbalance.
- `book_imbalance`: best-bid versus best-ask quantity imbalance.
- `momentum_15s`: very short price movement.
- `divergence`: pressure/price agreement or exhaustion warning.

Spot grid:

- The displayed grid is a paper plan only and never submits exchange orders.
- It is enabled only when `BTC_GRID_ENABLED=true`, enough historical bars are
  available, the recent range is not in a strong trend, the spread and data
  age pass the real-time gates, and trade/book pressure is not conflicting.
- It is paused near the end of a five-minute round and whenever the market
  becomes strongly directional. Grid levels are not a prediction-market
  UP/DOWN signal.

Prediction-market controls:

- `BTC_PREDICTION_MODE=paper` is required; live prediction execution is not enabled.
- Automatic trading is off by default and can be enabled from the dashboard.
- Paper fees, slippage, minimum odds, probability threshold, stake cap, daily
  loss cap, loss-streak circuit breaker, last-seconds entry block, take-profit,
  stop-loss, and automatic probability-reversal close are applied.
- Automatic trading opens at most one paper position per five-minute round.
  That guard is persisted through the position history, so a closed position
  is not reopened by dashboard refreshes or service restarts.
- The displayed odds and pools are marked paper-market estimates, not Binance
  prediction-market quotes.

## Account connection

Set credentials only in the local process environment. Never put them in chat,
source files, SQLite, or dashboard responses.

```powershell
$env:BINANCE_API_KEY="..."
$env:BINANCE_API_SECRET="..."
$env:BTC_TESTNET="true"
$env:BTC_LIVE_TRADING="false"
python -m btc5m.main account
```

Use a Binance key with read and trade permission only, and disable withdrawals.

## Live order gate

Real orders require all of the following:

```powershell
$env:BTC_TESTNET="false"
$env:BTC_ACCOUNT_BASE_URL="https://api.binance.com"
$env:BTC_LIVE_TRADING="true"
$env:BTC_LIVE_CONFIRMATION="I_UNDERSTAND_REAL_ORDERS"
```

The system is spot-only, uses BUY/SELL, applies position and per-trade caps,
and records order and equity history locally. Do not enable this gate until a
longer walk-forward test and extended Testnet run have passed.

## One-click launch

Double-click:

```text
C:\Users\振宇\Desktop\BTC 5m 预测系统.lnk
```

The backup launcher is:

```text
D:\btc5m-trader\Start-BTC5M.cmd
```
