#!/usr/bin/env python3
"""
Does combining trend speeds beat the single 252-day signal?

    python3 check_universe_multispeed.py

check_universe.py tested one lookback (252 days, 12 months) because that is
the single canonical signal in Moskowitz, Ooi & Pedersen (2012). But AQR's
longer-running work -- "A Century of Evidence on Trend-Following Investing"
and "Time Series Momentum" -- actually uses an equal-weighted COMBINATION of
1-month, 3-month, and 12-month signals, on the finding that fast and slow
trend read on largely uncorrelated information (documented correlation
between fast and slow trend models as low as 0.17 in follow-up work), so
blending them behaves like adding a second, mostly independent bet rather
than averaging noise.

PRE-SPECIFIED, NOT SEARCHED: 21/63/252 trading days (1/3/12 months), equal
weight, chosen because that is AQR's own published methodology -- not
picked after looking at which combination scores best here. Each speed is
independently sized to the same volatility target used everywhere else in
this kit, then the three resulting position series are averaged. That is
the only new degree of freedom; if it does not help, the answer is no,
not "try more combinations until one does."

Same universe, same costs, same admin-fee model as check_universe.py, so the
two are directly comparable. It places no trades and connects to no broker.
"""

import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_strategy import Tee, portfolio_series, score  # noqa: E402
import check_strategy  # noqa: E402
import check_universe as cu  # noqa: E402

SPEEDS = [21, 63, 252]  # 1 / 3 / 12 months -- AQR's own combination
COST_BPS = 2.0          # matches the headline verdict in check_universe.py


def blended_targets(closes):
    """Equal-weight combination of independently-sized 1/3/12-month sleeves."""
    sleeves = [cu.targets_for(closes, cu.tsm(closes, lb)) for lb in SPEEDS]
    return [statistics.fmean(day) for day in zip(*sleeves)]


def main():
    say = Tee("universe_multispeed_output.txt")
    say("=" * 74)
    say("  MULTI-SPEED TREND ENSEMBLE vs. THE SINGLE 252-DAY SIGNAL")
    say("=" * 74)
    say()
    say(f"Speeds combined: {', '.join(f'{s}d' for s in SPEEDS)} (1 / 3 / 12 months),")
    say("equal weight, each independently vol-targeted before blending.")
    say()
    say("Downloading ~25 years of daily prices (same 22-instrument universe")
    say("as check_universe.py)...")

    data, failed = {}, []
    for name, ticker, klass in cu.UNIVERSE:
        try:
            dates, closes = cu.fetch_ticker(ticker)
            data[name] = (dates, closes, klass)
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            say(f"  {name:<14} FAILED: {exc}")
    say(f"  {len(data)} of {len(cu.UNIVERSE)} instruments loaded.")
    if not data:
        say("Nothing downloaded; cannot draw any conclusion.")
        return 1
    say()

    check_strategy.WARMUP = cu.WARMUP
    everything = {n: (d, c) for n, (d, c, _) in data.items()}

    # ---- single-speed baseline (unchanged from check_universe.py) ---------
    single = {name: cu.targets_for(closes, cu.tsm(closes, cu.LOOKBACK))
              for name, (_, closes, _) in data.items()}

    # ---- multi-speed ensemble -----------------------------------------
    multi = {name: blended_targets(closes) for name, (_, closes, _) in data.items()}

    spans_single = [s for t in single.values() for s in check_strategy.holding_periods(t)]
    spans_multi = [s for t in multi.values() for s in check_strategy.holding_periods(t)]
    typical_single = round(statistics.fmean(spans_single)) if spans_single else cu.LOOKBACK
    typical_multi = round(statistics.fmean(spans_multi)) if spans_multi else cu.LOOKBACK

    say(f"Average holding period -- single-speed: {typical_single}d, "
        f"multi-speed: {typical_multi}d.")
    say()

    # ---- head-to-head, gross and financed ------------------------------
    say("-" * 74)
    say(f"HEAD TO HEAD ({COST_BPS:g} bp cost)")
    say("-" * 74)
    say(f"{'':<22}{'gross Sharpe':>14}{'financed Sharpe':>17}{'return/yr':>12}{'worst fall':>12}")

    results = {}
    for label, targets in [("Single-speed (252d)", single), ("Multi-speed (1/3/12mo)", multi)]:
        gross_series = portfolio_series(everything, targets, COST_BPS)
        fin_series = cu.financed_portfolio(data, targets, COST_BPS)
        g = score([r for _, r in gross_series])
        f = score([r for _, r in fin_series])
        if not g or not f:
            say(f"{label:<22} not enough data")
            continue
        results[label] = (g, f)
        say(f"{label:<22}{g['sharpe']:>14.2f}{f['sharpe']:>17.2f}{f['cagr']:>11.1%}{f['drawdown']:>12.1%}")

    # ---- year by year, multi-speed, financed ---------------------------
    say()
    say("-" * 74)
    say("YEAR BY YEAR, MULTI-SPEED, FINANCED")
    say("-" * 74)

    fin_daily = cu.financed_portfolio(data, multi, COST_BPS)
    by_year = defaultdict(list)
    for day, ret in fin_daily:
        by_year[day[:4]].append(ret)

    yearly = {}
    for year, rets in by_year.items():
        total = 1.0
        for x in rets:
            total *= (1.0 + x)
        yearly[year] = total - 1.0

    biggest = max((abs(v) for v in yearly.values()), default=0.0) or 1.0
    good = 0
    for year in sorted(yearly):
        pnl = yearly[year]
        good += pnl > 0
        bar = "#" * max(1, round(abs(pnl) / biggest * 26))
        say(f"  {year}  {pnl:>7.1%}  {'' if pnl >= 0 else '-'}{bar}")
    if yearly:
        say()
        say(f"  Profitable in {good} of {len(yearly)} years.")

    # ---- verdict ---------------------------------------------------------
    say()
    say("=" * 74)
    say("  WHAT THIS MEANS")
    say("=" * 74)
    say()

    single_r, multi_r = results.get("Single-speed (252d)"), results.get("Multi-speed (1/3/12mo)")
    if not single_r or not multi_r:
        say("Not enough data to conclude.")
        return 1

    _, single_fin = single_r
    _, multi_fin = multi_r
    improvement = multi_fin["sharpe"] - single_fin["sharpe"]

    say(f"  Single-speed, financed: Sharpe {single_fin['sharpe']:.2f}, t={single_fin['t']:.1f}")
    say(f"  Multi-speed,  financed: Sharpe {multi_fin['sharpe']:.2f}, t={multi_fin['t']:.1f}")
    say(f"  Difference: {improvement:+.2f} Sharpe")
    say()

    if improvement >= 0.1 and multi_fin["t"] > single_fin["t"]:
        say("WORTH ADOPTING. The blend improves both the Sharpe and the")
        say("statistical confidence over the single-speed version -- consistent")
        say("with the literature, not just a lucky combination on this data.")
    elif abs(improvement) < 0.1:
        say("NO MEANINGFUL DIFFERENCE. The single-speed version was already")
        say("capturing most of what is here. Adding complexity for a result")
        say("this close to a wash is not worth it.")
    else:
        say("WORSE. The single 252-day signal was the better choice on this")
        say("universe. Not every documented enhancement transfers -- that is")
        say("exactly why this gets tested rather than assumed.")

    if failed:
        say()
        say(f"  Could not download: {', '.join(failed)}.")

    say()
    say("-" * 74)
    say("Saved to universe_multispeed_output.txt")
    say("-" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
