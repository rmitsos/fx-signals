// Orchestration: prices in, explained signals and paper P&L out.

import { UNIVERSE, STRATEGY, COST_BPS, ADMIN_FEES, MIN_BARS } from "./config";
import { fetchDailyCloses, ageInDays } from "./prices";
import { runStrategy, explain, dailyPnl } from "./strategy";
import { saveSignals, savePortfolioDay } from "./store";

const STALE_AFTER_DAYS = 5;

/**
 * Compute today's signal, reasoning, and paper P&L contribution for every
 * instrument.
 *
 * One dead feed must not take the others down with it, so failures are
 * collected per instrument rather than thrown. A partial answer with a
 * visible gap is more useful than no answer, as long as the gap stays
 * visible -- which is why `errors` is surfaced on the page rather than only
 * logged.
 */
export async function computeSignals() {
  const rows = [];
  const errors = [];

  const settled = await Promise.allSettled(
    UNIVERSE.map(async (inst) => ({ inst, data: await fetchDailyCloses(inst.ticker) }))
  );

  for (let i = 0; i < settled.length; i++) {
    const outcome = settled[i];
    const inst = UNIVERSE[i];

    if (outcome.status === "rejected") {
      errors.push(`${inst.code}: ${outcome.reason?.message || outcome.reason}`);
      continue;
    }

    const { dates, closes } = outcome.value.data;
    if (closes.length < MIN_BARS) {
      errors.push(`${inst.code}: only ${closes.length} bars, need ${MIN_BARS}`);
      continue;
    }

    const result = runStrategy(closes, STRATEGY);
    const view = explain(result);
    const pnl = dailyPnl(result, closes.length - 1, {
      costBps: COST_BPS,
      adminFeeAnnual: ADMIN_FEES[inst.assetClass] ?? 0,
    });

    const asof = dates[dates.length - 1];
    const staleDays = ageInDays(asof);

    rows.push({
      asof,
      code: inst.code,
      label: inst.label,
      assetClass: inst.assetClass,
      strategy: STRATEGY.strategy,
      staleDays,
      dailyGross: pnl.gross,
      dailyFinanced: pnl.financed,
      ...view,
    });
  }

  return { rows, errors, strategy: STRATEGY };
}

/** Compute, persist, and roll up the portfolio's day. Called by the cron route. */
export async function runSignalUpdate() {
  const { rows, errors } = await computeSignals();

  const stale = rows.filter((r) => r.staleDays > STALE_AFTER_DAYS);
  for (const r of stale) {
    errors.push(`${r.code}: data is ${r.staleDays} days old (last bar ${r.asof})`);
  }

  let written = 0;
  try {
    written = await saveSignals(rows);
  } catch (err) {
    errors.push(`database write failed: ${err?.message || err}`);
  }

  // Equal-weight portfolio day: the average of what every instrument that
  // priced successfully earned today. A day with a dead feed uses whatever
  // instruments did report -- a graceful degradation, not a silent one, since
  // the gap is visible in both `errors` and `instrumentsCount`.
  let portfolioRow = null;
  if (rows.length > 0) {
    const asof = rows[0].asof;
    const gross = mean(rows.map((r) => r.dailyGross));
    const financed = mean(rows.map((r) => r.dailyFinanced));
    portfolioRow = { asof, gross, financed, instrumentsCount: rows.length };
    try {
      await savePortfolioDay(portfolioRow);
    } catch (err) {
      errors.push(`portfolio write failed: ${err?.message || err}`);
    }
  }

  const changes = rows.filter((r) => r.target !== r.previousTarget);

  return {
    ok: rows.length > 0,
    computed: rows.length,
    written,
    changes,
    portfolio: portfolioRow,
    errors,
  };
}

function mean(values) {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
}

export { STALE_AFTER_DAYS };
