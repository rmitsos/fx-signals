"""Walk-forward backtest runner.

    python3 run_backtest.py --pairs stooq:eurusd stooq:usdjpy --strategies tsm donchian
    python3 run_backtest.py --pairs csv:mydata.csv --strategies tsm --cost-sweep 0 1 3 10
    python3 run_backtest.py --pairs synthetic:seed=1 --strategies all   # no network needed

Reports out-of-sample results only. The full-sample number is printed too,
but greyed out in your mind please: it is the number that made you like the
strategy in the first place, so it cannot also be the evidence for it.

This script places no trades and talks to no broker.
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fxlab import data, strategies
from fxlab.engine import Config, run, walk_forward
from fxlab.metrics import deflated_hurdle, summary


def _short(spec: str) -> str:
    return spec.split(":", 1)[-1].replace("=X", "").lower()


def parse_params(items):
    """Turn ['tsm.lookback=21', 'donchian.lookback=20'] into nested kwargs."""
    out: dict[str, dict] = {}
    for item in items:
        target, _, value = item.partition("=")
        strat, _, key = target.partition(".")
        if not key or not value:
            raise ValueError(f"expected 'strategy.kwarg=value', got {item!r}")
        out.setdefault(strat, {})[key] = float(value) if "." in value else int(value)
    return out


def build_signal_fn(name, params, max_hold):
    fn = strategies.REGISTRY[name]
    if params:
        fn = partial(fn, **params)
        fn.__name__ = name  # partial has no __name__, and with_max_hold wants one
    if max_hold > 0:
        fn = strategies.with_max_hold(fn, max_hold)
    return fn


def evaluate(prices, signal_fn, cfg, train_years, test_years):
    """Walk-forward one strategy on one pair. Returns (stats dict, oos returns)."""
    table, oos = walk_forward(prices, signal_fn, cfg, train_years=train_years, test_years=test_years)
    if oos.empty:
        return None, None
    stats = summary(oos["net"], oos["position"], cfg.periods_per_year)
    stats["Windows"] = len(table)
    stats["WorstWin"] = float(table["Sharpe"].min())
    return stats, oos["net"]


def main():
    p = argparse.ArgumentParser(description="Walk-forward FX backtest")
    p.add_argument("--pairs", nargs="+", default=["synthetic:seed=1"],
                   help="specs like stooq:eurusd, yf:EURUSD=X, csv:path.csv, synthetic:seed=1")
    p.add_argument("--strategies", nargs="+", default=["tsm"],
                   help=f"one or more of {sorted(strategies.REGISTRY)}, or 'all'")
    p.add_argument("--cost-bps", type=float, default=1.0, help="one-way cost per unit traded")
    p.add_argument("--cost-sweep", nargs="*", type=float, default=None,
                   help="repeat the run at several cost levels to find the break-even")
    p.add_argument("--vol-target", type=float, default=0.10)
    p.add_argument("--max-leverage", type=float, default=1.0)
    p.add_argument("--rebalance-band", type=float, default=0.0,
                   help="skip trades smaller than this fraction of notional (cuts resizing churn)")
    p.add_argument("--params", nargs="*", default=[],
                   help="strategy kwargs, e.g. tsm.lookback=21 donchian.lookback=20")
    p.add_argument("--max-hold", type=int, default=0,
                   help="force flat after N bars; 10 targets a two-week horizon (0 = no cap)")
    p.add_argument("--train-years", type=int, default=3)
    p.add_argument("--test-years", type=int, default=1)
    p.add_argument("--period", default="max", help="history length for yfinance specs")
    args = p.parse_args()

    names = sorted(strategies.REGISTRY) if args.strategies == ["all"] else args.strategies
    for n in names:
        if n not in strategies.REGISTRY:
            p.error(f"unknown strategy {n!r}; choose from {sorted(strategies.REGISTRY)}")
    try:
        params = parse_params(args.params)
    except ValueError as exc:
        p.error(str(exc))
    for n in params:
        if n not in names:
            p.error(f"--params names {n!r}, which is not in --strategies")

    series = {}
    for spec in args.pairs:
        try:
            series[_short(spec)] = data.load(spec, args.period)
        except Exception as exc:  # noqa: BLE001 -- one bad feed shouldn't kill the run
            print(f"  ! {spec}: {exc}", file=sys.stderr)
    if not series:
        sys.exit("No price data could be loaded.")

    for name, px in series.items():
        print(f"  {name}: {len(px)} bars, {px.index.min().date()} to {px.index.max().date()}")

    costs = args.cost_sweep if args.cost_sweep else [args.cost_bps]
    cols = ["CAGR", "Vol", "Sharpe", "t_stat", "MaxDD", "Calmar",
            "Trades", "AvgHold", "TradeWin", "Turnover", "WorstWin"]

    for cost in costs:
        cfg = Config(vol_target=args.vol_target, cost_bps=cost,
                     max_leverage=args.max_leverage, rebalance_band=args.rebalance_band)
        print(f"\n=== Out-of-sample, cost = {cost:g} bps one-way "
              f"({args.train_years}y train / {args.test_years}y test) ===")

        rows, oos_by_strategy = {}, {}
        for strat in names:
            signal_fn = build_signal_fn(strat, params.get(strat, {}), args.max_hold)
            per_pair = []
            for pair, px in series.items():
                stats, oos = evaluate(px, signal_fn, cfg, args.train_years, args.test_years)
                if stats is None:
                    continue
                rows[(strat, pair)] = stats
                per_pair.append(oos.rename(pair))

            # Equal-weight portfolio. Single-pair FX momentum is mostly noise;
            # the published edge is a diversified one, so this is the line to read.
            if len(per_pair) > 1:
                book = pd.concat(per_pair, axis=1).fillna(0.0).mean(axis=1)
                rows[(strat, "PORTFOLIO")] = summary(book, periods_per_year=cfg.periods_per_year)
                oos_by_strategy[strat] = book

        if not rows:
            print("  not enough history for a walk-forward window")
            continue

        table = pd.DataFrame(rows).T[[c for c in cols if c in next(iter(rows.values()))]]
        table.index.names = ["strategy", "pair"]
        with pd.option_context("display.float_format", lambda v: f"{v:8.3f}", "display.width", 200):
            print(table.to_string())

    n_trials = len(names) * len(series) * len(costs)
    hurdle = deflated_hurdle(n_trials)
    print(f"\n{n_trials} configuration(s) evaluated.", end=" ")
    if hurdle > 2.0:
        print(f"With that much searching, the best one needs\n|t| above roughly {hurdle:.1f} to mean anything, not the usual 2.0.")
    else:
        print("A winner still needs |t| above 2.0.")
    print("Check AvgHold against the horizon you intended -- it is an output, not a setting.")
    print("Sharpe below ~0.4 out of sample is not a business. It is a hobby with variance.")


if __name__ == "__main__":
    main()
