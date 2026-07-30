// Which instruments to watch and how the rule is configured.
//
// Everything here is deliberately a constant rather than a database row. A
// strategy whose parameters can be edited while it runs is a strategy you
// can talk yourself into changing after a bad week, which is the failure
// mode this whole project exists to design around. Changing these means a
// commit, a diff, and a deploy.
//
// check_universe.py originally tested 22 instruments and assumed all of them
// were available as OANDA CFDs -- that assumption was wrong. Confirmed by
// hand, symbol by symbol, on the actual OANDA EU (TMS Brokers) account this
// dashboard serves: only 14 of the 22 exist. Bonds and agriculture drop out
// entirely, not just a name or two. check_universe_oanda.py re-ran the exact
// same backtest on exactly these 14 rather than assuming the full-universe
// number would carry over: gross Sharpe 0.50, financed Sharpe 0.29 (t=1.6)
// -- essentially unchanged from the 22-instrument result (0.54 / 0.28,
// t=1.5). Still marginal, still not proven, but losing bonds and
// agriculture cost almost nothing. See forex/README.md.

// code is deliberately OANDA's own symbol name where one exists (US500, not
// SPX), so what this dashboard says IS what you would type into the
// platform -- no translation step between reading a signal and finding the
// instrument. ticker is the Yahoo ticker used to fetch prices; identical set
// to check_universe_oanda.py's OANDA_UNIVERSE. Keep the two in sync by hand.
export const UNIVERSE = [
  { code: "GOLD", ticker: "GC=F", label: "Gold", assetClass: "metals" },
  { code: "SILVER", ticker: "SI=F", label: "Silver", assetClass: "metals" },
  { code: "WTICO", ticker: "CL=F", label: "WTI Crude", assetClass: "energy" },
  { code: "BCO", ticker: "BZ=F", label: "Brent Crude", assetClass: "energy" },
  { code: "NATGAS", ticker: "NG=F", label: "Natural Gas", assetClass: "energy" },
  { code: "US500", ticker: "^GSPC", label: "S&P 500", assetClass: "equity index" },
  { code: "DE30", ticker: "^GDAXI", label: "DAX", assetClass: "equity index" },
  { code: "UK100", ticker: "^FTSE", label: "FTSE 100", assetClass: "equity index" },
  { code: "JP225", ticker: "^N225", label: "Nikkei 225", assetClass: "equity index" },
  { code: "AU200", ticker: "^AXJO", label: "ASX 200", assetClass: "equity index" },
  { code: "EURUSD", ticker: "EURUSD=X", label: "Euro / US Dollar", assetClass: "currencies" },
  { code: "GBPUSD", ticker: "GBPUSD=X", label: "Sterling / US Dollar", assetClass: "currencies" },
  { code: "USDJPY", ticker: "USDJPY=X", label: "US Dollar / Yen", assetClass: "currencies" },
  { code: "AUDUSD", ticker: "AUDUSD=X", label: "Aussie / US Dollar", assetClass: "currencies" },
];

// Mirrors DEFAULTS in strategy.js and STRATEGY in forex/check_universe.py.
export const STRATEGY = {
  strategy: "tsm",
  lookback: 252,
  maxHold: 0, // no cap -- winners run until the trend itself reverses
  volTarget: 0.1,
  volWindow: 60,
  maxLeverage: 1.0,
  rebalanceBand: 0.25,
};

// One-way transaction cost assumption for the live paper P&L, in basis
// points. Matches the "2 bp" column used for the headline verdict in
// check_universe.py -- reasonable for liquid futures/index CFDs, optimistic
// for the thinner agricultural contracts.
export const COST_BPS = 2.0;

// OANDA's CFD admin fee, annualised, per asset class -- charged whether you
// are long or short (long pays basis+fee, short receives basis-fee), so it
// is a flat drag on notional held rather than a cost of one direction. Same
// table as check_universe.py; see that file for sourcing.
export const ADMIN_FEES = {
  metals: 0.01,
  energy: 0.025,
  "equity index": 0.025,
  currencies: 0.01,
};

// Reference point from the 25-year backtest, not used in any calculation --
// just so "held 12 days" can be read against "usually around 40".
export const TYPICAL_HOLD_DAYS = 40;

// Notional the position sizes are expressed against, so the page can show
// money rather than fractions. Display only -- nothing here places an
// order, so this number cannot lose you anything.
export const DISPLAY_EQUITY = Number(process.env.FX_DISPLAY_EQUITY || 10000);

// Daily bars needed before the first signal is trustworthy: the 252-day
// lookback, the 60-day volatility window, and headroom. Matches WARMUP in
// check_universe.py.
export const MIN_BARS = STRATEGY.lookback + STRATEGY.volWindow + 20;
