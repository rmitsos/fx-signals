"""Assert the JavaScript signal module matches the Python research kit.

There are two implementations of this strategy: `fxlab` (pandas, used to
decide whether the edge is real) and `src/lib/fx/strategy.js` (dependency
free, used to generate the signals you actually look at). Two copies of a
rule is normally a mistake, because the copy that drifts is invariably the
one making decisions.

This test is what makes the arrangement safe. It pushes identical prices
through both and requires the targets to match to 1e-12. If it fails, the
signals on the site are no longer the ones that were validated, and the
correct response is to fix the code, not to loosen the tolerance.

Run: python3 forex/tests/test_parity.py    (needs node on PATH)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fxlab import data, strategies  # noqa: E402
from fxlab.engine import Config, run  # noqa: E402

RUNNER = Path(__file__).resolve().parent / "parity_runner.mjs"
TOLERANCE = 1e-12

# Deliberately varied: a trending series, a pure random walk, a short series
# that barely clears the lookback, and a config with the cap switched off.
CASES = [
    ("trending", dict(n=1200, seed=1, trend_strength=0.95),
     dict(strategy="donchian", lookback=20, maxHold=10, rebalanceBand=0.25)),
    ("random walk", dict(n=1200, seed=2, trend_strength=0.0),
     dict(strategy="donchian", lookback=20, maxHold=10, rebalanceBand=0.25)),
    ("no cap", dict(n=800, seed=3, trend_strength=0.9),
     dict(strategy="donchian", lookback=55, maxHold=0, rebalanceBand=0.0)),
    ("tsm", dict(n=1000, seed=4, trend_strength=0.9),
     dict(strategy="tsm", lookback=126, maxHold=10, rebalanceBand=0.25)),
    ("short series", dict(n=60, seed=5),
     dict(strategy="donchian", lookback=20, maxHold=5, rebalanceBand=0.25)),
    ("unclipped sizer", dict(n=900, seed=6, trend_strength=0.9),
     dict(strategy="donchian", lookback=20, maxHold=10, rebalanceBand=0.1, maxLeverage=3.0)),
]

DEFAULTS = dict(volTarget=0.10, volWindow=20, maxLeverage=1.0)


def python_target(prices, cfg_js):
    """The same computation on the pandas side."""
    base = strategies.REGISTRY["tsm" if cfg_js["strategy"] == "tsm" else "donchian"]
    fn = partial(base, lookback=cfg_js["lookback"])
    fn.__name__ = cfg_js["strategy"]
    if cfg_js["maxHold"] > 0:
        fn = strategies.with_max_hold(fn, cfg_js["maxHold"])

    cfg = Config(
        vol_target=cfg_js["volTarget"],
        vol_window=cfg_js["volWindow"],
        max_leverage=cfg_js["maxLeverage"],
        rebalance_band=cfg_js["rebalanceBand"],
    )
    return run(prices, fn(prices), cfg)["target"].to_numpy()


def js_target(closes, cfg_js):
    proc = subprocess.run(
        ["node", str(RUNNER)],
        input=json.dumps({"closes": list(closes), "config": cfg_js}),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"parity_runner.mjs failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def standalone_target(closes, cfg_js):
    """The zero-dependency check_strategy.py, which is a THIRD copy of this.

    It exists so the strategy can be tested on a machine with nothing
    installed. That convenience is only safe if it computes the same thing,
    which is what this checks.
    """
    import importlib.util

    path = ROOT.parent / "check_strategy.py"  # repo root, not forex/
    spec = importlib.util.spec_from_file_location("check_strategy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Match the case's config rather than the module's own constants.
    mod.LOOKBACK = cfg_js["lookback"]
    mod.MAX_HOLD = cfg_js["maxHold"]
    mod.VOL_TARGET = cfg_js["volTarget"]
    mod.VOL_WINDOW = cfg_js["volWindow"]
    mod.MAX_LEVERAGE = cfg_js["maxLeverage"]
    mod.REBALANCE_BAND = cfg_js["rebalanceBand"]

    signal = mod.apply_max_hold(
        mod.donchian(list(closes), cfg_js["lookback"]), cfg_js["maxHold"]
    )
    return np.asarray(mod.build_targets(list(closes), signal), dtype=float)


def main():
    if shutil.which("node") is None:
        sys.exit("node is not on PATH; the parity test cannot run")

    failures = 0
    for name, series_kw, cfg in CASES:
        cfg_js = {**DEFAULTS, **cfg}
        prices = data.synthetic(**series_kw)

        expected = python_target(prices, cfg_js)
        actual = np.asarray(js_target(prices.to_numpy(), cfg_js)["target"], dtype=float)

        if len(expected) != len(actual):
            print(f"FAIL  {name}: length {len(actual)} != {len(expected)}")
            failures += 1
            continue

        diff = np.abs(expected - actual)
        worst = float(np.nanmax(diff))
        if worst > TOLERANCE:
            bad = int(np.argmax(diff))
            print(f"FAIL  {name}: worst diff {worst:.3e} at bar {bad} "
                  f"(python {expected[bad]:.9f}, js {actual[bad]:.9f})")
            failures += 1
        else:
            traded = int((np.diff(actual, prepend=0.0) != 0).sum())
            print(f"PASS  {name}: {len(actual)} bars, {traded} position changes, "
                  f"worst diff {worst:.1e}")

        # check_strategy.py only implements the donchian rule.
        if cfg_js["strategy"] != "donchian":
            continue
        standalone = standalone_target(prices.to_numpy(), cfg_js)
        sdiff = float(np.nanmax(np.abs(expected - standalone)))
        if sdiff > TOLERANCE:
            bad = int(np.argmax(np.abs(expected - standalone)))
            print(f"FAIL  {name} [check_strategy.py]: worst diff {sdiff:.3e} at bar {bad} "
                  f"(fxlab {expected[bad]:.9f}, standalone {standalone[bad]:.9f})")
            failures += 1
        else:
            print(f"  ok  {name} [check_strategy.py]: worst diff {sdiff:.1e}")

    if failures:
        sys.exit(f"\n{failures} of {len(CASES)} parity cases FAILED")
    print(f"\n{len(CASES)} parity cases passed. JS and Python agree to {TOLERANCE:.0e}.")


if __name__ == "__main__":
    main()
