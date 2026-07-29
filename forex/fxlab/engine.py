"""Vectorized backtest engine with a single, centralized no-lookahead rule.

THE CONTRACT
------------
A strategy returns a `signal` series where `signal[t]` is the desired
direction decided **at the close of bar t**, using only data up to and
including bar t. The engine -- not the strategy -- applies the one-bar lag.

That is deliberate. In the inherited script the lag lived inside the
strategy code, which means every new strategy is a fresh chance to leak the
future. Here there is exactly one `.shift(1)`, in one place, covered by a
test.

RETURN CONVENTION
-----------------
`rets[t] = P[t]/P[t-1] - 1` is the return earned *over* bar t. A position
decided at the close of bar t-1 is what earns it. Hence:

    position_during_bar_t = target[t-1]
    pnl[t] = position_during_bar_t * rets[t] - cost of the trade that set it
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .metrics import TRADING_DAYS, summary


@dataclass(frozen=True)
class Config:
    """Execution and sizing assumptions.

    vol_target
        Annualized volatility the position sizer aims at. 0.10 = 10%/yr.
    vol_window
        Bars of realized volatility used for sizing.
    cost_bps
        ONE-WAY cost per unit of notional traded, in basis points. This has
        to cover half the spread plus commission plus slippage. For retail
        spot FX on EURUSD, 1.0 bp is an optimistic floor; on a 1-pip spread
        at 1.08 the half-spread alone is ~0.46 bp and most retail fills are
        worse. Crosses and exotics are several times that.
    max_leverage
        Cap on |position|. 1.0 means never more than the account notional.
    rebalance_band
        Don't trade until the target position drifts this far from what is
        already held, in units of notional. Volatility targeting otherwise
        nudges the position every single bar, and those nudges are pure cost:
        on a 126-day momentum rule that only changes its mind ~4 times a
        year, resizing churn can be half of all turnover. 0.0 rebalances
        every bar. Note the interaction with `max_leverage` -- if the cap
        binds most of the time the sizer is effectively switched off and
        there is no churn for a band to remove.
    carry_annual
        Optional annualized carry (rollover/swap) earned by a +1 position,
        as a decimal. Scalar or a series aligned to prices. Spot price
        series exclude the interest differential entirely, so leaving this
        at 0.0 backtests a strategy that is blind to a real P&L component.
    """

    vol_target: float = 0.10
    vol_window: int = 20
    cost_bps: float = 1.0
    max_leverage: float = 1.0
    rebalance_band: float = 0.0
    periods_per_year: int = TRADING_DAYS
    carry_annual: float | pd.Series = 0.0


def apply_rebalance_band(target: pd.Series, band: float) -> pd.Series:
    """Hold the current position until the target drifts more than `band` away."""
    if band <= 0.0:
        return target

    tgt = target.to_numpy(dtype=float)
    held = np.empty_like(tgt)
    current = 0.0
    for i in range(len(tgt)):
        want = tgt[i] if np.isfinite(tgt[i]) else 0.0
        if abs(want - current) > band:
            current = want
        held[i] = current
    return pd.Series(held, index=target.index)


def volatility_sizer(returns: pd.Series, cfg: Config) -> pd.Series:
    """Position scale that targets constant volatility, known at close of t."""
    realized = returns.rolling(cfg.vol_window).std(ddof=1) * np.sqrt(cfg.periods_per_year)
    scale = cfg.vol_target / realized.replace(0.0, np.nan)
    return scale.clip(upper=cfg.max_leverage).fillna(0.0)


def run(prices: pd.Series, signal: pd.Series, cfg: Config = Config()) -> pd.DataFrame:
    """Evaluate `signal` on `prices`. Returns a per-bar frame.

    `signal` must be aligned to `prices` and must not use data after its own
    timestamp; the engine handles the execution lag.
    """
    prices = prices.astype(float).dropna()
    signal = signal.reindex(prices.index).fillna(0.0).astype(float)

    rets = prices.pct_change()
    scale = volatility_sizer(rets, cfg)

    # What we want to be holding, decided at the close of each bar.
    target = (signal * scale).clip(-cfg.max_leverage, cfg.max_leverage)
    target = apply_rebalance_band(target, cfg.rebalance_band)

    # The one and only execution lag in this codebase.
    position = target.shift(1).fillna(0.0)

    traded = position.diff().abs().fillna(position.abs())
    cost = traded * (cfg.cost_bps / 1e4)

    carry = cfg.carry_annual
    if isinstance(carry, pd.Series):
        carry = carry.reindex(prices.index).fillna(0.0)
    carry_pnl = position * (carry / cfg.periods_per_year)

    gross = (position * rets).fillna(0.0)
    net = gross + carry_pnl - cost

    return pd.DataFrame(
        {
            "price": prices,
            "return": rets,
            "signal": signal,
            # What the rule wants to hold as of this bar's close. The live
            # runner reads the last value of THIS column -- `position` is the
            # same thing lagged, which is right for measuring P&L and wrong
            # for deciding what to do tonight.
            "target": target,
            "position": position,
            "traded": traded,
            "cost": cost,
            "gross": gross,
            "net": net,
            "equity": (1.0 + net).cumprod(),
        }
    )


def walk_forward(
    prices: pd.Series,
    signal_fn,
    cfg: Config = Config(),
    fit_fn=None,
    train_years: int = 3,
    test_years: int = 1,
    step_years: int = 1,
) -> tuple[pd.DataFrame, pd.Series]:
    """Rolling out-of-sample evaluation.

    Two things this fixes relative to the inherited implementation:

    1. WARMUP. The signal is computed on all history up to the end of the
       test window -- never on the test slice alone. The old version handed
       a 126-day momentum rule a 252-day slice, so the first 126 days of
       every "out-of-sample" window were forcibly flat. Roughly half of each
       window was measuring nothing at all.

    2. HONEST REFITTING. If `fit_fn` is supplied it sees only the training
       slice, and the parameters it returns are passed to `signal_fn` for
       that window. A parameter-free rule can leave it as None.

    Returns (per-window stats, stitched out-of-sample frame with `net` and
    `position` columns). The stitched frame is the one that matters: it is a
    single continuous track record with no window ever seeing its own future.
    """
    results: list[dict] = []
    oos_chunks: list[pd.DataFrame] = []

    start, end = prices.index.min(), prices.index.max()
    train_start = start

    while True:
        train_end = train_start + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if train_end >= end:
            break
        test_end = min(test_end, end)

        params = fit_fn(prices.loc[train_start:train_end]) if fit_fn else {}

        # History up to the end of the test window, and not one bar further.
        history = prices.loc[:test_end]
        bt = run(history, signal_fn(history, **params), cfg)

        window = bt.loc[bt.index > train_end]
        if len(window) > cfg.vol_window:
            stats = summary(window["net"], window["position"], cfg.periods_per_year)
            stats["train_end"] = train_end.date()
            stats["test_end"] = test_end.date()
            results.append(stats)
            oos_chunks.append(window[["net", "position"]])

        train_start += pd.DateOffset(years=step_years)

    if not results:
        return pd.DataFrame(), pd.DataFrame(columns=["net", "position"], dtype=float)

    cols = ["train_end", "test_end", "CAGR", "Vol", "Sharpe", "MaxDD", "HitRate", "Turnover", "Bars"]
    table = pd.DataFrame(results)[cols]
    stitched = pd.concat(oos_chunks).sort_index()
    return table, stitched[~stitched.index.duplicated(keep="first")]
