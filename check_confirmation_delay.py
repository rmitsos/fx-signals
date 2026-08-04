#!/usr/bin/env python3
"""
Does waiting for a flip to hold before acting on it improve the trend rule?

    python3 check_confirmation_delay.py

THE IDEA: right now a flip in the 252-day momentum sign is acted on
immediately -- so a position can be opened, and just as easily reversed,
within days of a trend barely turning. This tests requiring the new sign to
persist for N consecutive trading days before the position actually
changes, on the theory that a trend surviving its first N days is less
likely to be a false start than one acted on the instant it appears.

SYMMETRIC BY CONSTRUCTION: the delay gates entries and exits alike, because
in this system -- no separate stop, no time exit, only reversal -- they are
the same event: a sign flip. There is no honest way to require confirmation
before entering but act on exits instantly without that asymmetry itself
being an untested, arbitrary choice.

Pure price data, so unlike the volume-exhaustion overlay this runs on the
full 14-instrument OANDA-tradeable universe, currencies included -- exactly
the class (Sharpe -0.16, the weakest of the four in check_universe_oanda.py)
a fast reversal on a pair like GBPUSD belongs to.

PRE-SPECIFIED: confirmation windows of 5, 10 and 20 trading days, with 10 as
the primary, fixed before this ran once -- for the same reason nothing else
in this project got tuned on the data it was tested on. The 5- and 20-day
results are a robustness check, not a menu to pick the best number from
afterwards.

STATED PRIOR, BEFORE RUNNING: a related idea -- the multi-speed ensemble,
which effectively requires several signals to agree -- already made things
worse on this data (Sharpe 0.28 -> -0.02). Confirmation delays are commonly
found in the trend-following literature to cost more in late entries, missing
the fastest part of a real trend, than they save by skipping false starts.
This is a real test of that prior on this universe, not an assumption.

Same signal, same costs, same admin-fee model as check_universe_oanda.py, so
this is directly comparable to the no-delay baseline it is judged against.

It places no trades and connects to no broker.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_strategy import Tee, score  # noqa: E402
import check_universe as cu  # noqa: E402
import check_universe_oanda as cuo  # noqa: E402

DELAYS = [5, 10, 20]
PRIMARY_DELAY = 10


def confirmed_signal(raw_signal, delay):
    """Only switch the acted-upon sign once the new raw sign has held for
    `delay` consecutive days. Symmetric for entries and exits alike -- both
    are the same underlying opinion, just gated by how long it has persisted.
    """
    if delay <= 0:
        return list(raw_signal)
    out = [0.0] * len(raw_signal)
    confirmed = 0.0
    run_sign, run_len = None, 0
    for i, s in enumerate(raw_signal):
        if s == run_sign:
            run_len += 1
        else:
            run_sign, run_len = s, 1
        if run_sign != confirmed and run_len >= delay:
            confirmed = run_sign
        out[i] = confirmed
    return out


def count_flips(signal):
    return sum(1 for i in range(1, len(signal)) if signal[i] != signal[i - 1])


def main():
    say = Tee("confirmation_delay_output.txt")
    say("=" * 74)
    say("  DOES WAITING FOR A FLIP TO HOLD IMPROVE THE TREND RULE?")
    say("=" * 74)
    say()
    say(f"{len(cuo.OANDA_UNIVERSE)} instruments -- the full OANDA-tradeable universe,")
    say("currencies included, since this filter needs only price data.")
    say()
    say("Downloading ~25 years of daily prices...")

    data, failed = {}, []
    for name, ticker, klass in cuo.OANDA_UNIVERSE:
        try:
            dates, closes = cu.fetch_ticker(ticker)
            data[name] = (dates, closes, klass)
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            say(f"  {name:<14} FAILED: {exc}")
    say(f"  {len(data)} of {len(cuo.OANDA_UNIVERSE)} instruments loaded.")
    if not data:
        say("Nothing downloaded; cannot draw any conclusion.")
        return 1
    say()

    raw_signal, baseline_targets = {}, {}
    for name, (_, closes, _) in data.items():
        sig = cu.tsm(closes, cu.LOOKBACK)
        raw_signal[name] = sig
        baseline_targets[name] = cu.targets_for(closes, sig)

    delayed_signal = {d: {} for d in DELAYS}
    delayed_targets = {d: {} for d in DELAYS}
    for name, (_, closes, _) in data.items():
        for d in DELAYS:
            sig = confirmed_signal(raw_signal[name], d)
            delayed_signal[d][name] = sig
            delayed_targets[d][name] = cu.targets_for(closes, sig)

    # ---- how many flips does this actually filter out? ----------------------
    say("-" * 74)
    say(f"FLIP COUNT: RAW SIGNAL VS CONFIRMED (delay={PRIMARY_DELAY}d), SCORED PERIOD ONLY")
    say("-" * 74)
    say(f"{'instrument':<16}{'raw flips':>12}{'confirmed':>12}{'filtered out':>15}")
    total_raw, total_confirmed = 0, 0
    for name in data:
        r = count_flips(raw_signal[name][cu.WARMUP:])
        c = count_flips(delayed_signal[PRIMARY_DELAY][name][cu.WARMUP:])
        total_raw += r
        total_confirmed += c
        say(f"{name:<16}{r:>12}{c:>12}{r - c:>15}")
    say(f"{'TOTAL':<16}{total_raw:>12}{total_confirmed:>12}{total_raw - total_confirmed:>15}")
    say()

    # ---- head-to-head: baseline vs each delay, financed ----------------------
    say("-" * 74)
    say("FINANCED PORTFOLIO (2bp cost), BASELINE VS CONFIRMATION DELAY")
    say("-" * 74)
    say(f"{'version':<28}{'sharpe':>9}{'t':>7}{'return/yr':>12}{'worst fall':>12}")

    b_series = cu.financed_portfolio(data, baseline_targets, 2.0)
    b = score([r for _, r in b_series])
    if b:
        say(f"{'baseline (no delay)':<28}{b['sharpe']:>9.2f}{b['t']:>7.1f}"
            f"{b['cagr']:>11.1%}{b['drawdown']:>12.1%}")

    results = {}
    for d in DELAYS:
        series = cu.financed_portfolio(data, delayed_targets[d], 2.0)
        s = score([r for _, r in series])
        results[d] = s
        if s:
            tag = "  <- PRIMARY" if d == PRIMARY_DELAY else ""
            say(f"{f'confirm >= {d}d':<28}{s['sharpe']:>9.2f}{s['t']:>7.1f}"
                f"{s['cagr']:>11.1%}{s['drawdown']:>12.1%}{tag}")

    # ---- by asset class, at the primary delay ----------------------------------
    say()
    say("-" * 74)
    say(f"BY ASSET CLASS, FINANCED (primary delay: {PRIMARY_DELAY}d)")
    say("-" * 74)
    classes = defaultdict(list)
    for name, (_, _, klass) in data.items():
        classes[klass].append(name)

    for klass, names in classes.items():
        class_data = {n: data[n] for n in names}
        base_class = cu.financed_portfolio(class_data, {n: baseline_targets[n] for n in names}, 2.0)
        delay_class = cu.financed_portfolio(class_data, {n: delayed_targets[PRIMARY_DELAY][n] for n in names}, 2.0)
        sb, sd = score([r for _, r in base_class]), score([r for _, r in delay_class])
        if sb and sd:
            say(f"{klass:<14} baseline Sharpe {sb['sharpe']:>6.2f}   "
                f"with {PRIMARY_DELAY}d confirmation {sd['sharpe']:>6.2f}")

    # ---- verdict -----------------------------------------------------------------
    say()
    say("=" * 74)
    say("  WHAT THIS MEANS")
    say("=" * 74)
    say()

    primary = results.get(PRIMARY_DELAY)
    if not b or not primary:
        say("Not enough data to conclude.")
        return 1

    edge = primary["sharpe"] - b["sharpe"]
    say(f"  Baseline (no delay), financed:          Sharpe {b['sharpe']:.2f}, t={b['t']:.1f}")
    say(f"  With {PRIMARY_DELAY}-day confirmation, financed:    Sharpe {primary['sharpe']:.2f}, t={primary['t']:.1f}")
    if total_raw:
        say(f"  Flips filtered out by confirmation:     {total_raw - total_confirmed} of {total_raw} "
            f"({(total_raw - total_confirmed) / total_raw:.0%})")
    say()

    if edge >= 0.05:
        say("HELPS. Waiting for the flip to hold reduced whipsaw enough to")
        say("improve the financed Sharpe. Worth testing further -- one universe,")
        say("one period -- before trusting it the way the core signal has been.")
    elif edge > -0.05:
        say("NO REAL DIFFERENCE. Fewer, later trades roughly cancelled out --")
        say("what was saved in avoided whipsaws was given back in missed early")
        say("moves. Not worth the added complexity for this little.")
    else:
        say("HURTS. Consistent with the prior stated going in: this system's")
        say("edge depends more on catching trends early than avoiding the cost")
        say("of false starts. Left out of the live dashboard.")

    if failed:
        say()
        say(f"  Could not download: {', '.join(failed)}.")

    say()
    say("-" * 74)
    say("Saved to confirmation_delay_output.txt")
    say("-" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
