// Daily closes from Yahoo's chart endpoint, for any instrument Yahoo quotes:
// futures ("GC=F"), index levels ("^GSPC"), or FX ("EURUSD=X").
//
// Treat this as what it is: a convenience feed, not your broker's prices.
// OANDA's own API is not available to this account -- EU retail clients were
// migrated to OANDA TMS Brokers S.A., which does not offer API access at all
// (see forex/DEPLOYMENT.md). Yahoo is the stand-in for now. Because the
// strategy decides once a day from the close, an end-of-day feed is not a
// compromise on decision quality -- only on how authoritative the exact
// price is, and on how long the feed can be trusted to keep working
// unannounced, since this is an undocumented endpoint.

const YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart";

/**
 * Fetch daily closes for one Yahoo ticker, oldest first.
 * Returns { dates: string[], closes: number[] }.
 */
export async function fetchDailyCloses(ticker, { signal, range = "25y" } = {}) {
  const url = `${YAHOO}/${encodeURIComponent(ticker)}?range=${range}&interval=1d`;
  const res = await fetch(url, {
    signal,
    cache: "no-store",
    headers: { "User-Agent": "Mozilla/5.0 (fxlab daily signal generator)" },
  });

  if (!res.ok) throw new Error(`Yahoo returned ${res.status} for ${ticker}`);

  const payload = await res.json();
  const result = payload?.chart?.result?.[0];
  if (!result) throw new Error(`Yahoo returned no data for ${ticker}`);

  const stamps = result.timestamp || [];
  const values = result.indicators?.quote?.[0]?.close || [];

  const dates = [];
  const closes = [];
  for (let i = 0; i < stamps.length; i++) {
    const close = values[i];
    if (close === null || close === undefined || close <= 0) continue;
    dates.push(new Date(stamps[i] * 1000).toISOString().slice(0, 10));
    closes.push(Number(close));
  }

  if (closes.length === 0) throw new Error(`Yahoo response for ${ticker} had no usable prices`);
  return { dates, closes };
}

/** Calendar days between the last bar and now — the staleness check. */
export function ageInDays(lastDate, now = new Date()) {
  const last = new Date(`${lastDate}T00:00:00Z`);
  return Math.floor((now.getTime() - last.getTime()) / 86_400_000);
}
