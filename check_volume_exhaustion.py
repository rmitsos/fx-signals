#!/usr/bin/env python3
"""
Does watching volume for "lost interest" improve the trend rule?

    python3 check_volume_exhaustion.py

Tested on exactly the five OANDA-tradeable instruments where Yahoo's volume
figure is real, exchange-reported futures volume rather than a proxy or a
zero: gold, silver, WTI crude, Brent crude, natural gas. FX (spot trading has
no consolidated volume at all -- there is no single tape) and the five equity
indices (Yahoo reports zero or unreliable volume for index-level tickers) are
structurally excluded here, not left out because they tested badly. There is
no real volume number to test them with.

THE IDEA: while a position is held, compare its own trailing 20-day average
volume against its own trailing 100-day average. If recent volume has fallen
more than a pre-specified threshold below that baseline -- meaningfully fewer
contracts trading than usual, while the position is still open -- force flat,
on the theory that a trend running out of participants is exhausted before
price itself says so.

PRE-SPECIFIED: 20/100-day windows and a 70% threshold, fixed before this ran
once, for the same reason the momentum lookback was never tuned on this data
-- searching parameters until one looks good is how backtests get fooled. A
sweep across nearby thresholds (60/70/80/90%) is reported as a robustness
check, not as a menu to quietly pick the best number from afterwards.

Same signal, same costs, same admin-fee model as check_universe_oanda.py, so
this is a direct, apples-to-apples comparison against the no-exhaustion
baseline it is judged against.

It places no trades and connects to no broker.
"""

import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_strategy import Tee, score  # noqa: E402
import check_universe as cu  # noqa: E402
import check_universe_oanda as cuo  # noqa: E402

SHORT_WINDOW = 20
LONG_WINDOW = 100
THRESHOLDS = [0.90, 0.80, 0.70, 0.60]
PRIMARY_THRESHOLD = 0.70

# Metals and energy are exactly the OANDA-confirmed instruments that are
# real futures contracts with real reported volume -- filtering
# check_universe_oanda's own 14-instrument list rather than redefining it,
# so this can never silently drift from what the live dashboard trades.
VOLUME_UNIVERSE = [row for row in cuo.OANDA_UNIVERSE if row[2] in ("metals", "energy")]


def fetch_with_volume(ticker):
    """Daily closes and volume from Yahoo's chart endpoint, aligned by index."""
    quoted = urllib.parse.quote(ticker, safe="")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{quoted}"
           "?range=25y&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    results = (payload.get("chart") or {}).get("result")
    if not results:
        raise RuntimeError("no data in response")
    stamps = results[0].get("timestamp") or []
    quote = ((results[0].get("indicators") or {}).get("quote") or [{}])[0]
    closes_raw = quote.get("close") or []
    volumes_raw = quote.get("volume") or []

    dates, closes, volumes = [], [], []
    for i, stamp in enumerate(stamps):
        close = closes_raw[i] if i < len(closes_raw) else None
        if close is None or close <= 0:
            continue
        vol = volumes_raw[i] if i < len(volumes_raw) else None
        dates.append(datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d"))
        closes.append(float(close))
        volumes.append(float(vol) if vol is not None and vol > 0 else 0.0)

    if len(closes) < cu.WARMUP + LONG_WINDOW:
        raise RuntimeError(f"only {len(closes)} days of history")
    return dates, closes, volumes


def volume_ratio(volumes):
    """Trailing 20-day average volume / trailing 100-day average.

    Below 1 means recently quieter than usual; the exhaustion overlay only
    cares about how far below.
    """
    out = [None] * len(volumes)
    for i in range(LONG_WINDOW - 1, len(volumes)):
        short_avg = statistics.fmean(volumes[i - SHORT_WINDOW + 1:i + 1])
        long_avg = statistics.fmean(volumes[i - LONG_WINDOW + 1:i + 1])
        out[i] = (short_avg / long_avg) if long_avg > 0 else None
    return out


def apply_exhaustion(signal, vratio, threshold):
    """Force flat on any day a position is held but recent volume has fallen
    below `threshold` of its own 100-day average. Memoryless by design: a
    day where volume recovers above the threshold returns straight to
    whatever the momentum signal says, with no added "stay flat until the
    trend reverses" debouncing -- that would be a second, untested idea
    layered on top of the first.
    """
    out = []
    for s, vr in zip(signal, vratio):
        if s != 0 and vr is not None and vr < threshold:
            out.append(0.0)
        else:
            out.append(s)
    return out


def fraction_exhausted(signal, exhausted_signal):
    held_days = sum(1 for s in signal if s != 0)
    forced_flat = sum(1 for s, e in zip(signal, exhausted_signal) if s != 0 and e == 0)
    return (forced_flat / held_days) if held_days else 0.0


def main():
    say = Tee("volume_exhaustion_output.txt")
    say("=" * 74)
    say("  DOES A VOLUME-EXHAUSTION OVERLAY IMPROVE THE TREND RULE?")
    say("=" * 74)
    say()
    say(f"{len(VOLUME_UNIVERSE)} instruments -- the only OANDA-tradeable ones where")
    say("Yahoo's volume figure is real exchange volume, not a zero or an FX proxy:")
    say("  " + ", ".join(n for n, _, _ in VOLUME_UNIVERSE))
    say()
    say("Downloading ~25 years of daily prices and volume...")

    data, failed = {}, []
    for name, ticker, klass in VOLUME_UNIVERSE:
        try:
            dates, closes, volumes = fetch_with_volume(ticker)
            data[name] = (dates, closes, volumes, klass)
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            say(f"  {name:<14} FAILED: {exc}")
    say(f"  {len(data)} of {len(VOLUME_UNIVERSE)} instruments loaded.")
    if not data:
        say("Nothing downloaded; cannot draw any conclusion.")
        return 1
    say()

    # ---- signals: baseline vs exhaustion at each threshold ----------------
    base_signal, base_targets, vratios = {}, {}, {}
    for name, (_, closes, volumes, _) in data.items():
        sig = cu.tsm(closes, cu.LOOKBACK)
        base_signal[name] = sig
        base_targets[name] = cu.targets_for(closes, sig)
        vratios[name] = volume_ratio(volumes)

    exhaustion_signal = {t: {} for t in THRESHOLDS}
    exhaustion_targets = {t: {} for t in THRESHOLDS}
    for name, (_, closes, _, _) in data.items():
        for t in THRESHOLDS:
            sig = apply_exhaustion(base_signal[name], vratios[name], t)
            exhaustion_signal[t][name] = sig
            exhaustion_targets[t][name] = cu.targets_for(closes, sig)

    say("-" * 74)
    say("HOW OFTEN DOES THE OVERLAY ACTUALLY FIRE? (share of held days forced flat)")
    say("-" * 74)
    say(f"{'instrument':<16}" + "".join(f"{f'ratio<{t:.0%}':>14}" for t in THRESHOLDS))
    for name in data:
        row = f"{name:<16}"
        for t in THRESHOLDS:
            frac = fraction_exhausted(base_signal[name], exhaustion_signal[t][name])
            row += f"{frac:>14.1%}"
        say(row)
    say()

    # ---- head-to-head: baseline vs each threshold, financed ----------------
    say("-" * 74)
    say("FINANCED PORTFOLIO (2bp cost), BASELINE VS EXHAUSTION OVERLAY")
    say("-" * 74)
    say(f"{'version':<30}{'sharpe':>9}{'t':>7}{'return/yr':>12}{'worst fall':>12}")

    sub_data = {n: (data[n][0], data[n][1], data[n][3]) for n in data}

    baseline_series = cu.financed_portfolio(sub_data, base_targets, 2.0)
    b = score([r for _, r in baseline_series])
    if b:
        say(f"{'baseline (no exhaustion)':<30}{b['sharpe']:>9.2f}{b['t']:>7.1f}"
            f"{b['cagr']:>11.1%}{b['drawdown']:>12.1%}")

    results = {}
    for t in THRESHOLDS:
        series = cu.financed_portfolio(sub_data, exhaustion_targets[t], 2.0)
        s = score([r for _, r in series])
        results[t] = s
        if s:
            tag = "  <- PRIMARY" if t == PRIMARY_THRESHOLD else ""
            say(f"{f'exhaustion, ratio<{t:.0%}':<30}{s['sharpe']:>9.2f}{s['t']:>7.1f}"
                f"{s['cagr']:>11.1%}{s['drawdown']:>12.1%}{tag}")

    # ---- by asset class, at the primary threshold --------------------------
    say()
    say("-" * 74)
    say(f"BY ASSET CLASS, FINANCED (primary threshold: ratio < {PRIMARY_THRESHOLD:.0%})")
    say("-" * 74)
    classes = defaultdict(list)
    for name, (_, _, _, klass) in data.items():
        classes[klass].append(name)

    for klass, names in classes.items():
        class_data = {n: sub_data[n] for n in names}
        base_class = cu.financed_portfolio(class_data, {n: base_targets[n] for n in names}, 2.0)
        exh_class = cu.financed_portfolio(
            class_data, {n: exhaustion_targets[PRIMARY_THRESHOLD][n] for n in names}, 2.0)
        sb, se = score([r for _, r in base_class]), score([r for _, r in exh_class])
        if sb and se:
            say(f"{klass:<12} baseline Sharpe {sb['sharpe']:>6.2f}   "
                f"with exhaustion {se['sharpe']:>6.2f}")

    # ---- verdict -------------------------------------------------------------
    say()
    say("=" * 74)
    say("  WHAT THIS MEANS")
    say("=" * 74)
    say()

    primary = results.get(PRIMARY_THRESHOLD)
    if not b or not primary:
        say("Not enough data to conclude.")
        return 1

    edge = primary["sharpe"] - b["sharpe"]
    say(f"  Baseline (no exhaustion), financed:        Sharpe {b['sharpe']:.2f}, t={b['t']:.1f}")
    say(f"  With exhaustion overlay (ratio<{PRIMARY_THRESHOLD:.0%}), financed: "
        f"Sharpe {primary['sharpe']:.2f}, t={primary['t']:.1f}")
    say()

    if edge >= 0.05:
        say("HELPS, ON THIS SLICE. The overlay improved the financed Sharpe on")
        say("exactly the five instruments it could be tested on. Small sample")
        say("(5 instruments, two asset classes) -- worth watching further before")
        say("trusting it the way the core 252-day signal has been.")
    elif edge > -0.05:
        say("NO REAL DIFFERENCE. The overlay neither clearly helped nor clearly")
        say("hurt here -- essentially noise. Not worth the added complexity of a")
        say("second rule that can fire independently of price, for this little.")
    else:
        say("HURTS. Forcing flat on quiet volume cost more in whipsaw and missed")
        say("continuation than it saved by avoiding a real reversal. Consistent")
        say("with the broader trend-following literature, where exit-timing")
        say("overlays usually add cost rather than edge. Left out of the live")
        say("dashboard.")

    if failed:
        say()
        say(f"  Could not download: {', '.join(failed)}.")

    say()
    say("-" * 74)
    say("Saved to volume_exhaustion_output.txt")
    say("-" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
