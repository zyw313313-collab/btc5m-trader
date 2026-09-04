# BTC 5m Trader

[中文说明](README.zh-CN.md) | English

Binance BTCUSDT 5-minute research, real-time monitoring, paper prediction
market, and protected spot-trading project.

This repository is for research and paper trading. It does not guarantee
profitability. Short-horizon crypto direction is noisy, and the displayed
probabilities are not automatically calibrated trading odds.

## What It Does

- Streams Binance BTCUSDT trades, book ticker data, 1-second candles, and
  closed 5-minute candles.
- Falls back to Binance REST polling when the WebSocket is unavailable.
- Stores historical 5-minute candles locally in SQLite.
- Uses an online logistic model with price, volume, RSI, EMA, ATR, volatility,
  and time features.
- Provides an optional dependency-free deep sequence reference model.
- Calculates a separate five-minute close forecast.
- Analyzes aggressive buyer/seller flow, top-of-book imbalance, and short
  momentum.
- Includes fees, slippage, spread, stale-data, expected-value, and risk gates.
- Provides a paper UP/DOWN prediction-market layer with round timing, odds,
  positions, early close, settlement, and risk controls.
- Shows a spot-grid paper plan that is paused during strong trends, conflicting
  pressure, wide spreads, stale data, and the end of a round.
- Provides a local dashboard with a live candlestick chart, signals, pressure,
  close forecast, grid levels, account status, paper positions, and history.
- Can connect to a Binance Spot account in process memory. Credentials are not
  stored in SQLite or returned by the dashboard.

## Important Product Boundary

Binance Spot and a Binance prediction market are different products.

- Spot API operations use BTCUSDT `BUY` and `SELL`.
- The UP/DOWN market in this project is currently a transparent paper
  simulation. It is not a live Binance prediction-market order adapter.
- `BTC_LIVE_TRADING=true` only concerns protected Spot execution. It does not
  enable live UP/DOWN prediction-market orders.

## Quick Start on Windows

Requirements:

- Windows PowerShell
- Python 3.11 or newer
- Network access to Binance public market data

Install:

```powershell
cd D:\btc5m-trader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the dashboard:

```powershell
python -m btc5m.main serve
```

Open `http://127.0.0.1:8787`.

There is also a Windows launcher:

```text
D:\btc5m-trader\Start-BTC5M.cmd
```

Double-clicking the desktop shortcut created for this project starts the same
local service and opens the dashboard.

## Prepare Historical Data

Run these commands from the repository root:

```powershell
python -m btc5m.main backfill --limit 10000
python -m btc5m.main retrain
python -m btc5m.main backtest --limit 10000
```

The database and model files are written under `data/`. That directory is
intentionally excluded from Git because it contains local runtime state and
trained artifacts.

Optional deep reference training:

```powershell
python -m btc5m.main deep-train --limit 10000
```

The deep model remains reference-only unless its time-ordered test metrics pass
the configured thresholds and `BTC_PREDICTION_DEEP_USE_FOR_DECISION=true`.
Keep it disabled for decisions until a longer walk-forward evaluation supports
that change.

## Signal Interpretation

The dashboard separates entry timing from the expected round close:

- `WAIT`: observe the initial part of a new round.
- `NO_TRADE`: data, spread, probability, pressure, cost, timing, or risk gates
  failed.
- `ENTER_UP` / `ENTER_DOWN`: a candidate entry passed all configured gates.
- `HOLD`: an existing paper position is not clearly invalidated.
- `CLOSE`: the close forecast reversed or a position risk rule triggered.

The system does not treat a high UP probability as an unconditional buy signal.
An entry requires fresh data, sufficient probability edge, positive
fee/slippage-adjusted expected value, market-flow confirmation, and no
trade/book pressure conflict. A clear conflict between entry direction and
close forecast also blocks the entry.

Pressure fields include:

- `trade_imbalance_15s` and `trade_imbalance_60s`: aggressive buyer/seller
  quote-volume imbalance.
- `book_imbalance`: best-bid versus best-ask quantity imbalance.
- `momentum_15s`: very short price movement.
- `divergence`: confirmed pressure or possible exhaustion.

These are explanatory market features, not guaranteed predictors.

## Grid Strategy

The grid module produces a spot-grid plan for paper inspection. It never
submits exchange orders.

Enable the displayed plan locally:

```powershell
$env:BTC_GRID_ENABLED="true"
python -m btc5m.main serve
```

The plan is enabled only when enough bars exist and the market is suitable for
range trading. It pauses for strong recent trends, strong directional pressure,
conflicting trade/book pressure, wide spreads, stale data, and the last part of
the five-minute round.

## Binance Account Connection

The dashboard can connect to Binance Spot using the account form. Credentials
are held in process memory and cleared from the form after submission.

For a local environment-based connection:

```powershell
$env:BINANCE_API_KEY="your_key"
$env:BINANCE_API_SECRET="your_secret"
$env:BTC_TESTNET="true"
$env:BTC_LIVE_TRADING="false"
python -m btc5m.main account
```

Use a key with only the permissions required for testing. Disable withdrawals
and restrict the key by IP. Never put real values in `.env.example`, README,
source files, issues, or pull requests.

To create local configuration, copy `.env.example` to `.env` and load it with
your preferred environment-variable workflow. `.env` is ignored by Git.

## Configuration

Important safety defaults:

```text
BTC_TESTNET=true
BTC_LIVE_TRADING=false
BTC_PREDICTION_MODE=paper
BTC_PREDICTION_AUTO_TRADING=false
BTC_GRID_ENABLED=false
BTC_PREDICTION_DEEP_USE_FOR_DECISION=false
```

The complete safe template is in `.env.example`. Additional operational
details and risk controls are documented in [RUNBOOK.md](RUNBOOK.md).

## Tests

```powershell
python -m compileall -q btc5m tests
python -m unittest discover -s tests -v
```

The tests cover feature generation, paper execution, risk controls, deep-model
approval, neutral/no-trade behavior, market-pressure conflicts, close-forecast
conflicts, and grid pause conditions.

## Project Layout

```text
btc5m/
  engine.py             realtime engine and prediction-market state machine
  market_analysis.py    trade-flow, order-book, and momentum analysis
  grid_strategy.py      paper spot-grid planner
  deep_model.py         optional deep reference model
  exchange.py           Binance public REST data access
  stream.py             Binance WebSocket streams
  trader.py             protected Spot account and paper execution
  dashboard.py          local HTTP dashboard
  storage.py            SQLite persistence
tests/                  unit and regression tests
RUNBOOK.md              operations and risk details
REFERENCES.md           project references and product boundaries
Start-BTC5M.cmd         Windows one-click launcher
```

## References and License

See [REFERENCES.md](REFERENCES.md) for the projects and ideas used as
references. Reference projects are not copied wholesale and their claimed
performance should not be treated as evidence of profitability.

This project is released under the [MIT License](LICENSE). See
[SECURITY.md](SECURITY.md) for credential-handling guidance.
