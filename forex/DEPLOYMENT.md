# Running this on a server

Two ways, and you probably want the first.

## Option A: Vercel, from this repo (recommended)

Vercel is the better starting point precisely because you asked for a signal
generator rather than a bot. There is nothing to place orders, so nothing
needs to hold broker credentials or run continuously. A page that recomputes
once a day is a perfect fit for what Vercel does.

This project deploys **on its own**, in its own Vercel project. It was
briefly built inside another site's repo and moved out, for reasons worth
stating because they apply to anyone tempted to do the same:

- A production site with real readers should not share a failure domain with
  a personal experiment — a broken deploy here would have taken that down.
- Vercel's Hobby plan limits cron jobs **per project**, so two unrelated
  daily jobs compete for the same allowance.
- A page showing open positions on a domain with a named publisher behind it
  raises questions about presenting investment recommendations that are much
  easier to simply not raise.
- And if execution ever exists, broker API keys must not sit in the
  environment of a public website.

Setup is in the top-level `README.md`. The short version: attach Postgres,
set `FX_ACCESS_TOKEN`, deploy, hit `/api/signals` once, then open the site
with `?k=<token>`.

### The access gate is not optional

A private repo does **not** make a Vercel deployment private. The project
gets a public `*.vercel.app` URL and anyone who learns it can read the page —
which shows your open positions. `proxy.js` refuses every request without the
shared secret and **fails closed** when the secret is unset, because an
unset secret silently meaning "open to everyone" is exactly the failure this
is meant to prevent.

`/api/*` is deliberately exempt: Vercel's scheduler carries no cookie, so a
gated cron would simply never fire. That route guards itself with
`CRON_SECRET` instead.

### The one real risk in this approach

There are now **two implementations** of the same strategy: `forex/fxlab`
(Python, pandas, used to decide whether the edge is real) and
`src/lib/fx/strategy.js` (used to generate the signals you look at). Two
copies of a trading rule is normally a mistake, because the copy that drifts
is invariably the one making decisions.

`forex/tests/test_parity.py` is what makes it safe. It pushes identical prices
through both and requires the targets to match to 1e-12, across trending
series, random walks, short series, and configurations with the cap off:

```bash
python3 forex/tests/test_parity.py    # needs node on PATH
```

**If you change either implementation, run this.** If it fails, the signals on
the site are no longer the ones that were validated, and the fix is the code,
not the tolerance.

## Option B: a VPS running the Python directly

Better once you want the full research kit on the same machine, or when the
execution layer eventually exists.

Short answer: **yes, easily, for about €5/month.**

The reason it is easy is the reason your new horizon is a good choice. A
strategy that holds for one to two weeks and decides once a day is not
competing on speed with anyone. You need a machine that wakes up once a day
and can reach the internet. That is all.

Anything you read about VPS latency, colocation, or "trading servers near the
liquidity provider" is aimed at people doing something entirely different
from what we are doing, and mostly at people being sold something.

## The machine

| Option | Cost | Notes |
|---|---|---|
| **Hetzner CX22** | ~€4/mo | Nuremberg/Helsinki. Best value in the EU. |
| DigitalOcean basic | ~$6/mo | Frankfurt/Amsterdam regions. |
| Fly.io / Railway | ~$5/mo | Fine if you prefer not to manage a box. |
| A Raspberry Pi at home | one-off | Works, but your home internet and power become single points of failure. |

Requirements are trivial: 1 vCPU, 1 GB RAM, Python 3.11+, and outbound HTTPS.
The full daily run over ten pairs takes a couple of seconds.

Pick a region near your broker's servers if you like, but for a daily
decision it genuinely does not matter.

## Setup

```bash
# on the VPS
sudo apt update && sudo apt install -y python3-pip git
git clone <this repo> /opt/fxlab && cd /opt/fxlab/forex
pip3 install pandas numpy --break-system-packages
mkdir -p log

cp config.example.json config.json
$EDITOR config.json          # set account_equity, pairs, and your REAL cost_bps

python3 tests/test_engine.py # must pass before you trust any output
python3 signals.py --config config.json --no-write
```

Then cron, once a day, after the New York close (22:00 UTC), weekdays only:

```cron
30 22 * * 1-5 cd /opt/fxlab/forex && /usr/bin/python3 signals.py --config config.json >> log/signals.log 2>&1
```

Use `--no-write` while you are still watching it, so a bad run cannot corrupt
`state.json`. Drop the flag once you trust it.

### Knowing when it breaks

A silent cron job is how automated systems die. Two habits:

- `signals.py` writes warnings to **stderr**, so with the redirect above they
  land in the log. Stale data — a dead feed, a broker holiday — is flagged
  rather than silently traded on.
- Add a heartbeat. Simplest version that works: pipe the output to a
  `curl` call at healthchecks.io (free) so that *not* running pages you.
  A system that stops trading without telling you is worse than one that
  never started.

## Choosing a broker API

This is the real decision, and it is still open. It sets your costs, which is
the single number the whole strategy turns on.

**Correction to what this file used to say:** OANDA's v20 API was listed
here as the easy default. It isn't available. EU retail clients were
migrated to OANDA TMS Brokers S.A. (Poland-regulated), which — per OANDA's
own developer documentation — does not offer API access at all. This was
found the hard way, hunting for a menu item that doesn't exist for this
account type. See `fx-signals/README.md` for what the live dashboard uses
instead (Yahoo, as a stand-in).

| Broker | API | All-in cost on EURUSD | Verdict |
|---|---|---|---|
| **Interactive Brokers** | TWS/IB Gateway, needs a running process | ~0.2–0.4 bp round trip | Full API access for EU clients. Materially more work to wire up, materially cheaper, and — because it can trade real futures, not CFDs — sidesteps the overnight financing fee entirely. Worth it above ~€25k. |
| **Saxo** | OpenAPI, REST, EU | ~1.0–1.6 bp | Confirm API access is actually included for a retail EU account before relying on it — ask, don't assume, given what happened with OANDA. |
| ~~OANDA~~ | ~~v20 REST~~ | — | **Not available to EU retail clients as of this writing.** Kept struck through rather than deleted, so this mistake isn't repeated. |
| MetaTrader 5 | Python package, but needs the MT5 terminal | broker-dependent | Awkward on a Linux VPS. Avoid unless tied to a specific broker. |

Two things worth knowing as an EU resident:

- ESMA caps retail leverage at 30:1 on majors, with negative balance
  protection. **This does not constrain us at all** — the design runs at
  `max_leverage: 1.0`, i.e. never more than account notional. The cap is
  roughly thirty times looser than what we are doing. That is intentional.
- Ask your broker for their **swap/rollover rates**. A one-to-two week hold
  crosses 5–10 rollovers, and spot price series exclude the interest
  differential entirely. `Config.carry_annual` exists to model this; right
  now it is set to zero, which means every backtest here is blind to a real
  P&L component. On some pairs it is a meaningful drag.

## Before any of this touches money

The runner deliberately cannot place orders. Broker execution is a separate
piece of work, and it should not be written until these gates are passed:

1. **The edge exists.** Out-of-sample Sharpe beats the `random_walk` null,
   across at least six pairs and ten-plus years of real data. Not synthetic.
   Nothing in this repo has met this gate yet, because no market data host is
   reachable from the environment it was built in.
2. **It survives your real costs.** Run `--cost-sweep` and find the level
   where the edge dies. If that number is not at least double your broker's
   actual round-trip cost, there is no margin for the slippage you will meet
   live.
3. **The holding period is what you think it is.** Check the `AvgHold`
   column. A rule you believe is a two-week strategy will often turn out to
   hold for two months.
4. **Paper first, for two to three months.** Run the cron job, log what it
   says, and compare against what actually happened. You are checking for
   boring failures: data gaps, timezone errors, a feed that revises its
   history.
5. **Then live at the smallest size your broker allows, for three months.**
   The only question at this stage is whether live fills match backtest
   assumptions. They will be worse. The question is by how much.
6. **Only then scale**, and slowly.

Skipping to step 6 is the standard way this goes wrong, and it is more
tempting after a good backtest, not less.

## Safety rails to add before live execution

When we do write the execution layer, it needs these, and they are not
optional:

- **Drawdown kill switch.** Flatten and stop trading at a preset account
  drawdown. Decide the number while calm, encode it, and do not let the
  running system be the thing that reconsiders.
- **Per-pair position cap**, independent of what the strategy asks for.
- **Sanity check on every order** — reject anything more than N× the largest
  position the backtest ever took. A data glitch producing a 50x position is
  a real failure mode, not a hypothetical one.
- **Reconciliation.** Compare the broker's reported position against
  `state.json` on every run and halt on mismatch. Divergence between what you
  think you hold and what you hold is how small bugs become large losses.
- **No retry loops on order placement** without an idempotency key. Doubling
  a position because a response timed out is an easy and expensive mistake.

## What this costs to run

€4–6/month for the VPS, €0 for data if Stooq's daily FX series holds up, and
your time. If you want more reliable data later, a paid feed runs €20–50/month
— but do not buy one until step 1 above has actually passed.
