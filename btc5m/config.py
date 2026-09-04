from dataclasses import dataclass
import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    symbol: str = os.getenv("BTC_SYMBOL", "BTCUSDT").upper()
    interval: str = os.getenv("BTC_INTERVAL", "5m")
    base_url: str = os.getenv("BTC_BASE_URL", "https://api.binance.com").rstrip("/")
    ws_url: str = os.getenv(
        "BTC_WS_URL", "wss://stream.binance.com:9443/ws"
    ).rstrip("/")
    testnet: bool = env_bool("BTC_TESTNET", True)
    account_base_url: str = os.getenv(
        "BTC_ACCOUNT_BASE_URL",
        "https://testnet.binance.vision" if testnet else "https://api.binance.com",
    ).rstrip("/")
    use_ccxt: bool = env_bool("BTC_USE_CCXT", False)
    api_key: str = os.getenv("BINANCE_API_KEY", "")
    api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    db_path: str = os.getenv("BTC_DB_PATH", "data/btc5m.sqlite3")
    poll_seconds: int = int(os.getenv("BTC_POLL_SECONDS", "20"))
    websocket_enabled: bool = env_bool("BTC_WEBSOCKET", True)
    websocket_reconnect_seconds: int = int(
        os.getenv("BTC_WS_RECONNECT_SECONDS", "5")
    )
    port: int = int(os.getenv("BTC_PORT", "8787"))
    history_limit: int = int(os.getenv("BTC_HISTORY_LIMIT", "1000"))
    sync_limit: int = int(os.getenv("BTC_SYNC_LIMIT", "300"))
    fee_bps: float = float(os.getenv("BTC_FEE_BPS", "10"))
    slippage_bps: float = float(os.getenv("BTC_SLIPPAGE_BPS", "5"))
    trade_threshold: float = float(os.getenv("BTC_TRADE_THRESHOLD", "0.56"))
    max_quote_per_trade: float = float(os.getenv("BTC_MAX_QUOTE_PER_TRADE", "50"))
    max_position_quote: float = float(os.getenv("BTC_MAX_POSITION_QUOTE", "100"))
    min_quote_per_trade: float = float(os.getenv("BTC_MIN_QUOTE_PER_TRADE", "5"))
    paper_quote_balance: float = float(os.getenv("BTC_PAPER_QUOTE_BALANCE", "1000"))
    live_trading: bool = env_bool("BTC_LIVE_TRADING", False)
    live_confirmation: str = os.getenv("BTC_LIVE_CONFIRMATION", "")
    prediction_mode: str = os.getenv("BTC_PREDICTION_MODE", "paper").lower()
    prediction_auto_trading: bool = env_bool("BTC_PREDICTION_AUTO_TRADING", False)
    prediction_fee_bps: float = float(os.getenv("BTC_PREDICTION_FEE_BPS", "20"))
    prediction_slippage_bps: float = float(
        os.getenv("BTC_PREDICTION_SLIPPAGE_BPS", "10")
    )
    prediction_market_margin: float = float(
        os.getenv("BTC_PREDICTION_MARKET_MARGIN", "0.04")
    )
    prediction_min_probability: float = float(
        os.getenv("BTC_PREDICTION_MIN_PROBABILITY", "0.60")
    )
    prediction_min_odds: float = float(os.getenv("BTC_PREDICTION_MIN_ODDS", "1.50"))
    prediction_max_stake: float = float(
        os.getenv("BTC_PREDICTION_MAX_STAKE", "50")
    )
    prediction_min_stake: float = float(
        os.getenv("BTC_PREDICTION_MIN_STAKE", "5")
    )
    prediction_max_daily_trades: int = int(
        os.getenv("BTC_PREDICTION_MAX_DAILY_TRADES", "15")
    )
    prediction_daily_loss_limit: float = float(
        os.getenv("BTC_PREDICTION_DAILY_LOSS_LIMIT", "100")
    )
    prediction_max_loss_streak: int = int(
        os.getenv("BTC_PREDICTION_MAX_LOSS_STREAK", "3")
    )
    prediction_no_trade_last_seconds: int = int(
        os.getenv("BTC_PREDICTION_NO_TRADE_LAST_SECONDS", "10")
    )
    prediction_observation_seconds: int = int(
        os.getenv("BTC_PREDICTION_OBSERVATION_SECONDS", "30")
    )
    prediction_entry_probability: float = float(
        os.getenv("BTC_PREDICTION_ENTRY_PROBABILITY", "0.64")
    )
    prediction_decision_min_ev: float = float(
        os.getenv("BTC_PREDICTION_DECISION_MIN_EV", "0.01")
    )
    prediction_max_spread_bps: float = float(
        os.getenv("BTC_PREDICTION_MAX_SPREAD_BPS", "4")
    )
    prediction_min_realtime_trades: int = int(
        os.getenv("BTC_PREDICTION_MIN_REALTIME_TRADES", "5")
    )
    prediction_realtime_stale_ms: int = int(
        os.getenv("BTC_PREDICTION_REALTIME_STALE_MS", "3000")
    )
    prediction_signal_min_imbalance: float = float(
        os.getenv("BTC_PREDICTION_SIGNAL_MIN_IMBALANCE", "0.08")
    )
    prediction_signal_min_momentum: float = float(
        os.getenv("BTC_PREDICTION_SIGNAL_MIN_MOMENTUM", "0.00015")
    )
    prediction_take_profit_pct: float = float(
        os.getenv("BTC_PREDICTION_TAKE_PROFIT_PCT", "0.50")
    )
    prediction_stop_loss_pct: float = float(
        os.getenv("BTC_PREDICTION_STOP_LOSS_PCT", "0.30")
    )
    prediction_close_last_seconds: int = int(
        os.getenv("BTC_PREDICTION_CLOSE_LAST_SECONDS", "30")
    )
    deep_model_path: str = os.getenv("BTC_DEEP_MODEL_PATH", "")
    prediction_deep_enabled: bool = env_bool("BTC_PREDICTION_DEEP_ENABLED", True)
    prediction_deep_use_for_decision: bool = env_bool(
        "BTC_PREDICTION_DEEP_USE_FOR_DECISION", False
    )
    prediction_deep_sequence_length: int = int(
        os.getenv("BTC_PREDICTION_DEEP_SEQUENCE_LENGTH", "12")
    )
    prediction_deep_epochs: int = int(os.getenv("BTC_PREDICTION_DEEP_EPOCHS", "6"))
    prediction_deep_learning_rate: float = float(
        os.getenv("BTC_PREDICTION_DEEP_LEARNING_RATE", "0.003")
    )
    prediction_deep_min_train_samples: int = int(
        os.getenv("BTC_PREDICTION_DEEP_MIN_TRAIN_SAMPLES", "120")
    )
    prediction_deep_min_test_accuracy: float = float(
        os.getenv("BTC_PREDICTION_DEEP_MIN_TEST_ACCURACY", "0.55")
    )
    prediction_deep_max_test_brier: float = float(
        os.getenv("BTC_PREDICTION_DEEP_MAX_TEST_BRIER", "0.245")
    )
    prediction_neutral_lower: float = float(
        os.getenv("BTC_PREDICTION_NEUTRAL_LOWER", "0.46")
    )
    prediction_neutral_upper: float = float(
        os.getenv("BTC_PREDICTION_NEUTRAL_UPPER", "0.54")
    )
    prediction_min_pressure_score: float = float(
        os.getenv("BTC_PREDICTION_MIN_PRESSURE_SCORE", "0.12")
    )
    prediction_pressure_conflict_block: bool = env_bool(
        "BTC_PREDICTION_PRESSURE_CONFLICT_BLOCK", True
    )
    prediction_prior_window: int = int(
        os.getenv("BTC_PREDICTION_PRIOR_WINDOW", "96")
    )
    grid_enabled: bool = env_bool("BTC_GRID_ENABLED", False)
    grid_levels: int = int(os.getenv("BTC_GRID_LEVELS", "5"))
    grid_spacing_pct: float = float(os.getenv("BTC_GRID_SPACING_PCT", "0.002"))
    grid_min_spacing_pct: float = float(
        os.getenv("BTC_GRID_MIN_SPACING_PCT", "0.0015")
    )
    grid_max_spacing_pct: float = float(
        os.getenv("BTC_GRID_MAX_SPACING_PCT", "0.02")
    )
    grid_range_window: int = int(os.getenv("BTC_GRID_RANGE_WINDOW", "36"))
    grid_range_fraction: float = float(
        os.getenv("BTC_GRID_RANGE_FRACTION", "0.35")
    )
    grid_trend_return_filter: float = float(
        os.getenv("BTC_GRID_TREND_RETURN_FILTER", "0.004")
    )
    grid_no_trade_last_seconds: int = int(
        os.getenv("BTC_GRID_NO_TRADE_LAST_SECONDS", "30")
    )
    grid_max_quote: float = float(os.getenv("BTC_GRID_MAX_QUOTE", "100"))
