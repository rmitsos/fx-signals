// One-off coverage check: does Twelve Data actually carry our 22 instruments?
//
// v2. The first version was too naive in two ways worth recording rather
// than silently fixing: it paced requests at 1.6s and got rate-limited
// partway through (their free tier is closer to one request per 8s), and it
// blindly took symbol_search's FIRST result -- which for "corn futures" and
// "wheat futures" returned what look like Chinese A-share stock tickers
// (6-digit numeric codes), not the actual commodity. A wrong top match is
// not evidence of "no coverage"; it's a bug in the test.
//
// This version paces conservatively, fetches the top 5 candidates per
// instrument instead of just the first, and picks whichever candidate's
// instrument_type actually matches what we're looking for -- logging every
// candidate considered, so a wrong pick is visible rather than silent.
//
// Run: TWELVE_DATA_API_KEY=... node scripts/check-twelvedata-coverage.mjs

const KEY = process.env.TWELVE_DATA_API_KEY;
if (!KEY) {
  console.error("TWELVE_DATA_API_KEY is not set.");
  process.exit(1);
}

const BASE = "https://api.twelvedata.com";
const PACE_MS = 8000; // free tier is commonly ~8 req/min; stay well clear of it

// name to search for, an instrument_type substring (lowercase) that would
// count as a real match for this asset class, and our internal code.
const TARGETS = [
  ["GOLD", "gold", "metals", ["commodity", "currency"]],
  ["SILVER", "silver", "metals", ["commodity", "currency"]],
  ["COPPER", "copper", "metals", ["commodity"]],
  ["WTI", "WTI crude oil", "energy", ["commodity"]],
  ["BRENT", "Brent crude oil", "energy", ["commodity"]],
  ["NATGAS", "natural gas", "energy", ["commodity"]],
  ["CORN", "corn", "agriculture", ["commodity"]],
  ["WHEAT", "wheat", "agriculture", ["commodity"]],
  ["SOYBEANS", "soybean", "agriculture", ["commodity"]],
  ["SUGAR", "sugar", "agriculture", ["commodity"]],
  ["SPX", "S&P 500", "equity index", ["index"]],
  ["NDX", "Nasdaq 100", "equity index", ["index"]],
  ["DAX", "DAX", "equity index", ["index"]],
  ["FTSE", "FTSE 100", "equity index", ["index"]],
  ["NIKKEI", "Nikkei 225", "equity index", ["index"]],
  ["ASX", "ASX 200", "equity index", ["index"]],
  ["UST10Y", "treasury note", "bonds", ["bond", "commodity", "index"]],
  ["UST30Y", "treasury bond", "bonds", ["bond", "commodity", "index"]],
  ["EURUSD", "EUR/USD", "currencies", ["currency"]],
  ["GBPUSD", "GBP/USD", "currencies", ["currency"]],
  ["USDJPY", "USD/JPY", "currencies", ["currency"]],
  ["AUDUSD", "AUD/USD", "currencies", ["currency"]],
];

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function callApi(path, params, attempt = 1) {
  const url = new URL(`${BASE}${path}`);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  url.searchParams.set("apikey", KEY);

  const res = await fetch(url);
  const body = await res.json().catch(() => ({}));

  if ((res.status === 429 || body?.code === 429) && attempt < 3) {
    await sleep(PACE_MS * 2);
    return callApi(path, params, attempt + 1);
  }
  return { status: res.status, body };
}

async function searchSymbol(query) {
  const { status, body } = await callApi("/symbol_search", { symbol: query, outputsize: 8 });
  if (status === 429 || body?.code === 429) return { rateLimited: true };
  return { matches: body?.data || [] };
}

async function confirmDaily(symbol) {
  const { status, body } = await callApi("/time_series", { symbol, interval: "1day", outputsize: 5 });
  if (status === 429 || body?.code === 429) return { rateLimited: true };
  const values = body?.values;
  return { ok: Array.isArray(values) && values.length > 0 };
}

async function main() {
  console.log("=".repeat(74));
  console.log("  TWELVE DATA COVERAGE CHECK v2 -- 22 instruments");
  console.log("=".repeat(74));
  console.log();

  const results = [];

  for (const [code, query, assetClass, wantTypes] of TARGETS) {
    await sleep(PACE_MS);
    const search = await searchSymbol(query);

    if (search.rateLimited) {
      console.log(`RATE LIMITED  ${code} (${query})`);
      results.push({ code, assetClass, status: "rate-limited" });
      continue;
    }
    if (!search.matches.length) {
      console.log(`NO MATCH      ${code} (${query}) -- nothing in their directory at all`);
      results.push({ code, assetClass, status: "no-match" });
      continue;
    }

    const candidateList = search.matches
      .map((m) => `${m.symbol} [${m.instrument_type}]`)
      .join(", ");
    console.log(`  candidates for ${code}: ${candidateList}`);

    const best = search.matches.find((m) =>
      wantTypes.some((t) => (m.instrument_type || "").toLowerCase().includes(t))
    );

    if (!best) {
      console.log(`NO GOOD MATCH ${code} (${query}) -- found results, but none of the right type`);
      results.push({ code, assetClass, status: "no-good-type-match", candidates: candidateList });
      continue;
    }

    await sleep(PACE_MS);
    const confirm = await confirmDaily(best.symbol);

    if (confirm.rateLimited) {
      console.log(`RATE LIMITED  ${code} -- picked ${best.symbol}, confirmation inconclusive`);
      results.push({ code, assetClass, status: "rate-limited", symbol: best.symbol });
    } else if (confirm.ok) {
      console.log(`COVERED       ${code} -> ${best.symbol} [${best.instrument_type}] -- daily data confirmed`);
      results.push({ code, assetClass, status: "covered", symbol: best.symbol, type: best.instrument_type });
    } else {
      console.log(`FOUND, NO DATA ${code} -> ${best.symbol} [${best.instrument_type}] -- no time_series data`);
      results.push({ code, assetClass, status: "found-no-data", symbol: best.symbol });
    }
  }

  console.log();
  console.log("-".repeat(74));
  console.log("SUMMARY BY ASSET CLASS");
  console.log("-".repeat(74));

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
  const rateLimitedCount = results.filter((r) => r.status === "rate-limited").length;
  console.log();
  console.log(`${coveredCount} of ${TARGETS.length} confirmed covered.` +
    (rateLimitedCount ? ` ${rateLimitedCount} inconclusive (rate-limited) -- rerun to resolve those.` : ""));
}

main();
