"""Assert the JS momentum strategy (used by the universe dashboard) matches
check_universe.py's Python -- both the position it takes and the daily P&L,
gross and after OANDA's financing.

This is the same discipline as test_parity.py, extended to a second live
implementation: src/lib/fx/strategy.js now runs a `tsm` (252-day momentum, no
holding cap) path for the /fx-signals dashboard, alongside the `donchian`
path already checked by test_parity.py. A momentum position is typically held
for months, so getting the daily-return bookkeeping wrong here would misstate
the paper track record for a long time before anyone noticed -- this is what
stands in for noticing immediately.

Run: python3 forex/tests/test_universe_parity.py    (needs node on PATH)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))         # forex/ -- for `fxlab`
sys.path.insert(0, str(ROOT.parent))  # fx-signals/ -- for check_strategy, check_universe

import check_strategy  # noqa: E402
import check_universe as cu  # noqa: E402
from fxlab import data  # noqa: E402

RUNNER = Path(__file__).resolve().parent / "parity_runner_universe.mjs"
TOLERANCE = 1e-9  # daily-return arithmetic involves more subtraction than the
                   # signal-only check, so the floor is a touch looser than
                   # test_parity.py's 1e-12 -- still far tighter than a cent
                   # on any real position.

CASES = [
    ("trending", dict(n=1500, seed=1, trend_strength=0.9), 2.0, 0.025),
    ("random walk", dict(n=1500, seed=2, trend_strength=0.0), 2.0, 0.025),
    ("short series", dict(n=340, seed=3), 5.0, 0.01),
    ("zero admin fee", dict(n=900, seed=4, trend_strength=0.8), 2.0, 0.0),
]

JS_CONFIG = dict(
    strategy="tsm",
    lookback=cu.LOOKBACK,
    maxHold=0,  # check_universe.py never caps the hold -- that's the point of it
    volTarget=cu.VOL_TARGET,
    volWindow=cu.VOL_WINDOW,
    maxLeverage=cu.MAX_LEVERAGE,
    rebalanceBand=cu.REBALANCE_BAND,
)


def python_series(prices, cost_bps, admin_fee):
    closes = prices.to_numpy()
    signal = cu.tsm(list(closes), cu.LOOKBACK)
    targets = cu.targets_for(list(closes), signal)
    gross = check_strategy.evaluate(closes, targets, cost_bps)
    financed = cu.evaluate_financed(list(closes), targets, cost_bps, admin_fee)
    return (
        np.asarray(targets, dtype=float),
        np.asarray([0.0 if v is None else v for v in gross], dtype=float),
        np.asarray([0.0 if v is None else v for v in financed], dtype=float),
    )


def js_series(closes, cost_bps, admin_fee):
    proc = subprocess.run(
        ["node", str(RUNNER)],
        input=json.dumps({
            "closes": list(closes), "config": JS_CONFIG,
            "costBps": cost_bps, "adminFeeAnnual": admin_fee,
        }),
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"parity_runner_universe.mjs failed:\n{proc.stderr}")
    out = json.loads(proc.stdout)
    return (
        np.asarray(out["target"], dtype=float),
        np.asarray(out["dailyGross"], dtype=float),
        np.asarray(out["dailyFinanced"], dtype=float),
    )


def worst_diff(a, b):
    return float(np.nanmax(np.abs(a - b))) if len(a) else 0.0


def main():
    if shutil.which("node") is None:
        sys.exit("node is not on PATH; the parity test cannot run")

    failures = 0
    for name, series_kw, cost_bps, admin_fee in CASES:
        prices = data.synthetic(**series_kw)
        closes = prices.to_numpy()

        py_target, py_gross, py_financed = python_series(prices, cost_bps, admin_fee)
        js_target, js_gross, js_financed = js_series(closes, cost_bps, admin_fee)

        if not (len(py_target) == len(js_target) == len(closes)):
            print(f"FAIL  {name}: length mismatch "
                  f"(python {len(py_target)}, js {len(js_target)}, prices {len(closes)})")
            failures += 1
            continue

        d_target = worst_diff(py_target, js_target)
        d_gross = worst_diff(py_gross, js_gross)
        d_financed = worst_diff(py_financed, js_financed)
        worst = max(d_target, d_gross, d_financed)

        if worst > TOLERANCE:
            print(f"FAIL  {name}: worst diff {worst:.3e} "
                  f"(target {d_target:.1e}, gross {d_gross:.1e}, financed {d_financed:.1e})")
            failures += 1
        else:
            traded = int((np.diff(js_target, prepend=0.0) != 0).sum())
            print(f"PASS  {name}: {len(closes)} bars, {traded} position changes, "
                  f"worst diff {worst:.1e} (cost={cost_bps}bp, admin={admin_fee:.1%})")

    if failures:
        sys.exit(f"\n{failures} of {len(CASES)} universe parity cases FAILED")
    print(f"\n{len(CASES)} universe parity cases passed. "
          f"JS and Python agree to {TOLERANCE:.0e} on position AND daily P&L.")


if __name__ == "__main__":
    main()
