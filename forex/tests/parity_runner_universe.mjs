// Bridge for the momentum parity test: reads {closes, config} as JSON on
// stdin, runs the real app's strategy module (tsm + dailyPnl), writes
// {target, dailyGross, dailyFinanced} out.
//
// Imports src/lib/fx/strategy.js directly, same as parity_runner.mjs, so the
// test compares Python against the exact code the website runs.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const { runStrategy, dailyPnl } = await import(
  resolve(here, "../../src/lib/fx/strategy.js")
);

const { closes, config, costBps, adminFeeAnnual } = JSON.parse(readFileSync(0, "utf8"));
const result = runStrategy(closes, config);

const target = result.target;
const dailyGross = [];
const dailyFinanced = [];
for (let i = 0; i < closes.length; i++) {
  const pnl = dailyPnl(result, i, { costBps, adminFeeAnnual });
  dailyGross.push(pnl.gross);
  dailyFinanced.push(pnl.financed);
}

process.stdout.write(JSON.stringify({ target, dailyGross, dailyFinanced }));
