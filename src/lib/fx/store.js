// Storage for daily signal snapshots and the running paper P&L.
//
// Serverless functions keep no filesystem between invocations, so "what did
// we hold yesterday" and "what has this actually earned since we started
// watching" both have to live in the database. Rows are never updated after
// the fact except by a re-run of the same day, which is how a paper-trading
// record stays evidence rather than a story told afterwards.

import { sql } from "@/lib/db";

let schemaPromise = null;

export function ensureFxSchema() {
  if (!sql) return Promise.resolve();
  if (!schemaPromise) {
    schemaPromise = createSchema().catch((err) => {
      schemaPromise = null; // allow a retry after a transient failure
      throw err;
    });
  }
  return schemaPromise;
}

async function createSchema() {
  await sql`
    CREATE TABLE IF NOT EXISTS universe_signals (
      id SERIAL PRIMARY KEY,
      asof DATE NOT NULL,
      code TEXT NOT NULL,
      asset_class TEXT NOT NULL,
      strategy TEXT NOT NULL,
      price DOUBLE PRECISION NOT NULL,
      momentum DOUBLE PRECISION,
      trigger_level DOUBLE PRECISION,
      vol DOUBLE PRECISION,
      raw_signal DOUBLE PRECISION NOT NULL DEFAULT 0,
      signal DOUBLE PRECISION NOT NULL DEFAULT 0,
      target DOUBLE PRECISION NOT NULL DEFAULT 0,
      previous_target DOUBLE PRECISION NOT NULL DEFAULT 0,
      bars_held INTEGER NOT NULL DEFAULT 0,
      reason TEXT,
      daily_gross DOUBLE PRECISION NOT NULL DEFAULT 0,
      daily_financed DOUBLE PRECISION NOT NULL DEFAULT 0,
      stale_days INTEGER NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
  // One row per instrument per day per strategy. Re-running the cron on the
  // same day corrects that day rather than appending a second opinion.
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS universe_signals_unique
      ON universe_signals (asof, code, strategy)
  `;
  await sql`CREATE INDEX IF NOT EXISTS universe_signals_asof_idx ON universe_signals (asof DESC)`;

  // One row per calendar day: the equal-weight portfolio's return that day,
  // before and after OANDA's admin fee. The cumulative equity curve is
  // computed at query time from these rather than stored, so there is
  // nothing to drift out of sync with the underlying rows.
  await sql`
    CREATE TABLE IF NOT EXISTS universe_portfolio (
      asof DATE PRIMARY KEY,
      gross_return DOUBLE PRECISION NOT NULL,
      financed_return DOUBLE PRECISION NOT NULL,
      instruments_count INTEGER NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
}

export async function saveSignals(rows) {
  if (!sql || rows.length === 0) return 0;
  await ensureFxSchema();

  let written = 0;
  for (const r of rows) {
    await sql`
      INSERT INTO universe_signals (
        asof, code, asset_class, strategy, price, momentum, trigger_level, vol,
        raw_signal, signal, target, previous_target, bars_held, reason,
        daily_gross, daily_financed, stale_days
      ) VALUES (
        ${r.asof}, ${r.code}, ${r.assetClass}, ${r.strategy}, ${r.price},
        ${r.momentum}, ${r.trigger}, ${r.vol},
        ${r.rawSignal}, ${r.signal}, ${r.target}, ${r.previousTarget}, ${r.barsHeld}, ${r.reason},
        ${r.dailyGross}, ${r.dailyFinanced}, ${r.staleDays}
      )
      ON CONFLICT (asof, code, strategy) DO UPDATE SET
        price = EXCLUDED.price,
        momentum = EXCLUDED.momentum,
        trigger_level = EXCLUDED.trigger_level,
        vol = EXCLUDED.vol,
        raw_signal = EXCLUDED.raw_signal,
        signal = EXCLUDED.signal,
        target = EXCLUDED.target,
        previous_target = EXCLUDED.previous_target,
        bars_held = EXCLUDED.bars_held,
        reason = EXCLUDED.reason,
        daily_gross = EXCLUDED.daily_gross,
        daily_financed = EXCLUDED.daily_financed,
        stale_days = EXCLUDED.stale_days
    `;
    written += 1;
  }
  return written;
}

export async function savePortfolioDay(row) {
  if (!sql) return;
  await ensureFxSchema();
  await sql`
    INSERT INTO universe_portfolio (asof, gross_return, financed_return, instruments_count)
    VALUES (${row.asof}, ${row.gross}, ${row.financed}, ${row.instrumentsCount})
    ON CONFLICT (asof) DO UPDATE SET
      gross_return = EXCLUDED.gross_return,
      financed_return = EXCLUDED.financed_return,
      instruments_count = EXCLUDED.instruments_count
  `;
}

/** The most recent row per instrument — what the rule wants right now. */
export async function getLatestSignals(strategy) {
  if (!sql) return [];
  await ensureFxSchema();
  return sql`
    SELECT DISTINCT ON (code) *
    FROM universe_signals
    WHERE strategy = ${strategy}
    ORDER BY code, asof DESC
  `;
}

/** Recent position changes — the trade log, newest first. */
export async function getRecentChanges(strategy, limit = 30) {
  if (!sql) return [];
  await ensureFxSchema();
  return sql`
    SELECT * FROM universe_signals
    WHERE strategy = ${strategy} AND target IS DISTINCT FROM previous_target
    ORDER BY asof DESC, code
    LIMIT ${limit}
  `;
}

/** The full paper track record, oldest first — what the equity curve is built from. */
export async function getPortfolioSeries() {
  if (!sql) return [];
  await ensureFxSchema();
  return sql`SELECT * FROM universe_portfolio ORDER BY asof ASC`;
}
