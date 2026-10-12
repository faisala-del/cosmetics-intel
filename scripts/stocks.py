"""Fetches last close, day change and 52-week range with yfinance.

yfinance is an unofficial wrapper around Yahoo Finance. It is free but can
break without notice. If it does, swap fetch_one() for Finnhub or Alpha
Vantage; the rest of the project only needs the dict shape below.
"""
from __future__ import annotations

import datetime as dt


def fetch_one(symbol: str) -> dict:
    import yfinance as yf  # imported lazily

    hist = yf.Ticker(symbol).history(period="1y", auto_adjust=False)
    close = hist["Close"].dropna()
    if close.empty:
        raise ValueError("no price history returned")
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else None
    return {
        "last": round(last, 4),
        "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "date": close.index[-1].strftime("%Y-%m-%d"),
        "low52": round(float(hist["Low"].min()), 4),
        "high52": round(float(hist["High"].max()), 4),
    }


def fetch_all(groups: list[dict], previous: dict | None = None) -> tuple[dict, list[str]]:
    """Returns (stocks_json, errors). A failed ticker reuses its last known
    values and is marked stale so the site never shows a silent blank."""
    prev_rows = {}
    for g in (previous or {}).get("groups", []):
        for r in g.get("rows", []):
            prev_rows[r["symbol"]] = r

    errors: list[str] = []
    out_groups = []
    for g in groups:
        rows = []
        for spec in g["rows"]:
            row = {"symbol": spec["symbol"], "name": spec["name"], "ccy": spec.get("ccy", "USD"),
                   "last": None, "change_pct": None, "date": None, "low52": None, "high52": None,
                   "stale": False}
            try:
                row.update(fetch_one(spec["symbol"]))
            except Exception as exc:
                errors.append(f"{spec['symbol']}: {exc}")
                old = prev_rows.get(spec["symbol"])
                if old and old.get("last") is not None:
                    row.update({k: old.get(k) for k in ("last", "change_pct", "date", "low52", "high52")})
                    row["stale"] = True
            rows.append(row)
        out_groups.append({"name": g["group"], "rows": rows})
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "groups": out_groups,
    }, errors
