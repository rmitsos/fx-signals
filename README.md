# fx-signals

A daily trend-following signal dashboard, and the research kit that found
and validated the strategy behind it.

**It places no trades, connects to no broker, and holds no credentials that
could move money.** It computes what a fixed rule wants to hold across 22
instruments, stores that every day, and shows you the reasoning — not just
the answer.

## Start here: does it actually work?

```bash
python3 check_universe.py
```

One file, nothing to install beyond the standard library. It downloads ~25
years of daily prices across metals, energy, agriculture, equity indices,
bonds and currencies, tests 12-month momentum, compares it against random
coin flips at matched turnover, and — critically — models OANDA's overnight
CFD financing, because that fee turned out to be the thing that decides
whether this is worth anything.

There is also `check_strategy.py`, the earlier and narrower test: a
short-horizon FX-only breakout. Kept for the record because it is
informative by contrast — it found nothing, which is what sent the search
toward `check_universe.py` in the first place.

Two implementations of the momentum strategy already existed before the
dashboard did — pandas (`forex/fxlab`) and a dependency-free stdlib version
(`check_universe.py`) — checked against each other in
`forex/tests/test_parity.py`. The dashboard adds a **third**: the JavaScript
in `src/lib/fx/`, checked against the Python in
`forex/tests/test_universe_parity.py` to 1e-9 on both the position taken and
the daily P&L, gross and after financing.

## Status: real edge, marginal after the broker's cut

25 years of real prices, 22 instruments, four asset classes:

| | Gross | After OANDA financing |
|---|---|---|
| Sharpe | 0.54 | **0.28** |
| Is it luck? | t = 2.9 (no) | t = 1.5 (can't rule it out) |
| Return | 2.5%/yr | 1.2%/yr |
| Worst fall | −12.7% | −18.4% |

The edge is real — it beats a coin flip run at the same turnover, across 25
years and four independent asset classes, and equity indices carry most of
it (currencies contributed nothing, in two separate tests). But OANDA's CFD
admin fee (2.5%/yr on most classes, charged whether you're long or short)
eats roughly half of it. What's left is too thin to trade with confidence.

See `forex/README.md` for the full walk from a losing short-term FX idea to
this, and `forex/DEPLOYMENT.md` for the deployment gates that still apply
before any of it should touch money.

**This dashboard exists to keep an honest, timestamped record of what the
rule says — a paper track record — so that question can eventually be
answered with more than a backtest.**

## The strategy

12-month (252-day) time-series momentum: long if the price is higher than it
was a year ago, short if lower. No holding cap — a position runs until the
trend itself reverses, unlike the earlier FX-only version which forced an
exit after 10 days. Each instrument is sized to an equal share of portfolio
risk (10% annualised volatility target), never levered beyond account
notional.

Average holding period is around 40 days, but with no cap, individual trends
can run for months. That is slower than most people mean by "trading" — it
is also, per the evidence, closer to where trend actually works.

## Data feed: Yahoo, not OANDA

The obvious choice would have been OANDA's own API — same prices you'd
actually deal at. It isn't available: EU retail clients (which this account
is) were migrated to OANDA TMS Brokers S.A., which does not offer API access
at all, by OANDA's own documentation. Yahoo's chart endpoint is the stand-in
for now. Since the strategy decides once a day from the daily close, this
is not a decision-quality compromise — only a "how authoritative is the
exact price, and how long will this undocumented endpoint keep working"
compromise. Revisit if a broker with real API access enters the picture.

## Layout

```
src/lib/fx/strategy.js   the signal math: donchian (legacy) + tsm (live), no deps
src/lib/fx/prices.js     daily closes from Yahoo's chart endpoint
src/lib/fx/config.js     the 22-instrument universe and strategy params —
                         edited by commit, not at runtime
src/lib/fx/signals.js    orchestration: fetch, compute, persist, roll up
src/lib/fx/store.js      daily snapshots + the running paper P&L, in Postgres
src/lib/fx/email.js      Resend call, fires only when a position changed
src/app/page.js          the dashboard: per-instrument reasoning, asset-class
                         rollup, and the gross-vs-financed equity curve
src/app/api/signals/     the daily cron endpoint
src/proxy.js             access gate — nothing is served without the secret
                         (Next 16 renamed the middleware convention to proxy;
                         it must sit beside app/, so src/ and not the root)
scripts/smoke-fetch.mjs  live-network check of the Yahoo fetch (see Tests)

forex/                   the Python research kit (backtests, walk-forward)
forex/README.md          the full result and how the search got here
forex/DEPLOYMENT.md      deployment, broker APIs, and the gates before live
forex/check_universe.py  the diversified-trend test — the one that mattered
forex/check_strategy.py  the earlier FX-only test — kept for the contrast
```

## Moving this into its own repository

It is currently staged inside another repo and needs to become its own. From
the parent repo's root:

```bash
# 1. Create an EMPTY private repo on GitHub named fx-signals (no README,
#    no .gitignore — an initial commit just gets in the way).

# 2. Copy this directory out, initialise it, and push.
cp -r fx-signals ../fx-signals && cd ../fx-signals
git init -b main
git add -A && git commit -m "Trend-following signal dashboard and research kit"
git remote add origin git@github.com:<you>/fx-signals.git
git push -u origin main
```

Then delete `fx-signals/` from the parent repo, along with its entries in
that repo's `.gitignore`, `.vercelignore` and `eslint.config.mjs`.

History is deliberately not preserved — the commits it would carry are
interleaved with an unrelated news site, so a clean first commit is more
honest than a filtered one that pretends this was always separate.

## Deploying to Vercel

1. Create a Vercel project from this repo.
2. Attach a Postgres database (Neon via Vercel Storage sets `DATABASE_URL`).
3. Set environment variables:
   - `FX_ACCESS_TOKEN` — a long random string. **Required.** Without it the
     site refuses every request rather than serving openly.
   - `CRON_SECRET` — optional; locks `/api/signals` to Vercel's scheduler.
   - `RESEND_API_KEY` / `ALERT_EMAIL_TO` — optional; without both, the app
     still runs fine and simply doesn't email on signal changes.
     `ALERT_EMAIL_FROM` defaults to Resend's sandbox sender if unset.
   - `FX_DISPLAY_EQUITY` — optional; the notional sizes are shown against.
4. Deploy. `vercel.json` runs `/api/signals` daily at 23:00 UTC.
5. Visit `/api/signals` once by hand to populate the first day.
6. Open `https://<your-app>.vercel.app/?k=<FX_ACCESS_TOKEN>`. The token moves
   into an httpOnly cookie and drops out of the URL.

### Why the access gate exists

A private repo does **not** make a Vercel deployment private. The project gets
a public `*.vercel.app` URL, and anyone who learns it can read the page. This
page shows your open positions. So `proxy.js` refuses everything without the
shared secret, and fails *closed* if the secret is unset.

It is a shared secret, not an authentication system. If this ever holds broker
credentials, replace it with real auth first.

## Tests

```bash
npm test
```

Three suites, and all three matter:

- `forex/tests/test_engine.py` — 11 correctness tests on the backtest engine.
  The important one rewrites the last 200 bars of price history and asserts no
  earlier P&L figure moves, which is how you catch lookahead.
- `forex/tests/test_parity.py` — the FX/donchian strategy exists in both
  pandas and JavaScript. Checks agreement to 1e-12.
- `forex/tests/test_universe_parity.py` — the live dashboard's momentum
  strategy, in both `check_universe.py`'s Python and `src/lib/fx/`'s
  JavaScript. Checks agreement to 1e-9 on **both** the position taken and the
  daily P&L, gross and after OANDA's admin fee — a strategy that holds for
  months would let a bookkeeping error sit unnoticed for a long time
  otherwise. **Run this after changing either side.**

None of the above touches a network — all synthetic. The one thing that
can't be checked without a live network is whether `prices.js`'s Yahoo fetch
itself still works, since this app was built in a sandbox that blocks
Yahoo. `scripts/smoke-fetch.mjs` does exactly that, wired into
`.github/workflows/check-strategy.yml` so it runs on every push on GitHub's
(unblocked) runners.

Running the research CLI needs `pandas` and `numpy`; the site itself needs
neither.

```bash
pip install pandas numpy --break-system-packages
python3 forex/run_backtest.py --pairs stooq:eurusd stooq:gbpusd \
  --strategies donchian random_walk --params donchian.lookback=20 \
  --max-hold 10 --cost-sweep 0 1 3 10
```

Read the `random_walk` row against the others. A rule that cannot beat coin
flips at matched turnover has demonstrated nothing.
