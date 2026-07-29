"""Signal generators.

Every function returns a series where the value at bar t is the direction
decided **at the close of bar t** (+1 long, -1 short, 0 flat). None of them
apply an execution lag -- `engine.run` does that, once, for all of them.

The set is chosen to answer a specific question: of the things retail FX
traders actually do, which ones survive costs? `tsm` and `donchian` are the
two with published support. `fib_pullback` is here because it is what people
mean by "trading Fibonacci", and the only way to settle that argument is to
measure it. `random_walk` is the null: same turnover, no information.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def tsm(prices: pd.Series, lookback: int = 126) -> pd.Series:
    """Time-series momentum: sign of the return over the last `lookback` bars.

    The single best-documented effect in futures and FX (Moskowitz, Ooi &
    Pedersen 2012). Slow by construction -- a 126-day lookback trades a
    handful of times a year, which is exactly why it survives costs.
    """
    return np.sign(prices.pct_change(lookback)).fillna(0.0)


def ma_cross(prices: pd.Series, fast: int = 20, slow: int = 100) -> pd.Series:
    """Long while the fast moving average is above the slow one."""
    f = prices.rolling(fast).mean()
    s = prices.rolling(slow).mean()
    return np.sign(f - s).fillna(0.0)


def donchian(prices: pd.Series, lookback: int = 55) -> pd.Series:
    """Channel breakout: flip long on a new `lookback`-bar high, short on a low.

    Holds the last position between breakouts, which is what makes it a
    trend follower rather than a series of one-bar bets. This is the
    testable form of "trading breakouts".
    """
    prior = prices.shift(1)
    upper = prior.rolling(lookback).max()
    lower = prior.rolling(lookback).min()

    raw = pd.Series(np.nan, index=prices.index, dtype=float)
    raw[prices > upper] = 1.0
    raw[prices < lower] = -1.0
    return raw.ffill().fillna(0.0)


def fib_pullback(
    prices: pd.Series,
    swing: int = 40,
    trend: int = 120,
    entry_zone: tuple[float, float] = (0.5, 0.786),
) -> pd.Series:
    """Buy the "golden pocket" retracement in the direction of the trend.

    The rule most people mean when they say they trade Fibonacci:

      - trend is up while price is above its `trend`-bar moving average;
      - the swing is the high and low of the last `swing` bars;
      - enter long when price pulls back into the 50%-78.6% retracement of
        that swing;
      - exit at the swing high (target) or the swing low (stop).

    Shorts are the mirror image. Stateful, so this walks the series bar by
    bar -- but it still only ever looks at bars at or before the current one.

    Implemented so the claim can be measured rather than argued about. The
    retracement levels are the interesting part: if 61.8% carries real
    information, this should beat the same structure with arbitrary levels,
    and you can check that by changing `entry_zone`.
    """
    lo_frac, hi_frac = entry_zone
    ma = prices.rolling(trend).mean()
    swing_hi = prices.rolling(swing).max()
    swing_lo = prices.rolling(swing).min()

    out = np.zeros(len(prices), dtype=float)
    px = prices.to_numpy()
    ma_a, hi_a, lo_a = ma.to_numpy(), swing_hi.to_numpy(), swing_lo.to_numpy()

    state = 0.0
    entry_hi = entry_lo = np.nan

    for i in range(len(px)):
        p, m, hi, lo = px[i], ma_a[i], hi_a[i], lo_a[i]
        if not (np.isfinite(m) and np.isfinite(hi) and np.isfinite(lo)) or hi <= lo:
            out[i] = state
            continue

        if state > 0:  # long: take profit at the swing high, stop at the low
            if p >= entry_hi or p <= entry_lo:
                state = 0.0
        elif state < 0:
            if p <= entry_lo or p >= entry_hi:
                state = 0.0

        if state == 0.0:
            span = hi - lo
            if p > m:  # uptrend -- look for a pullback from the high
                zone_hi = hi - lo_frac * span
                zone_lo = hi - hi_frac * span
                if zone_lo <= p <= zone_hi:
                    state, entry_hi, entry_lo = 1.0, hi, lo
            elif p < m:  # downtrend -- look for a bounce toward the high
                zone_lo = lo + lo_frac * span
                zone_hi = lo + hi_frac * span
                if zone_lo <= p <= zone_hi:
                    state, entry_hi, entry_lo = -1.0, hi, lo

        out[i] = state

    return pd.Series(out, index=prices.index)


def random_walk(prices: pd.Series, flip_every: int = 55, seed: int = 0) -> pd.Series:
    """Null hypothesis: coin flips held for `flip_every` bars.

    Run this alongside anything else. A strategy that cannot beat a coin at
    matched turnover has not demonstrated anything.
    """
    rng = np.random.default_rng(seed)
    n_flips = len(prices) // max(flip_every, 1) + 1
    flips = rng.choice([-1.0, 1.0], size=n_flips)
    return pd.Series(np.repeat(flips, flip_every)[: len(prices)], index=prices.index)


def with_max_hold(fn, max_bars: int):
    """Force a strategy flat after `max_bars` bars in the same direction.

    Holding period is normally an *output* -- a 126-day momentum rule holds
    for months because that is how often it changes its mind. This makes it
    an input, so a target horizon (5-10 bars for a one-to-two week system)
    can be tested directly rather than hoped for.

    Once the cap fires, the position stays flat until the underlying rule
    actually changes its opinion. Re-entering the next bar would make the cap
    a no-op with extra transaction costs.

    Be honest about what this is: a constraint that can only cost you gross
    return, since it cuts winners at an arbitrary bar count. It earns its
    place only if the shorter horizon buys something back -- lower drawdown,
    or capital freed for another pair. The backtest will tell you which.
    """

    def wrapped(prices: pd.Series, **kwargs) -> pd.Series:
        raw = fn(prices, **kwargs).to_numpy(dtype=float)
        out = np.zeros(len(raw))

        current, last_opinion, held = 0.0, None, 0
        for i, opinion in enumerate(raw):
            if opinion != last_opinion:  # the rule changed its mind: new trade
                last_opinion, current, held = opinion, opinion, 0
            if current != 0.0:
                held += 1
                if held > max_bars:
                    current = 0.0
            out[i] = current
        return pd.Series(out, index=prices.index)

    wrapped.__name__ = f"{fn.__name__}_max{max_bars}"
    return wrapped


REGISTRY = {
    "tsm": tsm,
    "ma_cross": ma_cross,
    "donchian": donchian,
    "fib_pullback": fib_pullback,
    "random_walk": random_walk,
}
