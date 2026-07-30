import { connection } from "next/server";
import {
  UNIVERSE, STRATEGY, DISPLAY_EQUITY, TYPICAL_HOLD_DAYS, ADMIN_FEES,
} from "@/lib/fx/config";
import { getLatestSignals, getRecentChanges, getPortfolioSeries } from "@/lib/fx/store";
import { STALE_AFTER_DAYS } from "@/lib/fx/signals";
import { buildNarrative, fromDbRow } from "@/lib/fx/narrative";

// Access is enforced in proxy.js before this ever renders; robots.js and the
// layout's metadata keep it out of search regardless.

const CLASS_ORDER = ["equity index", "bonds", "metals", "energy", "agriculture", "currencies"];
const CLASS_LABEL = {
  "equity index": "Equity indices",
  bonds: "Bonds",
  metals: "Metals",
  energy: "Energy",
  agriculture: "Agriculture",
  currencies: "Currencies",
};
const LABEL_BY_CODE = Object.fromEntries(UNIVERSE.map((u) => [u.code, u.label]));

function slug(assetClass) {
  return assetClass.replace(/\s+/g, "-");
}

function fmtPrice(value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return "—";
  if (v >= 100) return v.toFixed(2);
  if (v >= 1) return v.toFixed(4);
  return v.toFixed(5);
}

function pct(value, digits = 1) {
  if (!Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

function State({ target }) {
  if (target > 0) {
    return <span className="font-mono text-sm font-bold text-fin">LONG {target.toFixed(2)}</span>;
  }
  if (target < 0) {
    return <span className="font-mono text-sm font-bold text-enr">SHORT {Math.abs(target).toFixed(2)}</span>;
  }
  return <span className="font-mono text-sm font-bold text-muted">FLAT</span>;
}

// A momentum reading as a bar centred on zero, not a channel position like
// the old FX/Donchian page -- there is one number here (the trailing
// return), not two levels to sit between.
function MomentumBar({ momentum }) {
  if (!Number.isFinite(momentum)) return <p className="text-xs text-muted">Not enough history yet.</p>;
  const CLAMP = 0.30; // beyond +/-30% the bar is simply full; the number alongside it is exact
  const frac = Math.max(-1, Math.min(1, momentum / CLAMP));
  const positive = frac >= 0;
  const width = Math.abs(frac) * 50;

  return (
    <div>
      <div className="relative h-2 rounded-sm bg-tint">
        <div className="absolute left-1/2 top-0 h-full w-px bg-rule" />
        <div
          className={`absolute top-0 h-full rounded-sm ${positive ? "bg-fin" : "bg-enr"}`}
          style={positive ? { left: "50%", width: `${width}%` } : { right: "50%", width: `${width}%` }}
        />
      </div>
      <p className="mt-1 font-mono text-xs text-muted">
        {pct(momentum)} over the {Math.round(STRATEGY.lookback / 21)}-month lookback
      </p>
    </div>
  );
}

function InstrumentCard({ s }) {
  const target = Number(s.target);
  const previous = Number(s.previous_target);
  const price = Number(s.price);
  const momentum = s.momentum === null ? NaN : Number(s.momentum);
  const trigger = s.trigger_level === null ? NaN : Number(s.trigger_level);
  const changed = target !== previous;
  const stale = s.stale_days > STALE_AFTER_DAYS;
  const distance = Number.isFinite(trigger) ? trigger / price - 1 : NaN;

  return (
    <article className="border-b border-rule px-4 py-4">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h3 className="font-mono text-sm font-bold tracking-tight">{s.code}</h3>
          <span className="text-xs text-muted">{LABEL_BY_CODE[s.code] || s.code}</span>
          <span className="font-mono text-sm text-ink-2 tabular-nums">{fmtPrice(price)}</span>
          {stale && <span className="font-mono text-xs text-enr">stale {s.stale_days}d</span>}
        </div>
        <State target={target} />
      </header>

      <p className="mb-2 text-sm text-ink-2">
        {buildNarrative(fromDbRow(s), {
          displayEquity: DISPLAY_EQUITY,
          typicalHoldDays: TYPICAL_HOLD_DAYS,
          lookbackDays: STRATEGY.lookback,
        })}
      </p>

      <MomentumBar momentum={momentum} />

      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted">Flips at</dt>
          <dd className="tabular-nums">
            {Number.isFinite(trigger) ? (
              <>{fmtPrice(trigger)} <span className="text-muted">({pct(distance)})</span></>
            ) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Held</dt>
          <dd className="tabular-nums">
            {s.bars_held > 0 ? `${s.bars_held}d (avg ~${TYPICAL_HOLD_DAYS}d)` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Realized vol</dt>
          <dd className="tabular-nums">{s.vol === null ? "—" : pct(Number(s.vol))}</dd>
        </div>
        <div>
          <dt className="text-muted">Today, gross / financed</dt>
          <dd className="tabular-nums">
            {pct(Number(s.daily_gross), 2)} / {pct(Number(s.daily_financed), 2)}
          </dd>
        </div>
      </dl>

      {changed && (
        <p className="mt-3 border-l-2 border-fin pl-3 font-mono text-xs">
          Change today: {previous.toFixed(2)} → {target.toFixed(2)} ={" "}
          <strong>
            {target > previous ? "BUY" : "SELL"}{" "}
            {Math.abs((target - previous) * DISPLAY_EQUITY).toLocaleString("en-GB", { maximumFractionDigits: 0 })}
          </strong>{" "}
          notional per {DISPLAY_EQUITY.toLocaleString("en-GB")} of account
        </p>
      )}
    </article>
  );
}

function ClassRollup({ signalsByClass }) {
  return (
    <table className="w-full border-collapse font-mono text-xs">
      <thead>
        <tr className="border-b border-rule text-left text-muted">
          <th className="py-1 pr-2 font-normal">Asset class</th>
          <th className="py-1 pr-2 font-normal">Admin fee</th>
          <th className="py-1 pr-2 text-right font-normal">Long</th>
          <th className="py-1 pr-2 text-right font-normal">Short</th>
          <th className="py-1 text-right font-normal">Flat</th>
        </tr>
      </thead>
      <tbody>
        {CLASS_ORDER.filter((c) => signalsByClass[c]?.length).map((c) => {
          const rows = signalsByClass[c];
          const long = rows.filter((r) => Number(r.target) > 0).length;
          const short = rows.filter((r) => Number(r.target) < 0).length;
          const flat = rows.length - long - short;
          return (
            <tr key={c} className="border-b border-rule/50">
              <td className="py-1 pr-2">{CLASS_LABEL[c]}</td>
              <td className="py-1 pr-2 text-muted">{pct(ADMIN_FEES[c], 1)}/yr</td>
              <td className="py-1 pr-2 text-right text-fin tabular-nums">{long || "—"}</td>
              <td className="py-1 pr-2 text-right text-enr tabular-nums">{short || "—"}</td>
              <td className="py-1 text-right text-muted tabular-nums">{flat || "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// Server-rendered SVG, no charting library and no client JS -- consistent
// with the rest of this dependency-free kit. Two lines: gross (what the
// strategy earns) and financed (what OANDA's admin fee leaves you), so the
// gap between them is the thing to watch, not just the level of either one.
function EquityChart({ series }) {
  if (series.length < 2) {
    return (
      <p className="text-sm text-ink-2">
        Not enough days tracked yet to draw a curve. Come back after a few
        updates — this chart is the paper record building in real time, not a
        backtest.
      </p>
    );
  }

  const W = 600, H = 120, PAD = 4;
  let gEq = 1, fEq = 1;
  const gross = [1], financed = [1];
  for (const row of series) {
    gEq *= 1 + Number(row.gross_return);
    fEq *= 1 + Number(row.financed_return);
    gross.push(gEq);
    financed.push(fEq);
  }

  const all = [...gross, ...financed];
  const min = Math.min(...all), max = Math.max(...all);
  const span = max - min || 1;

  const toPoints = (series) =>
    series
      .map((v, i) => {
        const x = PAD + (i / (series.length - 1)) * (W - 2 * PAD);
        const y = H - PAD - ((v - min) / span) * (H - 2 * PAD);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

  const last = series.length - 1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 140 }}>
      <line x1={PAD} y1={H - PAD - ((1 - min) / span) * (H - 2 * PAD)}
            x2={W - PAD} y2={H - PAD - ((1 - min) / span) * (H - 2 * PAD)}
            stroke="var(--rule)" strokeWidth="1" />
      <polyline points={toPoints(gross)} fill="none" stroke="var(--muted)" strokeWidth="1.5" />
      <polyline points={toPoints(financed)} fill="none"
                stroke={fEq >= 1 ? "var(--fin)" : "var(--enr)"} strokeWidth="2" />
    </svg>
  );
}

export default async function UniversePage() {
  // Stop prerendering. Without this Next serves a copy of the page frozen at
  // build time — which for a page whose entire job is to show today's signal
  // is worse than showing nothing, because stale positions look current.
  await connection();

  const activeCodes = UNIVERSE.map((u) => u.code);
  const [signals, changes, portfolio] = await Promise.all([
    getLatestSignals(STRATEGY.strategy, activeCodes),
    getRecentChanges(STRATEGY.strategy, activeCodes, 30),
    getPortfolioSeries(),
  ]);

  const asof = signals.length
    ? signals.map((s) => new Date(s.asof).toISOString().slice(0, 10)).sort().at(-1)
    : null;
  const todaysChanges = signals.filter((s) => Number(s.target) !== Number(s.previous_target));

  const signalsByClass = {};
  for (const s of signals) (signalsByClass[s.asset_class] ??= []).push(s);

  let gEq = 1, fEq = 1;
  for (const row of portfolio) {
    gEq *= 1 + Number(row.gross_return);
    fEq *= 1 + Number(row.financed_return);
  }
  let peak = 1, worstDD = 0, eq = 1;
  for (const row of portfolio) {
    eq *= 1 + Number(row.financed_return);
    peak = Math.max(peak, eq);
    worstDD = Math.min(worstDD, eq / peak - 1);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-0 py-6">
      <header className="border-b border-rule px-4 pb-4">
        <h1 className="font-serif text-2xl font-bold tracking-tight">Trend signals</h1>
        <p className="mt-1 font-mono text-xs text-muted">
          {STRATEGY.lookback}-day momentum · no holding cap · vol target{" "}
          {(STRATEGY.volTarget * 100).toFixed(0)}% · max leverage {STRATEGY.maxLeverage.toFixed(1)}x ·{" "}
          {UNIVERSE.length} instruments
          {asof ? ` · data to ${asof}` : ""}
        </p>
      </header>

      <div className="border-b border-rule bg-tint px-4 py-3 text-xs text-ink-2">
        <p className="mb-2">
          <strong className="text-ink">This is a paper record, not advice.</strong> No
          order is placed by anything here and no broker is connected.
        </p>
        <p className="mb-2">
          These 14 instruments are exactly what was confirmed, symbol by
          symbol, on the actual OANDA EU account this dashboard serves — the
          original research covered 22, but bonds and agriculture don&apos;t
          exist as CFDs here. Re-tested on exactly this narrower set rather
          than assuming the number would carry over: gross Sharpe{" "}
          <strong>0.50</strong> (financed <strong>0.29</strong>, t=1.6) on 25
          years of real prices — essentially unchanged from the full
          22-instrument result (0.54 / 0.28, t=1.5). Losing bonds and
          agriculture cost almost nothing; metals (gold and silver) carried
          most of the edge here.
        </p>
        <p>
          Exit is trend reversal only, exactly as tested — <strong>no
          stop-loss</strong> is modelled or shown, because adding one now would
          be a strategy variant nobody has measured. See{" "}
          <code className="font-mono">forex/README.md</code> for the full
          result before treating this as more than something to watch.
        </p>
      </div>

      {signals.length > 0 && (
        <nav className="flex flex-wrap gap-x-3 gap-y-1 border-b border-rule bg-tint px-4 py-2 font-mono text-xs">
          <a href="#how-to-read" className="text-ink-2 underline decoration-rule underline-offset-2">
            How to read this
          </a>
          {CLASS_ORDER.filter((c) => signalsByClass[c]?.length).map((c) => (
            <a key={c} href={`#${slug(c)}`} className="text-ink-2 underline decoration-rule underline-offset-2">
              {CLASS_LABEL[c]}
            </a>
          ))}
          <a href="#pnl" className="text-ink-2 underline decoration-rule underline-offset-2">P&amp;L</a>
        </nav>
      )}

      <details id="how-to-read" className="border-b border-rule px-4 py-3 text-xs text-ink-2">
        <summary className="cursor-pointer font-mono uppercase tracking-wide text-muted">
          How to read this
        </summary>
        <dl className="mt-3 space-y-3">
          <div>
            <dt className="font-bold text-ink">LONG / SHORT / FLAT, with a number</dt>
            <dd className="mt-0.5">
              Direction, and the size of the position as a fraction of account
              notional (1.00 = full account size, the maximum this strategy
              ever takes). Size comes from volatility targeting — quieter
              instruments get a bigger fraction, wilder ones a smaller one —
              never from how strong the signal looks.
            </dd>
          </div>
          <div>
            <dt className="font-bold text-ink">The momentum bar</dt>
            <dd className="mt-0.5">
              Shows the instrument&apos;s trailing 12-month return — that&apos;s
              the entire signal. Positive, it&apos;s long; negative, short.{" "}
              <strong>The bar&apos;s width is not a confidence score.</strong> A
              +3% reading is not a &quot;weaker&quot; long than a +25% reading —
              both are simply long, and the strategy sizes both the same way
              (by volatility, not by momentum strength). There is no way to
              declare one instrument&apos;s signal &quot;better&quot; than
              another&apos;s on a given day — the only evidence that exists is
              the aggregate one above (Sharpe 0.50 / 0.29, t=1.6), which is a
              property of following the rule uniformly across the whole book,
              not of any single reading looking more convincing.
            </dd>
          </div>
          <div>
            <dt className="font-bold text-ink">Flips at</dt>
            <dd className="mt-0.5">
              The exact price from 12 months ago that today&apos;s price is
              being compared against. Cross it, and the sign of the trailing
              return — and the position — flips.
            </dd>
          </div>
          <div>
            <dt className="font-bold text-ink">Held</dt>
            <dd className="mt-0.5">
              Days since the position last changed direction, against the
              ~{TYPICAL_HOLD_DAYS}-day average from the 25-year backtest.
              There is no cap — a trend is allowed to run for as long as it
              keeps going, which is also why some positions will sit for
              months.
            </dd>
          </div>
          <div>
            <dt className="font-bold text-ink">Realized vol / Today, gross / financed</dt>
            <dd className="mt-0.5">
              Realized vol is the instrument&apos;s own recent annualised
              volatility, which is what sizes the position. Today&apos;s
              gross/financed figures are what that position earned today
              specifically — before, and after, OANDA&apos;s admin fee — and
              feed directly into the paper P&amp;L chart below.
            </dd>
          </div>
        </dl>
      </details>

      {signals.length === 0 ? (
        <div className="px-4 py-10 text-sm text-ink-2">
          <p className="mb-2">No signals stored yet.</p>
          <p className="text-muted">
            Visit <code className="font-mono">/api/signals</code> once to run the first
            update, or wait for tonight&apos;s cron.
          </p>
        </div>
      ) : (
        <>
          <section
            className={
              todaysChanges.length > 0
                ? "border-b border-rule bg-fin/10 px-4 py-3"
                : "border-b border-rule px-4 py-3"
            }
          >
            <h2 className="mb-1 font-mono text-xs uppercase tracking-wide text-muted">
              {todaysChanges.length > 0 ? `⚠ ${todaysChanges.length} change${todaysChanges.length > 1 ? "s" : ""} today` : "Today"}
            </h2>
            {todaysChanges.length === 0 ? (
              <p className="text-sm text-ink-2">
                No changes. Hold what you have.{" "}
                <span className="text-muted">
                  Normal most days — this rule changes its mind a handful of
                  times a year per instrument, not daily.
                </span>
              </p>
            ) : (
              <ul className="space-y-2">
                {todaysChanges.map((s) => (
                  <li key={s.code} className="font-mono text-sm">
                    <div>
                      <strong className={Number(s.target) > Number(s.previous_target) ? "text-fin" : "text-enr"}>
                        {Number(s.target) > Number(s.previous_target) ? "BUY " : "SELL"}
                      </strong>{" "}
                      {s.code}{" "}
                      <span className="text-muted">({LABEL_BY_CODE[s.code] || s.code})</span> →{" "}
                      {Number(s.target).toFixed(2)}
                    </div>
                    <p className="mt-0.5 font-sans text-xs text-ink-2">
                      {buildNarrative(fromDbRow(s), {
                        displayEquity: DISPLAY_EQUITY,
                        typicalHoldDays: TYPICAL_HOLD_DAYS,
                        lookbackDays: STRATEGY.lookback,
                      })}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="border-b border-rule px-4 py-4">
            <h2 className="mb-2 font-mono text-xs uppercase tracking-wide text-muted">
              By asset class
            </h2>
            <ClassRollup signalsByClass={signalsByClass} />
          </section>

          <section id="pnl" className="border-b border-rule px-4 py-4">
            <h2 className="mb-1 font-mono text-xs uppercase tracking-wide text-muted">
              Paper P&amp;L since tracking began
            </h2>
            <p className="mb-2 font-mono text-xs text-muted">
              {portfolio.length} day{portfolio.length === 1 ? "" : "s"} tracked
              {portfolio.length > 0 && (
                <>
                  {" "}· gross {pct(gEq - 1)} · financed {pct(fEq - 1)} · worst fall so far{" "}
                  {pct(worstDD)}
                </>
              )}
            </p>
            <EquityChart series={portfolio} />
            <p className="mt-2 font-mono text-xs text-muted">
              <span className="text-ink-2">— grey: gross</span>{" "}
              <span className={fEq >= 1 ? "text-fin" : "text-enr"}>— coloured: after OANDA financing</span>
            </p>
          </section>

          {CLASS_ORDER.filter((c) => signalsByClass[c]?.length).map((c) => {
            const rows = signalsByClass[c];
            const hasActivity = rows.some(
              (r) => Number(r.target) !== 0 || Number(r.target) !== Number(r.previous_target)
            );
            const long = rows.filter((r) => Number(r.target) > 0).length;
            const short = rows.filter((r) => Number(r.target) < 0).length;

            return (
              <details key={c} id={slug(c)} open={hasActivity}>
                <summary className="cursor-pointer border-b border-rule bg-tint px-4 py-2 font-mono text-xs uppercase tracking-wide text-muted">
                  {CLASS_LABEL[c]}{" "}
                  <span className="normal-case text-muted/70">
                    ({rows.length} · {long} long, {short} short, {rows.length - long - short} flat)
                  </span>
                </summary>
                {rows
                  .sort((a, b) => a.code.localeCompare(b.code))
                  .map((s) => (
                    <InstrumentCard key={s.code} s={s} />
                  ))}
              </details>
            );
          })}
        </>
      )}

      {changes.length > 0 && (
        <section className="px-4 py-5">
          <h2 className="mb-2 font-mono text-xs uppercase tracking-wide text-muted">
            Position changes, newest first
          </h2>
          <ul className="space-y-1 font-mono text-xs tabular-nums">
            {changes.map((c) => (
              <li key={c.id} className="flex gap-3 text-ink-2">
                <span className="text-muted">{new Date(c.asof).toISOString().slice(0, 10)}</span>
                <span className="w-20">{c.code}</span>
                <span>{Number(c.previous_target).toFixed(2)} → {Number(c.target).toFixed(2)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">
            Written the day the rule said it, before the outcome was known.
            That is what makes this a record rather than a story told
            afterwards.
          </p>
        </section>
      )}
    </div>
  );
}
