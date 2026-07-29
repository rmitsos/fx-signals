// Which instruments to watch and how the rule is configured.
//
// Everything here is deliberately a constant rather than a database row. A
// strategy whose parameters can be edited while it runs is a strategy you
// can talk yourself into changing after a bad week, which is the failure
// mode this whole project exists to design around. Changing these means a
// commit, a diff, and a deploy.
//
// This is the exact configuration check_universe.py measured on 25 years of
// real prices: 252-day (12-month) momentum, no holding cap, equal risk per
// instrument, across four asset classes. Gross Sharpe 0.54 (t=2.9 -- real).
// After OANDA's CFD financing: Sharpe 0.28 (t=1.5 -- no longer distinguishable
// from luck). See forex/README.md before treating this as more than a paper
// record worth watching.

// name, Yahoo ticker, asset class -- identical to UNIVERSE in
// forex/check_universe.py. Keep the two lists in sync by hand; the parity
// test checks the math, not that the instrument lists match.
export const UNIVERSE = [
  { code: "GOLD", ticker: "GC=F", label: "Gold", assetClass: "metals" },
  { code: "SILVER", ticker: "SI=F", label: "Silver", assetClass: "metals" },
  { code: "COPPER", ticker: "HG=F", label: "Copper", assetClass: "metals" },
  { code: "WTI", ticker: "CL=F", label: "WTI Crude", assetClass: "energy" },
  { code: "BRENT", ticker: "BZ=F", label: "Brent Crude", assetClass: "energy" },
  { code: "NATGAS", ticker: "NG=F", label: "Natural Gas", assetClass: "energy" },
  { code: "CORN", ticker: "ZC=F", label: "Corn", assetClass: "agriculture" },
  { code: "WHEAT", ticker: "ZW=F", label: "Wheat", assetClass: "agriculture" },
  { code: "SOYBEANS", ticker: "ZS=F", label: "Soybeans", assetClass: "agriculture" },
  { code: "SUGAR", ticker: "SB=F", label: "Sugar", assetClass: "agriculture" },
  { code: "SPX", ticker: "^GSPC", label: "S&P 500", assetClass: "equity index" },
  { code: "NDX", ticker: "^NDX", label: "Nasdaq 100", assetClass: "equity index" },
  { code: "DAX", ticker: "^GDAXI", label: "DAX", assetClass: "equity index" },
  { code: "FTSE", ticker: "^FTSE", label: "FTSE 100", assetClass: "equity index" },
  { code: "NIKKEI", ticker: "^N225", label: "Nikkei 225", assetClass: "equity index" },
  { code: "ASX", ticker: "^AXJO", label: "ASX 200", assetClass: "equity index" },
  { code: "UST10Y", ticker: "ZN=F", label: "US 10y Note", assetClass: "bonds" },
  { code: "UST30Y", ticker: "ZB=F", label: "US 30y Bond", assetClass: "bonds" },
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
  agriculture: 0.025,
  "equity index": 0.025,
  bonds: 0.025,
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
