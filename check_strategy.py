#!/usr/bin/env python3
"""
Does this strategy actually work? Run this to find out.

    python3 check_strategy.py

That is the whole thing. It needs nothing installed -- no pandas, no numpy,
no pip. It downloads ~20 years of daily FX prices, tests the rule against
them, compares it to random coin flips, and tells you in plain English
whether there is anything here.

It places no trades, connects to no broker, and asks for no credentials.

The result is printed on screen and saved to strategy_check_output.txt.

--- WHAT IT TESTS -------------------------------------------------------

A 20-day breakout rule: go long when the price closes above its highest
level of the last 20 days, short when it closes below the lowest, and hold
for at most 10 days. Position size is scaled so each pair contributes about
the same amount of risk, and never exceeds the account size.

--- WHY THE COIN FLIP MATTERS -------------------------------------------

Any rule will look profitable on some data by luck. So the same test is run
on random coin flips, forced to trade at the same frequency. If the rule
cannot beat a coin, it has demonstrated nothing, however good its numbers
look on their own.

--- WHY THE COST SWEEP MATTERS ------------------------------------------

Every trade pays the spread. The test is repeated at several cost levels so
you can see where the edge dies. If it dies below what your broker actually
charges you, the strategy does not exist in the real world.
"""

import argparse
import json
import math
import random
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

TRADING_DAYS = 252

# The strategy. These are the settings, and they are deliberately not
# tuneable from the command line -- searching for the parameters that look
# best on the data you already have is the single most reliable way to fool
# yourself in this field.
LOOKBACK = 20        # breakout channel length, in trading days
MAX_HOLD = 10        # force flat after this many days -- the 1-2 week horizon
VOL_TARGET = 0.10    # aim for 10% annualised volatility
VOL_WINDOW = 20      # days of history used to measure volatility
MAX_LEVERAGE = 1.0   # never hold more than the account size
REBALANCE_BAND = 0.25  # ignore small resizes; they are pure cost

PAIRS = ["eurusd", "gbpusd", "usdjpy", "audusd", "usdchf", "usdcad"]
COST_LEVELS = [0.0, 1.0, 3.0, 10.0]  # one-way cost per trade, in basis points

WARMUP = max(LOOKBACK, VOL_WINDOW) + 60


# --------------------------------------------------------------------- data

def fetch(symbol):
    """Daily closes, trying each free source in turn.

    Neither source needs an account or a key. Two of them because both
    occasionally refuse traffic from data centres and from corporate
    networks, and a single refusal should not end the test.
    """
    problems = []
    for name, source in (("stooq", _from_stooq), ("yahoo", _from_yahoo)):
        try:
            dates, closes = source(symbol)
            if len(closes) >= WARMUP + TRADING_DAYS:
                return dates, closes
            problems.append(f"{name}: only {len(closes)} days")
        except Exception as exc:  # noqa: BLE001 -- try the next source
            problems.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(problems))


def _from_yahoo(symbol):
    """Daily closes from Yahoo's chart endpoint. JSON, no key."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}=X"
           "?range=20y&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    results = (payload.get("chart") or {}).get("result")
    if not results:
        raise RuntimeError("no data in response")
    stamps = results[0].get("timestamp") or []
    quotes = ((results[0].get("indicators") or {}).get("quote") or [{}])[0]
    values = quotes.get("close") or []

    dates, closes = [], []
    for stamp, close in zip(stamps, values):
        if close is None or close <= 0:
            continue
        dates.append(datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d"))
        closes.append(float(close))
    if not closes:
        raise RuntimeError("response contained no usable prices")
    return dates, closes


def _from_stooq(symbol):
    """Daily closes from stooq.com. Plain CSV, no key."""
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8", "replace")

    lines = text.strip().split("\n")
    if not lines or not lines[0].lower().startswith("date"):
        raise RuntimeError(f"no data returned (got: {text[:80]!r})")

    cols = lines[0].lower().split(",")
    ci = cols.index("close")

    dates, closes = [], []
    for line in lines[1:]:
        parts = line.split(",")
        try:
            close = float(parts[ci])
        except (ValueError, IndexError):
            continue
        if close > 0:
            dates.append(parts[0])
            closes.append(close)
    if not closes:
        raise RuntimeError("file downloaded but contained no usable prices")
    return dates, closes


# ----------------------------------------------------------------- strategy

def donchian(closes, lookback):
    """+1 after a new N-day high, -1 after a new N-day low, hold in between."""
    signal = [0.0] * len(closes)
    last = 0.0
    for i in range(len(closes)):
        if i >= lookback:
            window = closes[i - lookback:i]
            if closes[i] > max(window):
                last = 1.0
            elif closes[i] < min(window):
                last = -1.0
        signal[i] = last
    return signal


def apply_max_hold(signal, max_bars):
    """Force flat after max_bars, and stay flat until the rule changes its mind.

    Re-entering the next day would make the cap pointless and pay the spread
    for the privilege.
    """
    out = [0.0] * len(signal)
    current, last_opinion, held = 0.0, None, 0
    for i, opinion in enumerate(signal):
        if opinion != last_opinion:
            last_opinion, current, held = opinion, opinion, 0
        if current != 0.0:
            held += 1
            if max_bars > 0 and held > max_bars:
                current = 0.0
        out[i] = current
    return out


def returns_of(closes):
    return [None] + [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]


def realized_vol(rets, window):
    """Annualised volatility over a trailing window."""
    out = [None] * len(rets)
    for i in range(window, len(rets)):
        chunk = rets[i - window + 1:i + 1]
        if any(r is None for r in chunk):
            continue
        out[i] = statistics.stdev(chunk) * math.sqrt(TRADING_DAYS)
    return out


def build_targets(closes, signal):
    """Turn a direction into a position size, then damp the small changes."""
    rets = returns_of(closes)
    vol = realized_vol(rets, VOL_WINDOW)

    raw = []
    for i in range(len(closes)):
        v = vol[i]
        scale = 0.0 if not v else min(VOL_TARGET / v, MAX_LEVERAGE)
        raw.append(max(-MAX_LEVERAGE, min(MAX_LEVERAGE, signal[i] * scale)))

    held, current = [], 0.0
    for want in raw:
        if abs(want - current) > REBALANCE_BAND:
            current = want
        held.append(current)
    return held


def coin_flip(closes, flip_every, seed):
    """The null hypothesis: random directions, held for the same length."""
    rng = random.Random(seed)
    signal, current, held = [], 0.0, 0
    for _ in closes:
        if held <= 0:
            current = rng.choice([-1.0, 1.0])
            held = max(1, flip_every)
        held -= 1
        signal.append(current)
    return signal


# ------------------------------------------------------------------ scoring

def evaluate(closes, targets, cost_bps):
    """Daily net returns. A position taken at yesterday's close earns today."""
    rets = returns_of(closes)
    nets, prev_position = [], 0.0
    for i in range(1, len(closes)):
        position = targets[i - 1]
        traded = abs(position - prev_position)
        nets.append(position * rets[i] - traded * cost_bps / 1e4)
        prev_position = position
    return [None] + nets


def holding_periods(targets):
    spans, run = [], 0
    for i, t in enumerate(targets):
        same = i > 0 and (t > 0) == (targets[i - 1] > 0) and (t < 0) == (targets[i - 1] < 0)
        if t != 0 and same:
            run += 1
        else:
            if run:
                spans.append(run)
            run = 1 if t != 0 else 0
    if run:
        spans.append(run)
    return spans


def score(nets):
    """Sharpe, return, worst drawdown, and a t-stat for 'is this luck?'."""
    r = [x for x in nets if x is not None]
    if len(r) < 30:
        return None

    mean, sd = statistics.fmean(r), statistics.stdev(r)
    sharpe = (mean / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else 0.0
    t_stat = (mean / sd * math.sqrt(len(r))) if sd > 0 else 0.0

    equity, peak, worst = 1.0, 1.0, 0.0
    for x in r:
        equity *= (1.0 + x)
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)

    years = len(r) / TRADING_DAYS
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0 and years > 0 else -1.0
    return {"sharpe": sharpe, "cagr": cagr, "drawdown": worst,
            "t": t_stat, "days": len(r)}


# ------------------------------------------------------------------- report

class Tee:
    """Print to the screen and to a file at the same time."""

    def __init__(self, path):
        self.file = open(path, "w", encoding="utf-8")

    def __call__(self, line=""):
        print(line)
        self.file.write(line + "\n")
        self.file.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="strategy_check_output.txt")
    args = ap.parse_args()

    say = Tee(args.out)
    say("=" * 70)
    say("  DOES THE STRATEGY WORK? -- honest test, out of sample")
    say("=" * 70)
    say()
    say(f"Rule: {LOOKBACK}-day breakout, held at most {MAX_HOLD} days,")
    say(f"      sized to {VOL_TARGET:.0%} volatility, never above account size.")
    say()

    # ---- download -----------------------------------------------------
    say("Downloading prices...")
    data, failed = {}, []
    for symbol in PAIRS:
        try:
            dates, closes = fetch(symbol)
            data[symbol] = (dates, closes)
            say(f"  {symbol.upper()}  {len(closes):>5} days  "
                f"{dates[0]} to {dates[-1]}")
        except Exception as exc:  # noqa: BLE001 -- report, never crash
            failed.append(symbol)
            say(f"  {symbol.upper()}  FAILED: {exc}")

    if not data:
        say()
        say("Could not download any prices, so nothing could be tested.")
        say("Usually this means no internet, or stooq.com is blocking you.")
        say("Send me this file and I will give you another way in.")
        return 1

    say()

    # ---- per-pair, at a realistic cost --------------------------------
    strategy_targets, flip_targets, all_spans = {}, {}, []
    for symbol, (_, closes) in data.items():
        signal = apply_max_hold(donchian(closes, LOOKBACK), MAX_HOLD)
        targets = build_targets(closes, signal)
        strategy_targets[symbol] = targets
        all_spans.extend(holding_periods(targets))

    typical_hold = round(statistics.fmean(all_spans)) if all_spans else MAX_HOLD
    for i, (symbol, (_, closes)) in enumerate(data.items()):
        flip_targets[symbol] = build_targets(
            closes, coin_flip(closes, typical_hold, seed=1000 + i))

    say(f"Average holding period: {typical_hold} days "
        f"({typical_hold / 5:.1f} weeks) -- the horizon you asked for.")
    say()
    say("-" * 70)
    say("EACH PAIR (at 1 bp cost, roughly a 1-pip spread)")
    say("-" * 70)
    say(f"{'pair':<10}{'strategy':>10}{'coin flip':>12}{'return/yr':>12}{'worst fall':>12}")

    for symbol in data:
        closes = data[symbol][1]
        # Skip the warmup, where the rule has no channel yet and is stuck flat.
        s = score(evaluate(closes, strategy_targets[symbol], 1.0)[WARMUP:])
        c = score(evaluate(closes, flip_targets[symbol], 1.0)[WARMUP:])
        if not s or not c:
            continue
        say(f"{symbol.upper():<10}{s['sharpe']:>10.2f}{c['sharpe']:>12.2f}"
            f"{s['cagr']:>11.1%}{s['drawdown']:>12.1%}")

    # ---- the portfolio, swept across costs ----------------------------
    say()
    say("-" * 70)
    say("ALL PAIRS TOGETHER, AT DIFFERENT COST LEVELS")
    say("-" * 70)
    say("(trading all pairs at once is the honest way to run this -- one pair")
    say(" alone is mostly noise)")
    say()
    say(f"{'cost':<22}{'strategy':>10}{'coin flip':>12}{'return/yr':>12}{'worst fall':>12}")

    portfolio_by_cost, portfolio_daily = {}, {}
    for cost in COST_LEVELS:
        combined = portfolio_series(data, strategy_targets, cost)
        flipped = portfolio_series(data, flip_targets, cost)
        ps = score([r for _, r in combined])
        pf = score([r for _, r in flipped])
        if not ps or not pf:
            continue
        portfolio_daily[cost] = combined
        portfolio_by_cost[cost] = (ps, pf)
        label = "free (impossible)" if cost == 0 else f"{cost:g} bp per trade"
        say(f"{label:<22}{ps['sharpe']:>10.2f}{pf['sharpe']:>12.2f}"
            f"{ps['cagr']:>11.1%}{ps['drawdown']:>12.1%}")

    # ---- year by year -------------------------------------------------
    say()
    say("-" * 70)
    say("YEAR BY YEAR (all pairs, 1 bp cost)")
    say("-" * 70)
    say("A rule that works should not depend on one lucky year.")
    say()

    by_year = defaultdict(list)
    for day, ret in portfolio_daily.get(1.0, []):
        by_year[day[:4]].append(ret)

    good, years, yearly = 0, sorted(by_year), {}
    for year in years:
        total = 1.0
        for x in by_year[year]:
            total *= (1.0 + x)
        yearly[year] = total - 1.0

    # Scale the bars to the biggest year so they stay readable whatever the
    # size of the returns.
    biggest = max((abs(v) for v in yearly.values()), default=0.0) or 1.0
    for year in years:
        pnl = yearly[year]
        good += pnl > 0
        bar = "#" * max(1, round(abs(pnl) / biggest * 26))
        say(f"  {year}  {pnl:>7.1%}  {'' if pnl >= 0 else '-'}{bar}")

    if years:
        say()
        say(f"  Profitable in {good} of {len(years)} years.")

    # ---- verdict ------------------------------------------------------
    say()
    say("=" * 70)
    say("  WHAT THIS MEANS")
    say("=" * 70)
    say()

    realistic = portfolio_by_cost.get(1.0) or portfolio_by_cost.get(3.0)
    if not realistic:
        say("Not enough data came back to reach a conclusion.")
        return 1

    strat, flip = realistic
    edge = strat["sharpe"] - flip["sharpe"]

    if strat["sharpe"] >= 0.4 and strat["t"] >= 2.0 and edge >= 0.3:
        say("PROMISING. The rule beat the coin flip by a clear margin and the")
        say("result is unlikely to be luck. That does NOT mean it will make")
        say("money in future -- it means it has earned the next test rather")
        say("than being thrown away.")
    elif strat["sharpe"] >= 0.2 and edge >= 0.15:
        say("WEAK BUT NOT NOTHING. There is a hint of an edge, too small to")
        say("be confident about. This is the most common honest outcome. It")
        say("is not a green light to fund an account.")
    else:
        say("NO EDGE FOUND. The rule did not meaningfully beat random coin")
        say("flips once costs were paid. That is a real answer and a valuable")
        say("one -- it just saved you an account.")

    say()
    say(f"  Strategy Sharpe:  {strat['sharpe']:.2f}   "
        f"(above 0.4 is a business; below 0.2 is noise)")
    say(f"  Coin flip Sharpe: {flip['sharpe']:.2f}")
    say(f"  Is it luck?       t = {strat['t']:.1f}   "
        f"(needs to be above 2 to be taken seriously)")
    say(f"  Worst fall:       {strat['drawdown']:.1%}   "
        "(you would have had to sit through this)")
    say()
    say("  Ignore how small the return looks. Six pairs each held about a")
    say("  third of the time averages out to a very quiet account, and size")
    say("  can be scaled up later. Sharpe is the number that cannot be")
    say("  scaled -- it is the quality of the edge, and no amount of")
    say("  leverage improves it. Leverage multiplies the losses just as")
    say("  faithfully.")

    zero = portfolio_by_cost.get(0.0)
    if zero and zero[0]["sharpe"] > 0.2:
        died = [c for c, (s, _) in sorted(portfolio_by_cost.items()) if s["sharpe"] < 0.2]
        if died:
            say(f"  Edge dies at:     {died[0]:g} bp of cost per trade")
            say("                    (if your broker charges more than that,")
            say("                     the strategy does not exist for you)")

    if failed:
        say()
        say(f"  Note: {', '.join(p.upper() for p in failed)} could not be "
            "downloaded, so this is based on fewer pairs than intended.")

    say()
    say("-" * 70)
    say(f"Saved to {args.out} -- send me that file and I will read it properly.")
    say("-" * 70)
    return 0


def portfolio_series(data, targets_by_symbol, cost_bps):
    """Equal-weight portfolio, aligned by calendar date.

    Holding six pairs at once means six returns on the same day, so they are
    averaged -- not added. Adding them would treat one day of six positions
    as six days of one, which inflates the result roughly sixfold. The pairs
    also start on different dates, so alignment has to be by date rather than
    by position in the list.

    Returns [(date, return), ...] sorted by date.
    """
    daily = defaultdict(list)
    for symbol, (dates, closes) in data.items():
        nets = evaluate(closes, targets_by_symbol[symbol], cost_bps)
        for i in range(WARMUP, len(nets)):
            if nets[i] is not None:
                daily[dates[i]].append(nets[i])
    return [(d, statistics.fmean(v)) for d, v in sorted(daily.items())]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(1)
