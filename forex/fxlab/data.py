"""Price loaders.

Three sources, in order of how much you should trust them:

  csv       -- your broker's own export. Always the best option, because it
               is the only one that reflects the prices you can actually
               trade, including your spread.
  stooq     -- free daily FX history, no API key, no dependency.
  yfinance  -- convenient, but Yahoo's FX series are indicative mid quotes
               with gaps and the occasional bad print. Fine for a first look,
               not for a decision.

`synthetic` is here for testing the engine without a network.
"""

from __future__ import annotations

import io
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


def from_csv(path: str, date_col: str = "Date", price_col: str = "Close") -> pd.Series:
    """Load a broker or vendor CSV export."""
    df = pd.read_csv(path)
    if date_col not in df.columns or price_col not in df.columns:
        raise ValueError(
            f"{path}: expected columns {date_col!r} and {price_col!r}, found {list(df.columns)}"
        )
    s = pd.Series(df[price_col].to_numpy(dtype=float), index=pd.to_datetime(df[date_col]))
    return s.sort_index().dropna()


def from_stooq(symbol: str) -> pd.Series:
    """Daily closes from stooq.com. `symbol` is like 'eurusd', 'usdjpy'."""
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    if "Date" not in raw.split("\n", 1)[0]:
        raise RuntimeError(f"stooq returned no data for {symbol!r}: {raw[:200]!r}")
    df = pd.read_csv(io.StringIO(raw))
    s = pd.Series(df["Close"].to_numpy(dtype=float), index=pd.to_datetime(df["Date"]))
    return s.sort_index().dropna()


def from_yfinance(ticker: str, period: str = "max") -> pd.Series:
    """Daily closes via yfinance, e.g. 'EURUSD=X'.

    Recent yfinance returns MultiIndex columns even for a single ticker, so
    the result is flattened defensively.
    """
    import yfinance as yf

    data = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    if data.empty:
        raise RuntimeError(f"No data returned for {ticker!r}. Check the symbol.")
    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.astype(float).dropna().sort_index()


def synthetic(
    n: int = 252 * 20,
    drift: float = 0.0,
    vol: float = 0.08,
    trend_strength: float = 0.0,
    seed: int = 0,
    start: str = "2005-01-03",
) -> pd.Series:
    """Geometric random walk, optionally with autocorrelated drift.

    `trend_strength` in (0, 1) makes the drift itself an AR(1) process, which
    is the only condition under which a momentum rule can work. At 0.0 you
    get a pure random walk -- run your strategies against that first, because
    anything that looks profitable on it is measuring your own bias.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=n)
    shocks = rng.standard_normal(n) * vol / np.sqrt(252.0)

    if trend_strength > 0.0:
        mu = np.zeros(n)
        for i in range(1, n):
            mu[i] = trend_strength * mu[i - 1] + (1 - trend_strength) * shocks[i]
        rets = drift / 252.0 + mu + shocks * 0.5
    else:
        rets = drift / 252.0 + shocks

    return pd.Series(100.0 * np.exp(np.cumsum(rets)), index=idx)


def load(spec: str, period: str = "max") -> pd.Series:
    """Dispatch on a 'source:identifier' spec.

    Examples: 'csv:/path/eurusd.csv', 'stooq:eurusd', 'yf:EURUSD=X',
    'synthetic:seed=1'.
    """
    source, _, ident = spec.partition(":")
    if not ident:
        raise ValueError(f"spec must look like 'source:identifier', got {spec!r}")
    if source == "csv":
        return from_csv(ident)
    if source == "stooq":
        return from_stooq(ident)
    if source in ("yf", "yfinance"):
        return from_yfinance(ident, period)
    if source == "synthetic":
        kwargs = dict(p.split("=") for p in ident.split(",") if "=" in p)
        return synthetic(**{k: float(v) if "." in v else int(v) for k, v in kwargs.items()})
    raise ValueError(f"unknown source {source!r}; use csv, stooq, yf or synthetic")
