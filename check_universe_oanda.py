#!/usr/bin/env python3
"""
Does the edge survive on only the instruments actually tradeable at OANDA?

    python3 check_universe_oanda.py

check_universe.py's 22-instrument universe included CME/CBOT futures --
copper, corn, wheat, soybeans, sugar, both bond futures -- that don't all
exist as OANDA CFDs, and OANDA's EU retail entity turned out to be narrower
than even that: confirmed by hand, symbol by symbol, on the actual account
this dashboard serves, only 14 of the 22 have a real OANDA equivalent. Bonds
and agriculture drop out entirely, not just one or two names.

Assuming the 22-instrument edge simply carries over to a smaller universe
missing two whole asset classes would be exactly the kind of unverified leap
this project has been built to avoid. This tests the actual, tradeable
subset directly rather than assuming.

PRE-SPECIFIED: the 14 instruments below are exactly what was confirmed on
the account by direct symbol search, nothing added or removed for a better
number. Same signal (252-day momentum, no cap), same costs, same admin-fee
model as check_universe.py, so the two are directly comparable.

It places no trades and connects to no broker.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_strategy import Tee, portfolio_series, score  # noqa: E402
import check_strategy  # noqa: E402
import check_universe as cu  # noqa: E402

# Confirmed by hand on the actual OANDA EU (TMS Brokers) retail account this
# dashboard serves -- not from marketing pages, which turned out to describe
# a different, broader entity (OANDA Global Markets / BVI). Name here is the
# OANDA-side symbol for the record; the Yahoo ticker is what check_universe's
# existing UNIVERSE list already carries, so this filters rather than
# redefines.
OANDA_SYMBOL = {
    "S&P 500": "US500", "DAX": "DE30", "FTSE 100": "UK100",
    "Nikkei 225": "JP225", "ASX 200": "AU200",
    "Gold": "XAU/USD", "Silver": "XAG/USD",
    "WTI crude": "WTICO", "Brent crude": "BCO", "Natural gas": "NATGAS",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
}

OANDA_UNIVERSE = [row for row in cu.UNIVERSE if row[0] in OANDA_SYMBOL]

DROPPED = [row[0] for row in cu.UNIVERSE if row[0] not in OANDA_SYMBOL]


def main():
    say = Tee("universe_oanda_output.txt")
    say("=" * 74)
    say("  THE EDGE, RESTRICTED TO WHAT'S ACTUALLY TRADEABLE AT OANDA (EU)")
    say("=" * 74)
    say()
    say(f"{len(OANDA_UNIVERSE)} of {len(cu.UNIVERSE)} instruments confirmed on the account.")
    say(f"Dropped entirely: {', '.join(DROPPED)}")
    say("(bonds and agriculture as whole asset classes -- not cherry-picked names)")
    say()
    say("Downloading ~25 years of daily prices for the confirmed 14...")

    data, failed = {}, []
    for name, ticker, klass in OANDA_UNIVERSE:
        try:
            dates, closes = cu.fetch_ticker(ticker)
            data[name] = (dates, closes, klass)
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            say(f"  {name:<14} FAILED: {exc}")
    say(f"  {len(data)} of {len(OANDA_UNIVERSE)} instruments loaded.")
    if not data:
        say("Nothing downloaded; cannot draw any conclusion.")
        return 1
    say()

    check_strategy.WARMUP = cu.WARMUP
    everything = {n: (d, c) for n, (d, c, _) in data.items()}

    # Same signal that won the multi-speed comparison: unchanged, single
    # 252-day momentum, no holding cap.
    targets = {name: cu.targets_for(closes, cu.tsm(closes, cu.LOOKBACK))
               for name, (_, closes, _) in data.items()}

    # ---- head to head: full 22-instrument result vs this 14 -------------
    say("-" * 74)
    say("14-INSTRUMENT (OANDA) RESULT AT DIFFERENT COST LEVELS")
    say("-" * 74)
    say(f"{'cost':<24}{'gross Sharpe':>14}{'financed Sharpe':>17}{'return/yr':>12}{'worst fall':>12}")

    financed = {}
    for cost in cu.COST_LEVELS:
        gross_series = portfolio_series(everything, targets, cost)
        fin_series = cu.financed_portfolio(data, targets, cost)
        g = score([r for _, r in gross_series])
        f = score([r for _, r in fin_series])
        if not g or not f:
            continue
        financed[cost] = (g, f)
        label = "free (impossible)" if cost == 0 else f"{cost:g} bp per trade"
        say(f"{label:<24}{g['sharpe']:>14.2f}{f['sharpe']:>17.2f}{f['cagr']:>11.1%}{f['drawdown']:>12.1%}")

    say()
    say("For reference, the full 22-instrument result at 2bp (from")
    say("check_universe.py): gross Sharpe 0.54, financed Sharpe 0.28, t=1.5.")

    # ---- by asset class, so it's clear which classes are still pulling weight
    say()
    say("-" * 74)
    say("BY ASSET CLASS (2 bp, financed)")
    say("-" * 74)
    from collections import defaultdict
    classes = defaultdict(dict)
    for name, (dates, closes, klass) in data.items():
        classes[klass][name] = (dates, closes, klass)

    for klass, members in classes.items():
        sub_data = {n: (d, c, k) for n, (d, c, k) in members.items()}
        sub_targets = {n: targets[n] for n in members}
        fin = cu.financed_portfolio(sub_data, sub_targets, 2.0)
        s = score([r for _, r in fin])
        if s:
            say(f"{klass:<16}{len(members):>4} instruments   Sharpe {s['sharpe']:>6.2f}   {s['cagr']:>7.1%}/yr")

    # ---- verdict ----------------------------------------------------------
    say()
    say("=" * 74)
    say("  WHAT THIS MEANS")
    say("=" * 74)
    say()

    ref = financed.get(2.0)
    if not ref:
        say("Not enough data to conclude.")
        return 1
    g, f = ref
    say(f"  14-instrument, financed: Sharpe {f['sharpe']:.2f}, t={f['t']:.1f}, "
        f"return {f['cagr']:.1%}/yr, worst fall {f['drawdown']:.1%}")
    say(f"  22-instrument, financed (reference): Sharpe 0.28, t=1.5")
    say()

    if f["sharpe"] >= 0.2 and f["t"] >= 1.0:
        say("HOLDS UP. Losing bonds and agriculture cost some diversification,")
        say("but what is actually tradeable here still shows the same shape of")
        say("edge as the full universe -- thin, not gone.")
    elif f["sharpe"] > 0:
        say("WEAKER, BUT STILL THERE. The full-universe number was already")
        say("marginal; this narrower, real-world-tradeable version is thinner")
        say("still. Worth watching as a paper record, not worth funding.")
    else:
        say("DOES NOT HOLD UP. Whatever edge existed in the full 22-instrument")
        say("test depended more than expected on bonds and/or agriculture.")
        say("What is actually available at OANDA (EU) does not show it.")

    if failed:
        say()
        say(f"  Could not download: {', '.join(failed)}.")

    say()
    say("-" * 74)
    say("Saved to universe_oanda_output.txt")
    say("-" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
