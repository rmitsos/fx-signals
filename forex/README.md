# fxlab — FX strategy research kit

Research tooling for testing FX trading rules honestly. It places no trades,
connects to no broker, and makes no forecasts.

## Read this before the code

You asked me to be your consultant trader and tell you when to get in and
when to get out. Here is the straight version of what that can and cannot be.

**I cannot be a signal service.** I have no live price feed and no memory
between sessions. Anyone — human or model — who gives you confident entry and
exit calls on FX without showing you an out-of-sample track record is
guessing, and the guess is worth what you paid for it.

**What I can be** is the person who builds the rules, tries to break them,
and tells you when the evidence isn't there. That is the more valuable job
anyway, because your problem was never signal generation.

### Your actual problem

In your own description: you could catch some good trades, but you were
"either bored or never used the information as it should." That is the whole
diagnosis. You were not losing because you lacked a method. You were losing
because the method never survived contact with a human being who was bored.

This matters for what we build next, because it rules some things out. A
strategy with a real edge in FX trades **rarely** — a few times a year per
pair. It is *more* boring than what you were doing, not less. If discretion
is where your P&L died, then the system has to be automated end to end, or it
will die the same way with better indicators.

### The arithmetic that beat you

Short-term FX at high leverage does not fail because of psychology. It fails
because of a cost identity you cannot trade your way out of.

Retail EURUSD spread is roughly 1 pip. At 1.0850 that is **0.92 bp round
trip**. Five round trips a day is 4.6 bp/day, or about **11.6% of traded
notional per year**, before commission and slippage.

So at 1x notional, a strategy targeting 10% volatility must produce a gross
Sharpe above 1.16 just to break even. Nothing available to a retail account
does that intraday. And leverage does not rescue it: at 30x, costs scale with
notional too, so you are paying ~350% of account equity per year in spread.
The leverage multiplies the tax at exactly the rate it multiplies the edge.

That is why it never worked. It was arithmetic, not discipline.

### What actually has evidence in FX

| Method | Evidence | Horizon | Honest expectation |
|---|---|---|---|
| **Time-series momentum** | Strong (Moskowitz, Ooi & Pedersen 2012, and 100+ years of replication) | Weeks–months | Sharpe ~0.3–0.6 per pair, ~0.8 diversified across 8–10 pairs, gross |
| **Carry** | Strong, but it is a risk premium — it pays steadily and then crashes | Months | Positive expectancy, brutal tail |
| **Breakout / trend** | Real; it is momentum wearing different clothes | Weeks–months | Similar to TSM, higher turnover |
| **Value / PPP** | Real at multi-year horizons | Years | Too slow to trade an account on |
| **Fibonacci retracements** | No robust published evidence that price respects 61.8% more than any arbitrary level | — | Implemented here so you can measure it instead of arguing about it |

A well-built, diversified FX trend book runs at maybe **Sharpe 0.5**. At a 10%
volatility target that is roughly 5% a year with 20% drawdowns and losing
stretches lasting eighteen months. That is the actual product. If that sounds
disappointing, it is worth knowing now rather than after funding an account.

## What was wrong with the inherited script

`legacy_tsm_walkforward_backtest.py` is preserved unchanged for reference. It
had the right instinct — walk-forward, vol targeting, explicit costs — and
three real defects:

1. **Dead warmup in every out-of-sample window.** It sliced a 1-year test
   window out of the price series and *then* asked for a 126-day momentum
   signal. With no prior history, `pct_change(126)` is NaN for the first 126
   days, so the signal was pinned at zero. Measured on synthetic data:
   **48% of every "out-of-sample" window was flat**, measuring nothing.
   Fixed here by computing signals on full history up to the window's end and
   only *evaluating* on the window. Covered by
   `test_walk_forward_has_no_dead_warmup` (now 0% flat).

2. **Volatility targeting that wasn't.** With `vol_target=0.10` and
   `max_leverage=1.0`, and FX majors realizing 7–9% vol, the cap binds
   essentially all the time. What looks like a vol-targeted position is a
   constant full-size position that only de-risks during crises. That may be
   a design you want — but you should choose it, not inherit it by accident.

3. **Sharpe understated.** It divided geometric CAGR by volatility, which is
   low by roughly half the variance. `metrics.sharpe` uses the standard
   definition.

The three-year training period was also never used for anything, which the
original acknowledged. Here `walk_forward` accepts a `fit_fn` that sees only
the training slice, so parameter fitting is possible without leaking.

## The horizon: one to two weeks, automated

That is the decision, and the cost arithmetic supports it far better than
what you were doing before:

| Holding period | Round trips/yr | Cost/yr @ 0.92bp | Sharpe drag |
|---|---|---|---|
| Intraday, 5/day | ~1,260 | **11.6%** | fatal |
| **1–2 weeks** | ~25–50 | **0.23–0.46%** | ~0.03 |

At this horizon costs essentially stop mattering — a 40x improvement. What
replaces cost as the binding constraint is whether the *edge* exists at that
speed, which is thinner territory than the 1–3 month band where most of the
published FX trend evidence sits. That is an empirical question, so the kit
now measures it directly.

One distinction worth being precise about: **holding period is normally an
output, not an input.** A 126-day momentum rule holds for ~36 bars because
that is how often it changes its mind. Measured here on synthetic data:

```
tsm(126)                    ~36 bars   (7 weeks)
donchian(20) + max_hold=10  ~9.5 bars  (2 weeks)   <- the target band
```

`strategies.with_max_hold` makes the horizon an input by forcing a flat
position after N bars. Be honest about what that is: a constraint that can
only reduce gross return, since it cuts winners at an arbitrary bar count. It
earns its place only if the shorter horizon buys something back — lower
drawdown, or capital freed for another pair. Also note it leaves you flat
much more of the time (~30% time-in-market in the configuration above), which
is its own kind of discipline test.

## Layout

```
fxlab/engine.py       backtest core; the ONLY execution lag in the codebase
fxlab/strategies.py   tsm, donchian, ma_cross, fib_pullback, random_walk,
                      with_max_hold
fxlab/metrics.py      Sharpe, drawdown, t-stats, trade spans, holding period
fxlab/data.py         csv / stooq / yfinance / synthetic loaders
run_backtest.py       research CLI
signals.py            daily runner for the server — emits positions, places
                      no orders
config.example.json   copy to config.json and set your real cost_bps
DEPLOYMENT.md         Vercel, VPS, broker APIs, and the gates before going live
tests/test_engine.py  correctness tests — run these after any change
tests/test_parity.py  proves the web app's JS matches this Python
```

The signal generator that renders in the browser lives in the Next.js app
alongside it, because you asked to *see* how it works rather than trust a
process you cannot watch:

```
src/lib/fx/strategy.js     the same math, ported, no dependencies
src/lib/fx/prices.js       daily closes from stooq
src/lib/fx/config.js       pairs and parameters
src/lib/fx/signals.js      orchestration
src/lib/fx/store.js        daily snapshots in Postgres
src/app/api/signals/       the daily cron
src/app/page.js            the page — shows the reasoning, not just the answer
src/proxy.js                   access gate; fails closed if the secret is unset
```

Two implementations of one strategy is a real hazard, so it is held shut by a
test rather than by care: `tests/test_parity.py` runs identical prices through
both and requires agreement to 1e-12. Run it after touching either side.

The design rule worth knowing: strategies return a direction decided *at the
close of bar t*, and the engine applies the one-bar execution lag. There is
exactly one `.shift(1)` in the codebase. Every new strategy inherits the
protection instead of being a fresh chance to leak the future.
`test_no_lookahead` verifies this by rewriting the last 200 bars of the price
series and asserting that no earlier P&L figure moves.

## Running it

```bash
pip install pandas numpy --break-system-packages   # yfinance only if you want it

python3 tests/test_engine.py                       # always start here

# no network required
python3 run_backtest.py --pairs synthetic:seed=1 --strategies all

# real data, targeting the one-to-two week band
python3 run_backtest.py \
  --pairs stooq:eurusd stooq:usdjpy stooq:gbpusd stooq:audusd \
  --strategies tsm donchian fib_pullback random_walk \
  --params donchian.lookback=20 tsm.lookback=21 \
  --max-hold 10 \
  --cost-sweep 0 1 3 10 --rebalance-band 0.25

# what the server would do tonight
python3 signals.py --config config.json --no-write
```

**Note:** this environment blocks all market-data hosts at the egress proxy
(Yahoo, Stooq, FRED and the ECB all fail with 403), so nothing here has been
run against real prices. It has only been verified on synthetic series. The
first real run has to happen on your machine, or in an environment with those
hosts allowed.

### How to read the output

- **Ignore the full-sample number.** It is the number that made you like the
  strategy, so it cannot also be the evidence for it.
- **Compare everything to `random_walk`**, which is coin flips at matched
  turnover. A strategy that cannot beat a coin has demonstrated nothing.
- **Watch the cost sweep.** The interesting output is not the Sharpe at
  0 bps, it is the cost level where the edge dies. If it dies below your real
  spread, the strategy does not exist.
- **Respect the multiple-testing hurdle** the runner prints. Testing 30
  configurations and keeping the best means the winner needs |t| above ~2.6,
  not 2.0.
- **Read the PORTFOLIO row.** Single-pair FX momentum is mostly noise; the
  documented edge is a diversified one.

## Open questions before the next step

Settled: one-to-two week horizon, fully automated, running on a small VPS.
See `DEPLOYMENT.md`.

Still blocking:

1. **Which broker, and what are your actual all-in costs per round trip?**
   Everything turns on this number and I am currently guessing it. It decides
   whether the edge — if there is one — is large enough to collect.
2. **Account size.** Sets whether position sizing is even expressible at sane
   granularity, and whether Interactive Brokers' lower costs are worth its
   heavier API.
3. **Real price data.** Nothing here has run against a real quote, because
   this environment blocks every market-data host. Until step 1 of the
   validation gates in `DEPLOYMENT.md` passes, we do not know whether any of
   these rules has an edge at a two-week horizon. Everything else is
   scaffolding waiting on that answer.

## What this is not

Research tooling. Backtests are informative, not predictive: they are blind
to slippage, liquidity gaps, weekend risk, and the specific way your broker
fills you during a spike. Every number this produces should be treated as an
optimistic upper bound on what live trading would have returned.
