// Bridge for the parity test: reads {closes, config} as JSON on stdin, runs
// the *real* app strategy module, writes {target, signal, upper, lower} out.
//
// It imports src/lib/fx/strategy.js directly rather than copying anything, so
// the test compares Python against the exact code the website runs.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const { runStrategy } = await import(
  resolve(here, "../../src/lib/fx/strategy.js")
);

const { closes, config } = JSON.parse(readFileSync(0, "utf8"));
const result = runStrategy(closes, config);

process.stdout.write(
  JSON.stringify({
    target: result.target,
    signal: result.signal,
    upper: result.upper.map((v) => (Number.isFinite(v) ? v : null)),
    lower: result.lower.map((v) => (Number.isFinite(v) ? v : null)),
  })
);
