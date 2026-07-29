// One-off coverage check: does Twelve Data actually carry our 22 instruments?
//
// Not guessed ticker strings -- for each instrument this searches Twelve
// Data's own symbol directory by name (their /symbol_search endpoint), then
// confirms real historical daily data exists for whatever it finds. Two
// calls per instrument, paced to stay under a free-tier rate limit, rather
// than dozens of blind guesses at ticker syntax.
//
// The real question this answers: bond futures (10y note, 30y bond) are
// usually CME-licensed data sold separately even by providers that cover
// everything else -- if Twelve Data doesn't have them, that's the actual
// finding, not a bug in this script.
//
// Run: TWELVE_DATA_API_KEY=... node scripts/check-twelvedata-coverage.mjs

const KEY = process.env.TWELVE_DATA_API_KEY;
if (!KEY) {
  console.error("TWELVE_DATA_API_KEY is not set.");
  process.exit(1);
}

const BASE = "https://api.twelvedata.com";
const PACE_MS = 1600; // conservative -- free tier is commonly ~8 req/min

// name to search for, plus our internal code/asset class for the report.
const TARGETS = [
  ["GOLD", "gold", "metals"],
  ["SILVER", "silver", "metals"],
  ["COPPER", "copper", "metals"],
  ["WTI", "WTI crude oil", "energy"],
  ["BRENT", "Brent crude oil", "energy"],
  ["NATGAS", "natural gas", "energy"],
  ["CORN", "corn futures", "agriculture"],
  ["WHEAT", "wheat futures", "agriculture"],
  ["SOYBEANS", "soybean futures", "agriculture"],
  ["SUGAR", "sugar futures", "agriculture"],
  ["SPX", "S&P 500", "equity index"],
  ["NDX", "Nasdaq 100", "equity index"],
  ["DAX", "DAX", "equity index"],
  ["FTSE", "FTSE 100", "equity index"],
  ["NIKKEI", "Nikkei 225", "equity index"],
  ["ASX", "ASX 200", "equity index"],
  ["UST10Y", "10 year treasury note futures", "bonds"],
  ["UST30Y", "30 year treasury bond futures", "bonds"],
  ["EURUSD", "EUR/USD", "currencies"],
  ["GBPUSD", "GBP/USD", "currencies"],
  ["USDJPY", "USD/JPY", "currencies"],
  ["AUDUSD", "AUD/USD", "currencies"],
];

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function callApi(path, params) {
  const url = new URL(`${BASE}${path}`);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  url.searchParams.set("apikey", KEY);

  const res = await fetch(url);
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
}

async function searchSymbol(query) {
  const { status, body } = await callApi("/symbol_search", { symbol: query, outputsize: 5 });
  if (status === 429 || body?.code === 429) return { rateLimited: true };
  const matches = body?.data || [];
  return { matches };
}

async function confirmDaily(symbol) {
  const { status, body } = await callApi("/time_series", {
    symbol, interval: "1day", outputsize: 5,
  });
  if (status === 429 || body?.code === 429) return { rateLimited: true };
  const values = body?.values;
  return { ok: Array.isArray(values) && values.length > 0, raw: body };
}

async function main() {
  console.log("=".repeat(70));
  console.log("  TWELVE DATA COVERAGE CHECK -- 22 instruments");
  console.log("=".repeat(70));
  console.log();

  const results = [];

  for (const [code, query, assetClass] of TARGETS) {
    await sleep(PACE_MS);
    const search = await searchSymbol(query);

    if (search.rateLimited) {
      console.log(`RATE LIMITED  ${code} (${query}) -- inconclusive, not "not covered"`);
      results.push({ code, assetClass, status: "rate-limited" });
      continue;
    }

    if (!search.matches || search.matches.length === 0) {
      console.log(`NO MATCH      ${code} (${query}) -- symbol_search returned nothing`);
      results.push({ code, assetClass, status: "no-match" });
      continue;
    }

    const top = search.matches[0];
    await sleep(PACE_MS);
    const confirm = await confirmDaily(top.symbol);

    if (confirm.rateLimited) {
      console.log(`RATE LIMITED  ${code} (${query}) -- found ${top.symbol}, data check inconclusive`);
      results.push({ code, assetClass, status: "rate-limited", foundSymbol: top.symbol });
      continue;
    }

    if (confirm.ok) {
      console.log(`COVERED       ${code} -> ${top.symbol} (${top.instrument_type || "?"}) -- daily data confirmed`);
      results.push({ code, assetClass, status: "covered", symbol: top.symbol, type: top.instrument_type });
    } else {
      console.log(`FOUND, NO DATA ${code} -> ${top.symbol} exists in their directory but time_series returned none`);
      results.push({ code, assetClass, status: "found-no-data", symbol: top.symbol });
    }
  }

  console.log();
  console.log("-".repeat(70));
  console.log("SUMMARY BY ASSET CLASS");
  console.log("-".repeat(70));

  const byClass = {};
  for (const r of results) (byClass[r.assetClass] ??= []).push(r);

  for (const [cls, rows] of Object.entries(byClass)) {
    const covered = rows.filter((r) => r.status === "covered").length;
    console.log(`${cls}: ${covered}/${rows.length} covered`);
    for (const r of rows) {
      if (r.status !== "covered") console.log(`  ! ${r.code}: ${r.status}${r.symbol ? ` (${r.symbol})` : ""}`);
    }
  }

  const coveredCount = results.filter((r) => r.status === "covered").length;
  console.log();
  console.log(`${coveredCount} of ${TARGETS.length} instruments confirmed covered with real daily data.`);
}

main();
