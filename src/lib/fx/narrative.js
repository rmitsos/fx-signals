// Plain-language trade narrative, shared between the dashboard and the email
// alert, so "why was this chosen" reads the same wherever you see it.
//
// This narrates the rule's mechanics -- direction, sizing, trigger distance,
// holding-period context -- never how "good" or "confident" a reading looks.
// There is no such thing as a more-convincing signal than another here: the
// only evidence is the aggregate backtest, not any single day's number. See
// src/app/page.js's "How to read this" section for the full caveat; this
// module assumes the reader has seen that once and doesn't repeat it every
// time -- it only restates the "sized by volatility, not by conviction"
// point inline, since that's the one most likely to be misread trade by
// trade.

function monthsFor(lookbackDays) {
  return Math.max(1, Math.round(lookbackDays / 21));
}

function fmtPct(value, digits = 1) {
  if (!Number.isFinite(value)) return null;
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

function fmtPrice(value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return null;
  if (v >= 100) return v.toFixed(2);
  if (v >= 1) return v.toFixed(4);
  return v.toFixed(5);
}

/**
 * Build the narrative for one instrument on one day.
 *
 * `n` is a normalized view: { target, previousTarget, momentum, trigger,
 * distanceToTrigger, barsHeld }. Use `fromDbRow` or `fromComputedRow` below
 * to get there from the two different shapes this data actually lives in.
 */
export function buildNarrative(n, { displayEquity, typicalHoldDays, lookbackDays = 252 } = {}) {
  const months = monthsFor(lookbackDays);
  const target = n.target;
  const previous = n.previousTarget;
  const changed = target !== previous;
  const dir = target > 0 ? "LONG" : target < 0 ? "SHORT" : "FLAT";
  const momentumText = fmtPct(n.momentum);
  const triggerText = fmtPrice(n.trigger);
  const distanceText = Number.isFinite(n.distanceToTrigger) ? fmtPct(Math.abs(n.distanceToTrigger)) : null;
  const notional =
    Number.isFinite(displayEquity) && target !== 0
      ? Math.abs(target * displayEquity).toLocaleString("en-GB", { maximumFractionDigits: 0 })
      : null;

  if (target === 0 && !changed) {
    return `Flat. No ${months}-month trend either way yet — waiting for the trailing return to move off zero.`;
  }

  const sizing =
    target !== 0
      ? ` Sized to ${Math.abs(target).toFixed(2)} of account notional${
          notional ? ` (~${notional} per ${Math.round(displayEquity).toLocaleString("en-GB")})` : ""
        } by volatility targeting — bigger for a quieter instrument, smaller for a wilder one, never by how strong this reading looks.`
      : "";

  const flipText = triggerText
    ? ` Reverses only if price crosses ${triggerText}${
        distanceText ? ` (${distanceText} away)` : ""
      } — the close from ${months} months ago.`
    : "";

  if (changed) {
    if (target === 0) {
      return `Went flat: the ${months}-month trend this position was riding just reversed.${flipText}`;
    }
    return `Went ${dir}: the trailing ${months}-month return turned ${
      target > 0 ? "positive" : "negative"
    }${momentumText ? ` (${momentumText})` : ""}.${sizing}${flipText}`;
  }

  const holdText =
    Number.isFinite(n.barsHeld) && n.barsHeld > 0
      ? `Held ${n.barsHeld} day${n.barsHeld === 1 ? "" : "s"}${
          typicalHoldDays ? ` — typical is ~${typicalHoldDays}.` : "."
        }`
      : "";
  return `Holding ${dir}${
    momentumText ? `, ${momentumText} over the trailing ${months} months` : ""
  }. ${holdText}${sizing}${flipText}`.trim();
}

/** Adapter for page.js's snake_case Postgres rows. */
export function fromDbRow(s) {
  const trigger = s.trigger_level === null ? NaN : Number(s.trigger_level);
  const price = Number(s.price);
  return {
    target: Number(s.target),
    previousTarget: Number(s.previous_target),
    momentum: s.momentum === null ? NaN : Number(s.momentum),
    trigger,
    distanceToTrigger: Number.isFinite(trigger) && Number.isFinite(price) ? trigger / price - 1 : NaN,
    barsHeld: Number(s.bars_held),
  };
}

/** Adapter for signals.js's camelCase computed rows (used by email.js). */
export function fromComputedRow(r) {
  return {
    target: r.target,
    previousTarget: r.previousTarget,
    momentum: r.momentum,
    trigger: r.trigger,
    distanceToTrigger: r.distanceToTrigger,
    barsHeld: r.barsHeld,
  };
}
