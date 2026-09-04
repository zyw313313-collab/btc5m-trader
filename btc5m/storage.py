import json
import os
import sqlite3
from contextlib import contextmanager


class Store:
    def __init__(self, path: str, initial_quote: float = 1000.0):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.path = path
        self.initial_quote = initial_quote
        self._init()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS bars (
                    open_time INTEGER PRIMARY KEY,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    close_time INTEGER NOT NULL,
                    quote_volume REAL NOT NULL,
                    trades INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_open_time INTEGER NOT NULL,
                    target_open_time INTEGER NOT NULL,
                    p_up REAL NOT NULL,
                    predicted_at INTEGER NOT NULL,
                    actual INTEGER,
                    actual_return REAL,
                    settled_at INTEGER,
                    UNIQUE(source_open_time, target_open_time)
                );
                CREATE INDEX IF NOT EXISTS idx_predictions_target
                    ON predictions(target_open_time);
                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    quote REAL NOT NULL,
                    base REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    p_up REAL NOT NULL,
                    price REAL NOT NULL,
                    quote_amount REAL,
                    quantity REAL,
                    status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    raw_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_orders_created_at
                    ON orders(created_at DESC);
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    quote REAL NOT NULL,
                    base REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    equity REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_equity_recorded_at
                    ON equity_snapshots(recorded_at DESC);
                CREATE TABLE IF NOT EXISTS prediction_rounds (
                    round_id TEXT PRIMARY KEY,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    lock_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    close_price REAL,
                    status TEXT NOT NULL,
                    p_up REAL NOT NULL,
                    confidence REAL NOT NULL,
                    up_odds REAL NOT NULL,
                    down_odds REAL NOT NULL,
                    up_pool REAL NOT NULL,
                    down_pool REAL NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prediction_rounds_start
                    ON prediction_rounds(start_time DESC);
                CREATE TABLE IF NOT EXISTS prediction_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    stake REAL NOT NULL,
                    entry_odds REAL NOT NULL,
                    opened_at INTEGER NOT NULL,
                    closed_at INTEGER,
                    exit_odds REAL,
                    status TEXT NOT NULL,
                    pnl REAL,
                    fee REAL NOT NULL DEFAULT 0,
                    raw_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_prediction_positions_status
                    ON prediction_positions(status, opened_at DESC);
                CREATE TABLE IF NOT EXISTS prediction_account (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    quote REAL NOT NULL,
                    realized_pnl REAL NOT NULL
                );
                """
            )
            db.execute(
                """
                INSERT OR IGNORE INTO paper_account (id, quote, base)
                VALUES (1, ?, 0.0)
                """,
                (self.initial_quote,),
            )
            db.execute(
                """
                INSERT OR IGNORE INTO prediction_account (id, quote, realized_pnl)
                VALUES (1, ?, 0.0)
                """,
                (self.initial_quote,),
            )

    def upsert_bars(self, rows: list[dict]):
        with self.connect() as db:
            db.executemany(
                """
                INSERT INTO bars (
                    open_time, open, high, low, close, volume, close_time,
                    quote_volume, trades
                ) VALUES (
                    :open_time, :open, :high, :low, :close, :volume, :close_time,
                    :quote_volume, :trades
                )
                ON CONFLICT(open_time) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    close_time=excluded.close_time,
                    quote_volume=excluded.quote_volume, trades=excluded.trades
                """,
                rows,
            )

    def bars(self, limit: int = 1000) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM bars ORDER BY open_time DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_prediction(self, source_open_time: int, target_open_time: int, p_up: float, predicted_at: int):
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO predictions
                    (source_open_time, target_open_time, p_up, predicted_at)
                VALUES (?, ?, ?, ?)
                """,
                (source_open_time, target_open_time, p_up, predicted_at),
            )
        return cursor.rowcount == 1

    def unsettled_predictions(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM predictions WHERE actual IS NULL ORDER BY target_open_time"
            ).fetchall()
        return [dict(row) for row in rows]

    def settle_prediction(self, prediction_id: int, actual: int, actual_return: float, settled_at: int):
        with self.connect() as db:
            db.execute(
                """
                UPDATE predictions
                SET actual=?, actual_return=?, settled_at=?
                WHERE id=? AND actual IS NULL
                """,
                (actual, actual_return, settled_at, prediction_id),
            )

    def predictions(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM predictions ORDER BY predicted_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_prediction(self) -> dict | None:
        rows = self.predictions(1)
        return rows[0] if rows else None

    def metrics(self) -> dict:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN actual IS NOT NULL THEN 1 ELSE 0 END) AS settled,
                       SUM(CASE WHEN actual IS NOT NULL AND
                                      ((p_up >= 0.5 AND actual=1) OR
                                       (p_up < 0.5 AND actual=0))
                                THEN 1 ELSE 0 END) AS correct,
                       AVG(CASE WHEN actual IS NOT NULL THEN actual_return END) AS avg_return
                FROM predictions
                """
            ).fetchone()
        total = int(row["total"] or 0)
        settled = int(row["settled"] or 0)
        correct = int(row["correct"] or 0)
        return {
            "total": total,
            "settled": settled,
            "accuracy": correct / settled if settled else None,
            "avg_return": row["avg_return"],
        }

    def save_model(self, state: dict):
        path = f"{self.path}.model.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)

    def load_model(self) -> dict | None:
        path = f"{self.path}.model.json"
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def paper_account(self) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT quote, base FROM paper_account WHERE id=1"
            ).fetchone()
        return {"quote": float(row["quote"]), "base": float(row["base"])}

    def save_paper_account(self, quote: float, base: float):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO paper_account (id, quote, base) VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET quote=excluded.quote, base=excluded.base
                """,
                (quote, base),
            )

    def record_order(self, order: dict):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO orders (
                    created_at, mode, symbol, side, decision, p_up, price,
                    quote_amount, quantity, status, exchange_order_id, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order["created_at"],
                    order["mode"],
                    order["symbol"],
                    order["side"],
                    order["decision"],
                    order["p_up"],
                    order["price"],
                    order.get("quote_amount"),
                    order.get("quantity"),
                    order["status"],
                    order.get("exchange_order_id"),
                    json.dumps(order.get("raw"), ensure_ascii=True),
                ),
            )

    def orders(self, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def record_equity(self, mode: str, quote: float, base: float, mark_price: float):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO equity_snapshots
                    (recorded_at, mode, quote, base, mark_price, equity)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(__import__("time").time() * 1000),
                    mode,
                    quote,
                    base,
                    mark_price,
                    quote + base * mark_price,
                ),
            )

    def equity_snapshots(self, limit: int = 200) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM equity_snapshots ORDER BY recorded_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def risk_metrics(self) -> dict:
        snapshots = self.equity_snapshots(10_000)
        if not snapshots:
            return {"equity": None, "peak_equity": None, "drawdown": None, "max_drawdown": None}
        values = [float(row["equity"]) for row in snapshots]
        peak = values[0]
        max_drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            max_drawdown = max(max_drawdown, (peak - value) / peak if peak else 0.0)
        return {
            "equity": values[-1],
            "peak_equity": max(values),
            "drawdown": (max(values) - values[-1]) / max(values) if max(values) else 0.0,
            "max_drawdown": max_drawdown,
        }

    def upsert_prediction_round(self, round_data: dict):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO prediction_rounds (
                    round_id, start_time, end_time, lock_price, current_price,
                    close_price, status, p_up, confidence, up_odds, down_odds,
                    up_pool, down_pool, updated_at
                ) VALUES (
                    :round_id, :start_time, :end_time, :lock_price, :current_price,
                    :close_price, :status, :p_up, :confidence, :up_odds, :down_odds,
                    :up_pool, :down_pool, :updated_at
                )
                ON CONFLICT(round_id) DO UPDATE SET
                    current_price=excluded.current_price,
                    close_price=COALESCE(excluded.close_price, prediction_rounds.close_price),
                    status=excluded.status, p_up=excluded.p_up,
                    confidence=excluded.confidence, up_odds=excluded.up_odds,
                    down_odds=excluded.down_odds, up_pool=excluded.up_pool,
                    down_pool=excluded.down_pool, updated_at=excluded.updated_at
                """,
                round_data,
            )

    def prediction_rounds(self, limit: int = 20) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM prediction_rounds ORDER BY start_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_prediction_round(self) -> dict | None:
        rows = self.prediction_rounds(1)
        return rows[0] if rows else None

    def prediction_account(self) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT quote, realized_pnl FROM prediction_account WHERE id=1"
            ).fetchone()
        return {"quote": float(row["quote"]), "realized_pnl": float(row["realized_pnl"])}

    def save_prediction_account(self, quote: float, realized_pnl: float):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO prediction_account (id, quote, realized_pnl)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    quote=excluded.quote, realized_pnl=excluded.realized_pnl
                """,
                (quote, realized_pnl),
            )

    def add_prediction_position(self, position: dict) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO prediction_positions (
                    round_id, direction, stake, entry_odds, opened_at, status,
                    fee, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position["round_id"],
                    position["direction"],
                    position["stake"],
                    position["entry_odds"],
                    position["opened_at"],
                    position.get("status", "active"),
                    position.get("fee", 0.0),
                    json.dumps(position.get("raw"), ensure_ascii=True),
                ),
            )
            return int(cursor.lastrowid)

    def prediction_positions(self, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM prediction_positions
                ORDER BY opened_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_prediction_positions(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM prediction_positions
                WHERE status='active' ORDER BY opened_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def prediction_positions_for_round(self, round_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM prediction_positions
                WHERE round_id=?
                ORDER BY opened_at
                """,
                (round_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def close_prediction_position(
        self,
        position_id: int,
        status: str,
        closed_at: int,
        exit_odds: float,
        pnl: float,
        fee: float,
    ):
        with self.connect() as db:
            db.execute(
                """
                UPDATE prediction_positions
                SET status=?, closed_at=?, exit_odds=?, pnl=?, fee=?
                WHERE id=? AND status='active'
                """,
                (status, closed_at, exit_odds, pnl, fee, position_id),
            )

    def prediction_daily_stats(self, day_start_ms: int) -> dict:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT COUNT(*) AS trades,
                       COALESCE(SUM(CASE WHEN pnl < 0 THEN -pnl ELSE 0 END), 0) AS loss,
                       COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) AS losses
                FROM prediction_positions
                WHERE opened_at >= ?
                """,
                (day_start_ms,),
            ).fetchone()
            streak_rows = db.execute(
                """
                SELECT pnl FROM prediction_positions
                WHERE status IN ('settled', 'closed') AND pnl IS NOT NULL
                ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT 100
                """
            ).fetchall()
        streak = 0
        for item in streak_rows:
            if float(item["pnl"]) < 0:
                streak += 1
            else:
                break
        return {
            "trades": int(row["trades"] or 0),
            "loss": float(row["loss"] or 0.0),
            "loss_streak": streak,
        }
