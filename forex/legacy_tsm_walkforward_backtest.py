"""
Time-Series Momentum walk-forward backtest for spot FX.

Methodology mirrors the validated approach discussed with Claude:
- Signal: sign of cumulative return over a lookback window (default 126 trading days)
- Position sizing: volatility-targeted (default 10% annualized)
- Validation: rolling walk-forward (3y train / 1y test), NOT a single in-sample fit
- Costs: configurable transaction cost per trade (in bps) applied on position changes

Requirements:
    pip install yfinance pandas numpy --break-system-packages
    (or use your own data source / broker export instead of yfinance)

Usage:
    python tsm_walkforward_backtest.py --pair EURUSD=X --lookback 126 --vol-target 0.10

Notes:
- yfinance ticker convention for FX: "EURUSD=X", "USDJPY=X", etc.
- This is a research/education script. It has no connection to any broker
  and places no live trades. Treat its output the way you'd treat any
  backtest: informative, not predictive, and blind to slippage/liquidity
  in live conditions.
"""

import argparse
import numpy as np
import pandas as pd


def load_prices(pair: str, period: str = "10y") -> pd.Series:
    import yfinance as yf
    data = yf.download(pair, period=period, interval="1d", progress=False)
    if data.empty:
        raise RuntimeError(f"No data returned for {pair}. Check the ticker symbol.")
    return data["Close"].dropna()


def tsm_signal(prices: pd.Series, lookback: int) -> pd.Series:
    """Sign of cumulative return over `lookback` trading days. +1 long, -1 short."""
    cum_ret = prices.pct_change(lookback)
    return np.sign(cum_ret).fillna(0)


def realized_vol(returns: pd.Series, window: int = 20) -> pd.Series:
    return returns.rolling(window).std() * np.sqrt(252)


def backtest(prices: pd.Series, lookback: int, vol_target: float,
             cost_bps: float = 2.0, max_leverage: float = 1.0) -> pd.DataFrame:
    daily_ret = prices.pct_change().fillna(0)
    signal = tsm_signal(prices, lookback).shift(1).fillna(0)  # trade next day, avoid lookahead
    vol = realized_vol(daily_ret).shift(1)

    raw_size = (vol_target / vol).clip(upper=max_leverage)
    raw_size = raw_size.fillna(0)
    position = signal * raw_size

    strat_ret = position.shift(0) * daily_ret  # position already lagged via signal.shift(1)

    turnover = position.diff().abs().fillna(0)
    cost = turnover * (cost_bps / 10000.0)
    strat_ret_net = strat_ret - cost

    equity = (1 + strat_ret_net).cumprod()

    out = pd.DataFrame({
        "price": prices,
        "signal": signal,
        "position": position,
        "daily_return": daily_ret,
        "strategy_return_net": strat_ret_net,
        "equity_curve": equity,
    })
    return out


def performance_summary(strat_ret: pd.Series) -> dict:
    ann_return = (1 + strat_ret).prod() ** (252 / len(strat_ret)) - 1
    ann_vol = strat_ret.std() * np.sqrt(252)
    sharpe = ann_return / ann_vol if ann_vol > 0 else float("nan")
    equity = (1 + strat_ret).cumprod()
    running_max = equity.cummax()
    drawdown = (equity / running_max) - 1
    max_dd = drawdown.min()
    calmar = ann_return / abs(max_dd) if max_dd != 0 else float("nan")
    return {
        "CAGR": ann_return,
        "Annualized Vol": ann_vol,
        "Sharpe": sharpe,
        "Max Drawdown": max_dd,
        "Calmar": calmar,
    }


def walk_forward(prices: pd.Series, lookback: int, vol_target: float,
                  train_years: int = 3, test_years: int = 1,
                  cost_bps: float = 2.0, max_leverage: float = 1.0):
    """
    Rolling walk-forward: fit nothing (TSM has no free parameter beyond lookback,
    which we hold fixed here for simplicity), but report OUT-OF-SAMPLE performance
    per rolling test window so you can see stability across regimes rather than
    trusting a single full-history number.
    """
    results = []
    start = prices.index.min()
    end = prices.index.max()

    window_start = start
    while True:
        train_end = window_start + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if test_end > end:
            break

        test_prices = prices.loc[train_end:test_end]
        if len(test_prices) < lookback + 10:
            window_start += pd.DateOffset(years=1)
            continue

        bt = backtest(test_prices, lookback, vol_target, cost_bps, max_leverage)
        perf = performance_summary(bt["strategy_return_net"].dropna())
        perf["window_start"] = train_end.date()
        perf["window_end"] = test_end.date()
        results.append(perf)

        window_start += pd.DateOffset(years=1)

    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser(description="TSM walk-forward FX backtest")
    parser.add_argument("--pair", default="EURUSD=X", help="yfinance ticker, e.g. EURUSD=X, USDJPY=X")
    parser.add_argument("--lookback", type=int, default=126, help="Momentum lookback in trading days")
    parser.add_argument("--vol-target", type=float, default=0.10, help="Annualized vol target, e.g. 0.10")
    parser.add_argument("--cost-bps", type=float, default=2.0, help="Round-trip cost proxy per position change, in bps")
    parser.add_argument("--max-leverage", type=float, default=1.0, help="Cap on position size (1.0 = no leverage)")
    parser.add_argument("--period", default="10y", help="History length to download, e.g. 10y, max")
    args = parser.parse_args()

    print(f"Loading {args.pair} ({args.period})...")
    prices = load_prices(args.pair, args.period)

    print("\n--- Full-sample backtest (in-sample, for reference only) ---")
    full_bt = backtest(prices, args.lookback, args.vol_target, args.cost_bps, args.max_leverage)
    full_perf = performance_summary(full_bt["strategy_return_net"].dropna())
    for k, v in full_perf.items():
        print(f"{k:>18}: {v:.4f}" if isinstance(v, float) else f"{k:>18}: {v}")

    print("\n--- Walk-forward out-of-sample windows (the numbers that actually matter) ---")
    wf = walk_forward(prices, args.lookback, args.vol_target, cost_bps=args.cost_bps, max_leverage=args.max_leverage)
    if wf.empty:
        print("Not enough history for a full walk-forward window. Try a longer --period.")
    else:
        print(wf.to_string(index=False))
        print(f"\nMedian OOS Sharpe across windows: {wf['Sharpe'].median():.3f}")
        print(f"Worst OOS window Sharpe:          {wf['Sharpe'].min():.3f}")
        print(f"Worst OOS window Max Drawdown:    {wf['Max Drawdown'].min():.3f}")

    print("\nReminder: this script never places trades. It's here so you can verify")
    print("(or break) the numbers we discussed yourself, on your own data pull.")


if __name__ == "__main__":
    main()
