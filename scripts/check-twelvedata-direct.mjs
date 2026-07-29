// Follow-up to check-twelvedata-coverage.mjs.
//
// That script's /symbol_search-based approach returned ONLY Common
// Stock/ETF/Mutual Fund/Warrant types across every single non-FX query --
// never a raw commodity, index, or bond type, not even for gold. That
// pattern suggests /symbol_search may have a blind spot for those asset
// classes on this plan, rather than the data genuinely being absent.
//
// This bypasses search entirely and calls /time_series directly on Twelve
// Data's own documented direct symbols (XAU/USD for gold spot is on their
// public commodities page; SPX/NDX/etc. are the conventional direct index
// symbols many providers support even when not surfaced by fuzzy search).
// A handful of calls, not a full re-scan.
//
// Run: TWELVE_DATA_API_KEY=... node scripts/check-twelvedata-direct.mjs

const KEY = process.env.TWELVE_DATA_API_KEY;
if (!KEY) {
  console.error("TWELVE_DATA_API_KEY is not set.");
  process.exit(1);
}

const BASE = "https://api.twelvedata.com";
const PACE_MS = 8000;

const DIRECT = [
  ["GOLD (spot)", "XAU/USD"],
  ["SILVER (spot)", "XAG/USD"],
  ["S&P 500", "SPX"],
  ["Nasdaq 100", "NDX"],
  ["Nasdaq Composite (alt)", "IXIC"],
  ["DAX", "DAX"],
  ["DAX (alt)", "GDAXI"],
  ["FTSE 100", "UKX"],
  ["FTSE 100 (alt)", "FTSE"],
  ["Nikkei 225", "N225"],
  ["ASX 200", "AXJO"],
  ["WTI crude (continuous)", "CL1"],
  ["Corn (continuous)", "C_1"],
];

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function timeSeries(symbol, attempt = 1) {
  const url = new URL(`${BASE}/time_series`);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("interval", "1day");
  url.searchParams.set("outputsize", "5");
  url.searchParams.set("apikey", KEY);

  const res = await fetch(url);
  const body = await res.json().catch(() => ({}));

  if ((res.status === 429 || body?.code === 429) && attempt < 3) {
    await sleep(PACE_MS * 2);
    return timeSeries(symbol, attempt + 1);
  }
  return { status: res.status, body };
}

async function main() {
  console.log("=".repeat(70));
  console.log("  DIRECT SYMBOL CHECK -- documented conventions, no search");
  console.log("=".repeat(70));
  console.log();

  let covered = 0;
  for (const [label, symbol] of DIRECT) {
    await sleep(PACE_MS);
    const { status, body } = await timeSeries(symbol);

    if (Array.isArray(body?.values) && body.values.length > 0) {
      console.log(`COVERED   ${label} -> "${symbol}": ${body.values.length} rows, ` +
        `latest ${body.values[0].datetime} = ${body.values[0].close}`);
      covered++;
    } else {
      const reason = body?.message || body?.code || status;
      console.log(`NO DATA   ${label} -> "${symbol}": ${reason}`);
    }
  }

  console.log();
  console.log(`${covered} of ${DIRECT.length} direct symbols confirmed.`);
}

main();
