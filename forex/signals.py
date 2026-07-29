"""Daily signal runner -- the thing that goes on the server.

Reads a config, pulls prices, and prints the positions the strategy wants to
hold tonight, plus the orders needed to get there from what you hold now.

It does NOT connect to a broker and does NOT place orders. That is
deliberate: run it in this mode for at least a couple of months and compare
its output against what you would have done, before letting anything of the
sort touch real money.

    python3 signals.py --config config.json
    python3 signals.py --config config.json --json    # for piping onward

Cron, once a day, after the New York close:

    30 22 * * 1-5 cd /opt/fxlab && /usr/bin/python3 signals.py --config config.json >> log/signals.log 2>&1

THE IMPORTANT DESIGN POINT: the target position is computed by the same
`engine.run` that the backtest uses, reading the last row of its `target`
column. There is no separate "live" signal path. A second implementation
would drift from the tested one, and you would end up trading a strategy you
never validated -- which is the classic way a backtested system loses money
in production.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fxlab import data, strategies
from fxlab.engine import Config, run

STALE_AFTER_DAYS = 5


def build_signal_fn(name: str, params: dict, max_hold: int):
    """Identical construction to run_backtest.py, on purpose."""
    fn = strategies.REGISTRY[name]
    if params:
        fn = partial(fn, **params)
        fn.__name__ = name
    if max_hold > 0:
        fn = strategies.with_max_hold(fn, max_hold)
    return fn


def target_for(prices: pd.Series, signal_fn, cfg: Config) -> dict:
    """The position this rule wants, as of the last bar we have."""
    bt = run(prices, signal_fn(prices), cfg)
    last = bt.iloc[-1]
    asof = bt.index[-1]
    age = (pd.Timestamp.now(tz=None).normalize() - asof.normalize()).days
    return {
        "asof": asof.date().isoformat(),
        "price": float(last["price"]),
        "target": float(last["target"]),
        "stale_days": int(age),
    }


def main():
    p = argparse.ArgumentParser(description="Emit today's target FX positions")
    p.add_argument("--config", required=True, help="path to config JSON")
    p.add_argument("--state", default="state.json", help="where the last run's positions live")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    p.add_argument("--no-write", action="store_true", help="don't update the state file")
    args = p.parse_args()

    cfg_raw = json.loads(Path(args.config).read_text())
    equity = float(cfg_raw["account_equity"])
    cfg = Config(
        vol_target=float(cfg_raw.get("vol_target", 0.10)),
        cost_bps=float(cfg_raw.get("cost_bps", 1.0)),
        max_leverage=float(cfg_raw.get("max_leverage", 1.0)),
        rebalance_band=float(cfg_raw.get("rebalance_band", 0.0)),
    )
    signal_fn = build_signal_fn(
        cfg_raw["strategy"], cfg_raw.get("params", {}), int(cfg_raw.get("max_hold", 0))
    )

    state_path = Path(args.state)
    held = json.loads(state_path.read_text()).get("positions", {}) if state_path.exists() else {}

    rows, warnings = {}, []
    for pair, spec in cfg_raw["pairs"].items():
        try:
            prices = data.load(spec)
        except Exception as exc:  # noqa: BLE001 -- one dead feed must not stop the rest
            warnings.append(f"{pair}: could not load prices ({exc})")
            continue

        info = target_for(prices, signal_fn, cfg)
        if info["stale_days"] > STALE_AFTER_DAYS:
            warnings.append(
                f"{pair}: data is {info['stale_days']} days old (last bar {info['asof']}) "
                "-- treat this signal as unreliable"
            )

        current = float(held.get(pair, 0.0))
        info["current"] = current
        info["delta"] = info["target"] - current
        info["notional_eur"] = round(info["target"] * equity, 2)
        info["trade_eur"] = round(info["delta"] * equity, 2)
        rows[pair] = info

    if not rows:
        print("No pairs could be priced. Nothing to do.", file=sys.stderr)
        for w in warnings:
            print(f"  ! {w}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "strategy": cfg_raw["strategy"],
        "params": cfg_raw.get("params", {}),
        "max_hold": cfg_raw.get("max_hold", 0),
        "account_equity": equity,
        "positions": {k: v["target"] for k, v in rows.items()},
        "detail": rows,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        table = pd.DataFrame(rows).T[
            ["asof", "price", "current", "target", "delta", "trade_eur", "notional_eur"]
        ]
        print(f"\n{cfg_raw['strategy']}{cfg_raw.get('params', {})} "
              f"max_hold={cfg_raw.get('max_hold', 0)}  equity={equity:,.0f}")
        print(table.to_string())

        trades = {k: v for k, v in rows.items() if abs(v["delta"]) > 1e-9}
        if trades:
            print("\nOrders to place:")
            for pair, v in trades.items():
                side = "BUY " if v["delta"] > 0 else "SELL"
                print(f"  {side} {pair}  {abs(v['trade_eur']):>12,.2f} EUR notional "
                      f"({v['current']:+.3f} -> {v['target']:+.3f})")
        else:
            print("\nNo trades. Hold what you have.")
            print("This is the normal output most days. It is the strategy working, not failing.")

    for w in warnings:
        print(f"  ! {w}", file=sys.stderr)

    if not args.no_write:
        state_path.write_text(json.dumps(
            {"updated_at": payload["generated_at"], "positions": payload["positions"]}, indent=2
        ))


if __name__ == "__main__":
    main()
