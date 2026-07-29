// Live-network smoke test for the JS side of the dashboard.
//
// Everything else about this app can be checked without touching a real
// network: the strategy math is proven against Python in
// forex/tests/test_universe_parity.py, and the access gate, empty-state
// page, and error handling can all run locally with the fetch itself
// stubbed out. The one thing that cannot be checked from a sandboxed dev
// environment is whether src/lib/fx/prices.js's Yahoo fetch actually works
// on a live network -- so this script does exactly that, nothing else, on
// GitHub's runners where the network isn't blocked.
//
// No database, no email, no Next.js server -- just prices in, signal out.

import { fetchDailyCloses } from "../src/lib/fx/prices.js";
import { runStrategy, explain } from "../src/lib/fx/strategy.js";
import { UNIVERSE, STRATEGY, MIN_BARS } from "../src/lib/fx/config.js";

const SAMPLE = ["GOLD", "SPX", "EURUSD"]; // one per how differently Yahoo serves them: future, index, FX

async function main() {
  let failures = 0;

  for (const code of SAMPLE) {
    const inst = UNIVERSE.find((u) => u.code === code);
    if (!inst) {
      console.log(`FAIL  ${code}: not in UNIVERSE`);
      failures++;
      continue;
    }

    try {
      const { dates, closes } = await fetchDailyCloses(inst.ticker);
      if (closes.length < MIN_BARS) {
        throw new Error(`only ${closes.length} bars, need ${MIN_BARS}`);
      }

      const result = runStrategy(closes, STRATEGY);
      const view = explain(result);

      console.log(
        `PASS  ${code} (${inst.ticker}): ${closes.length} bars, ` +
        `${dates[0]} to ${dates.at(-1)}, state=${view.target > 0 ? "LONG" : view.target < 0 ? "SHORT" : "FLAT"}`
      );
    } catch (err) {
      console.log(`FAIL  ${code} (${inst.ticker}): ${err.message}`);
      failures++;
    }
  }

  if (failures > 0) {
    console.log(`\n${failures} of ${SAMPLE.length} live fetches failed.`);
    process.exit(1);
  }
  console.log(`\nAll ${SAMPLE.length} sampled tickers fetched and produced a signal.`);
}

main();
