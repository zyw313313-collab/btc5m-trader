import argparse
import json
import threading

from .config import Settings
from .dashboard import serve
from .engine import PredictionEngine


def main():
    parser = argparse.ArgumentParser(description="BTC 5-minute prediction system")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("once", help="sync once and emit one prediction")
    sub.add_parser("live", help="poll closed candles and predict continuously")
    backfill = sub.add_parser("backfill", help="download and store more historical candles")
    backfill.add_argument("--limit", type=int, default=10_000)
    sub.add_parser("retrain", help="rebuild the model from all stored candles")
    deep_train = sub.add_parser(
        "deep-train", help="train the optional deep sequence reference model"
    )
    deep_train.add_argument("--limit", type=int, default=10_000)
    sub.add_parser("account", help="check the connected Binance account")
    serve_parser = sub.add_parser("serve", help="run live poller and local dashboard")
    serve_parser.add_argument("--port", type=int, default=None)
    backtest = sub.add_parser("backtest", help="walk-forward backtest")
    backtest.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    settings = Settings()
    engine = PredictionEngine(settings)

    if args.command == "backtest":
        result = engine.backtest(args.limit)
        print(json.dumps(result.__dict__, indent=2))
    elif args.command == "backfill":
        downloaded = engine.backfill(args.limit)
        steps = engine.rebuild_model(engine.store.bars(10_000_000))
        print(json.dumps({"downloaded": downloaded, "training_steps": steps}, indent=2))
    elif args.command == "retrain":
        steps = engine.rebuild_model(engine.store.bars(10_000_000))
        print(json.dumps({"training_steps": steps}, indent=2))
    elif args.command == "deep-train":
        bars = engine.store.bars(args.limit)
        if len(bars) < 120:
            engine.backfill(args.limit)
            bars = engine.store.bars(args.limit)
        print(json.dumps(engine.train_deep_model(bars), indent=2))
    elif args.command == "account":
        print(json.dumps(engine.trader.account_snapshot(), indent=2))
    elif args.command == "once":
        print(json.dumps(engine.run_once(), indent=2))
    elif args.command == "live":
        engine.live()
    else:
        threading.Thread(target=engine.live, daemon=True).start()
        serve(engine, args.port or settings.port)


if __name__ == "__main__":
    main()
