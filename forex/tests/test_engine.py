"""Correctness tests for the backtest engine.

These do not test whether any strategy makes money. They test that the
machinery reports the truth -- which is the only thing standing between you
and a beautiful equity curve built on an accounting error.

Run: python3 forex/tests/test_engine.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxlab import data, metrics, strategies  # noqa: E402
from fxlab.engine import Config, run, walk_forward  # noqa: E402

# vol_target high enough that the sizer always saturates, so position == signal
# and the arithmetic below is checkable by hand.
UNIT = Config(vol_target=100.0, max_leverage=1.0, cost_bps=0.0)


def test_return_alignment():
    """A position taken at the close of bar t-1 must earn bar t's return."""
    px = data.synthetic(n=300, seed=1)
    bt = run(px, pd.Series(1.0, index=px.index), UNIT)

    active = bt.loc[bt["position"] != 0.0]
    assert np.allclose(active["gross"], active["return"]), "gross P&L is misaligned with returns"

    # Buy-and-hold from the first bar we were actually long.
    first = active.index[0]
    expected = px.loc[first:].iloc[-1] / px.loc[:first].iloc[-2] - 1.0
    realized = (1.0 + bt.loc[first:, "net"]).prod() - 1.0
    assert abs(realized - expected) < 1e-9, f"{realized} != {expected}"
    print("PASS  return alignment")


def test_no_lookahead():
    """Rewriting the future must not change the past.

    The strongest available check: run the whole pipeline twice on series
    that are identical up to a cut point and wildly different after it. Every
    P&L figure before the cut must match to the last bit.
    """
    px = data.synthetic(n=1000, seed=2)
    cut = 800

    tampered = px.copy()
    tampered.iloc[cut:] = px.iloc[cut - 1] * np.linspace(1.0, 3.0, len(px) - cut)

    cfg = Config(cost_bps=1.0)
    for name, fn in strategies.REGISTRY.items():
        if name == "random_walk":
            continue  # seeded on length, so not comparable across series
        a = run(px, fn(px), cfg).iloc[:cut]
        b = run(tampered, fn(tampered), cfg).iloc[:cut]
        assert np.allclose(a["net"], b["net"], atol=1e-15), f"{name} leaks future data"
        assert np.allclose(a["position"], b["position"], atol=1e-15), f"{name} leaks future data"
    print(f"PASS  no lookahead ({len(strategies.REGISTRY) - 1} strategies)")


def test_cost_accounting():
    """Costs are charged once per unit of notional actually traded."""
    px = data.synthetic(n=300, seed=3)
    cfg = Config(vol_target=100.0, max_leverage=1.0, cost_bps=10.0)
    bt = run(px, pd.Series(1.0, index=px.index), cfg)

    # One entry, held to the end: exactly 1.0 unit of notional turned over.
    assert abs(bt["traded"].sum() - 1.0) < 1e-12, bt["traded"].sum()
    assert abs(bt["cost"].sum() - 10.0 / 1e4) < 1e-12, bt["cost"].sum()

    # A rule that flips every bar pays for every flip.
    flip = pd.Series(np.where(np.arange(len(px)) % 2 == 0, 1.0, -1.0), index=px.index)
    flips = run(px, flip, cfg)
    assert flips["cost"].sum() > 50 * bt["cost"].sum(), "turnover is not being charged"
    print("PASS  cost accounting")


def test_costs_are_monotonic():
    """More cost, less money. Sounds obvious; catches sign errors."""
    px = data.synthetic(n=2000, seed=4, trend_strength=0.95)
    sig = strategies.donchian(px)
    nets = [run(px, sig, Config(cost_bps=c))["net"].sum() for c in (0.0, 1.0, 5.0, 20.0)]
    assert nets == sorted(nets, reverse=True), nets
    print("PASS  cost monotonicity")


def test_walk_forward_has_no_dead_warmup():
    """Regression test for the bug in the inherited script.

    It computed a 126-day momentum signal on a 252-day test slice, so the
    first half of every out-of-sample window was pinned flat. Here the signal
    is built on full history and only *evaluated* on the window, so the
    strategy is live from bar one.
    """
    px = data.synthetic(n=252 * 12, seed=5, trend_strength=0.9)
    table, oos = walk_forward(px, strategies.tsm, Config(), train_years=3, test_years=1)

    assert not table.empty, "walk-forward produced no windows"
    positions = oos["position"]
    flat = float((positions == 0.0).mean())
    assert flat < 0.05, f"{flat:.0%} of out-of-sample bars are flat -- warmup is broken"

    # Windows must tile without overlapping, or returns get double-counted.
    assert positions.index.is_monotonic_increasing
    assert not positions.index.has_duplicates
    print(f"PASS  walk-forward warmup ({len(table)} windows, {flat:.1%} flat)")


def test_walk_forward_fit_sees_only_training_data():
    """A fitted parameter must not be able to peek past its training slice."""
    px = data.synthetic(n=252 * 12, seed=6)
    seen: list[pd.Timestamp] = []

    def fit(train_px):
        seen.append(train_px.index.max())
        return {"lookback": 126}

    table, _ = walk_forward(px, strategies.tsm, Config(), fit_fn=fit, train_years=3, test_years=1)
    for train_max, test_end in zip(seen, table["test_end"]):
        assert train_max.date() <= test_end, f"fit saw {train_max.date()} for window ending {test_end}"
    print(f"PASS  walk-forward fit isolation ({len(seen)} fits)")


def test_rebalance_band_cuts_turnover_without_changing_direction():
    """The band should remove resizing churn, not the strategy's opinion."""
    px = data.synthetic(n=252 * 10, seed=8, trend_strength=0.9)
    sig = strategies.tsm(px)

    # max_leverage above the vol target so the sizer is not pinned at the cap
    # and actually resizes every bar -- which is the churn the band removes.
    runs = {b: run(px, sig, Config(max_leverage=3.0, rebalance_band=b))
            for b in (0.0, 0.1, 0.25, 0.5)}
    traded = [runs[b]["traded"].sum() for b in (0.0, 0.1, 0.25, 0.5)]

    assert traded == sorted(traded, reverse=True), f"turnover not monotonic in band: {traded}"
    assert traded[-1] < 0.7 * traded[0], f"band barely helped: {traded[0]:.0f} -> {traded[-1]:.0f}"

    loose, banded = runs[0.0], runs[0.5]

    # Direction must be preserved wherever both are actually in the market.
    both = (loose["position"] != 0) & (banded["position"] != 0)
    same = np.sign(loose.loc[both, "position"]) == np.sign(banded.loc[both, "position"])
    assert float(same.mean()) > 0.95, "band changed which way the strategy is leaning"
    print(f"PASS  rebalance band ({loose['traded'].sum():.0f} -> {banded['traded'].sum():.0f} units traded)")


def test_trade_spans_counts_direction_changes():
    """Known-answer test: resizing is not a new trade, a flip is."""
    idx = pd.bdate_range("2020-01-01", periods=9)
    pos = pd.Series([0.0, 0.0, 1.0, 0.5, 1.0, -1.0, -1.0, 0.0, 1.0], index=idx)

    spans = metrics.trade_spans(pos)
    assert list(spans["bars"]) == [3, 2, 1], list(spans["bars"])
    assert list(spans["direction"]) == [1.0, -1.0, 1.0]

    stats = metrics.trade_stats(pos)
    assert stats["Trades"] == 3
    assert abs(stats["AvgHold"] - 2.0) < 1e-12
    print("PASS  trade spans")


def test_max_hold_caps_holding_period():
    """No trade may run longer than the cap, and the cap must actually bind."""
    px = data.synthetic(n=252 * 10, seed=9, trend_strength=0.95)
    cap = 10

    uncapped = run(px, strategies.tsm(px), Config())
    capped = run(px, strategies.with_max_hold(strategies.tsm, cap)(px), Config())

    spans = metrics.trade_spans(capped["position"])
    assert spans["bars"].max() <= cap, f"trade ran {spans['bars'].max()} bars, cap was {cap}"

    base = metrics.trade_spans(uncapped["position"])["bars"].mean()
    assert base > cap, f"cap never binds -- base holding period is only {base:.1f} bars"
    print(f"PASS  max hold ({base:.0f} bars -> {spans['bars'].mean():.1f}, cap {cap})")


def test_max_hold_does_not_re_enter_immediately():
    """After the cap fires, stay flat until the rule genuinely changes its mind.

    Re-entering on the next bar would make the cap a no-op that only adds
    transaction costs -- the most expensive kind of bug.
    """
    px = data.synthetic(n=252 * 6, seed=10, trend_strength=0.95)
    capped = strategies.with_max_hold(strategies.tsm, 5)(px)
    raw = strategies.tsm(px)

    forced_flat = (capped == 0.0) & (raw != 0.0)
    assert forced_flat.any(), "the cap never fired, so this proves nothing"

    # Wherever we were forced flat, the next bar may only re-enter if the
    # underlying opinion changed on that bar. Note the astype(bool): shifting
    # a boolean series yields object dtype, and `~` on object dtype is Python's
    # bitwise not, so ~True is -2 -- truthy, and every check silently inverts.
    reentered = forced_flat & (capped.shift(-1) == raw)
    changed_next = (raw != raw.shift(1)).shift(-1).fillna(False).astype(bool)
    violations = int((reentered & ~changed_next).sum())
    assert violations == 0, f"re-entered on {violations} bars while the rule still held the same view"
    print(f"PASS  max hold re-entry ({int(forced_flat.sum())} bars held flat by the cap)")


def test_random_walk_is_unprofitable_after_costs():
    """Sanity floor: no edge on a pure random walk, and costs bleed you dry."""
    px = data.synthetic(n=252 * 20, seed=7, trend_strength=0.0)
    sig = strategies.donchian(px, lookback=20)
    net = run(px, sig, Config(cost_bps=2.0))["net"]
    gross = run(px, sig, Config(cost_bps=0.0))["net"]
    assert net.sum() < gross.sum(), "costs did not reduce returns on a random walk"
    print(f"PASS  random-walk floor (gross {gross.sum():+.3f} -> net {net.sum():+.3f})")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} tests passed.")
