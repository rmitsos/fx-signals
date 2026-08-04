#!/usr/bin/env python3
"""
Per-instrument Sharpe, t-stat, and the exact data period behind each one.

    python3 check_per_instrument.py

Every verdict in this project so far has been reported at the portfolio
level (all 14 instruments together) or by asset class (metals, energy,
equity index, currencies) -- because trading one instrument alone is close
to noise, and the whole point of this strategy is spreading risk across
many weakly-correlated trends at once. That is still true; nothing here
changes it.

But "what's the Sharpe of GBPUSD, and over what period" is a fair, distinct
question the portfolio and asset-class numbers can't answer on their own.
This reports it directly: every one of the 14 OANDA-tradeable instruments,
on its own, with the exact date range and number of days Yahoo's data
actually covers for it -- not assumed to be the same "~25 years" for
everything, since some tickers (spot FX especially) have less history
available than futures do.

Same signal, same costs, same admin-fee model as check_universe_oanda.py.

READ WITH CARE: a single row here is a much smaller, noisier sample than
the portfolio number, and reading one instrument's row as "this signal is
more trustworthy than that one" is exactly the mistake this project has
tried to avoid throughout. This table exists for transparency about what's
behind each row on the dashboard, not for ranking instruments against each
other.

It places no trades and connects to no broker.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_strategy import Tee, score  # noqa: E402
import check_universe as cu  # noqa: E402
import check_universe_oanda as cuo  # noqa: E402


def main():
    say = Tee("per_instrument_output.txt")
    say("=" * 90)
    say("  PER-INSTRUMENT SHARPE, T-STAT, AND THE ACTUAL DATA PERIOD BEHIND EACH")
    say("=" * 90)
    say()
    say("Portfolio-level and asset-class numbers are still the ones the strategy is")
    say("judged on -- one instrument alone is close to noise. This is for")
    say("transparency about what's behind each row on the dashboard, not for")
    say("ranking instruments against each other.")
    say()
    say("Downloading prices for the 14 OANDA-tradeable instruments...")

    rows, failed = [], []
    for name, ticker, klass in cuo.OANDA_UNIVERSE:
        try:
            dates, closes = cu.fetch_ticker(ticker)
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            say(f"  {name:<14} FAILED: {exc}")
            continue

        signal = cu.tsm(closes, cu.LOOKBACK)
        targets = cu.targets_for(closes, signal)
        nets = cu.evaluate_financed(closes, targets, 2.0, cu.ADMIN_FEES[klass])
        scored_dates = dates[cu.WARMUP:]
        scored_nets = nets[cu.WARMUP:]
        s = score(scored_nets)
        rows.append((name, ticker, klass, dates, scored_dates, s))
    say(f"  {len(rows)} of {len(cuo.OANDA_UNIVERSE)} instruments loaded.")
    say()

    say("-" * 90)
    say("FINANCED (2bp cost), SCORED PERIOD ONLY -- WARMUP (first ~332 days) EXCLUDED")
    say("-" * 90)
    say(f"{'instrument':<14}{'class':<14}{'scored period':<24}{'days':>7}"
        f"{'sharpe':>9}{'t':>7}{'cagr':>9}{'worst fall':>12}")
    for name, _, klass, _, scored_dates, s in rows:
        period = f"{scored_dates[0]} to {scored_dates[-1]}" if scored_dates else "n/a"
        if s:
            say(f"{name:<14}{klass:<14}{period:<24}{s['days']:>7}{s['sharpe']:>9.2f}"
                f"{s['t']:>7.1f}{s['cagr']:>9.1%}{s['drawdown']:>12.1%}")
        else:
            say(f"{name:<14}{klass:<14}{period:<24}{'--':>7}{'--':>9}{'--':>7}{'--':>9}{'--':>12}")
    say()

    say("-" * 90)
    say("FULL DOWNLOADED RANGE PER TICKER (before the warmup the signal needs to start)")
    say("-" * 90)
    for name, ticker, klass, dates, _, _ in rows:
        say(f"  {name:<14} ({ticker:<10}) {dates[0]} to {dates[-1]}  ({len(dates)} bars)")

    if failed:
        say()
        say(f"Could not download: {', '.join(failed)}.")

    say()
    say("-" * 90)
    say("Saved to per_instrument_output.txt")
    say("-" * 90)
    return 0


if __name__ == "__main__":
    sys.exit(main())
