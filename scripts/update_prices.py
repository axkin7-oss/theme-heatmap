"""Fetch recent daily closes for Korean and US stocks and write data/prices.json.

Runs in GitHub Actions on a schedule. No API key needed: listings come from
FinanceDataReader and prices from Yahoo Finance via yfinance.
"""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prices.json"
EXTRA = ROOT / "config" / "extra_tickers.txt"
KEEP_DAYS = 30
KRX_SNAPSHOT = {}  # "005930.KS" -> latest close from the KRX listing, filled by korean_universe()
CHUNK = 200


def korean_universe():
    df = fdr.StockListing("KRX")
    out = {}
    for _, r in df.iterrows():
        market = str(r.get("Market", ""))
        if market.startswith("KOSPI"):
            suffix = ".KS"
        elif market.startswith("KOSDAQ"):
            suffix = ".KQ"
        else:
            continue
        sym = str(r["Code"]).zfill(6) + suffix
        out[sym] = str(r["Name"])
        try:
            close = float(r.get("Close"))
            if close > 0:
                KRX_SNAPSHOT[sym] = close
        except (TypeError, ValueError):
            pass
    return out


def us_universe():
    df = fdr.StockListing("S&P500")
    return {str(r["Symbol"]).replace(".", "-"): str(r["Symbol"]) for _, r in df.iterrows()}


def extra_tickers():
    if not EXTRA.exists():
        return {}
    out = {}
    for line in EXTRA.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            sym, _, name = line.partition(" ")
            out[sym.upper()] = name.strip() or sym.upper()
    return out


def fetch_closes(symbols, tz):
    """Download daily closes for one market and index them by that exchange's local date.

    Korean and US tickers are fetched separately: mixing them in one download makes
    yfinance align both on a shared timezone, which shifts Korean bars by a day.
    """
    frames = {}
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        df = yf.download(chunk, period="2mo", interval="1d", auto_adjust=True,
                         group_by="ticker", threads=True, progress=False, ignore_tz=False)
        for sym in chunk:
            try:
                s = df[sym]["Close"] if len(chunk) > 1 else df["Close"]
            except KeyError:
                continue
            s = s.dropna()
            if len(s) < 2:
                continue
            idx = pd.DatetimeIndex(s.index)
            if idx.tz is not None:
                idx = idx.tz_convert(tz).tz_localize(None)
            s.index = idx.normalize()
            frames[sym] = s[~s.index.duplicated(keep="last")]
        print(f"{tz}: fetched {min(i + CHUNK, len(symbols))}/{len(symbols)}", file=sys.stderr)
    return frames


def add_krx_session(series):
    """Yahoo often publishes the Korean daily bar late. The KRX listing carries every
    stock's latest close, so when Yahoo's last Korean day is behind, append that
    snapshot as the latest session (only if it clearly is a newer session)."""
    if not series or not KRX_SNAPSHOT:
        return
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    session = now.date() if (now.hour, now.minute) >= (15, 40) else now.date() - timedelta(days=1)
    while session.weekday() >= 5:
        session -= timedelta(days=1)
    session = pd.Timestamp(session)
    last_day = max(s.index[-1] for s in series.values())
    if last_day >= session:
        return
    common = [sym for sym in series if sym in KRX_SNAPSHOT and series[sym].index[-1] == last_day]
    changed = sum(1 for sym in common if abs(KRX_SNAPSHOT[sym] / float(series[sym].iloc[-1]) - 1) > 1e-9)
    if not common or changed < 0.5 * len(common):  # snapshot is the same session Yahoo already has (e.g. a holiday)
        return
    for sym in common:
        series[sym] = pd.concat([series[sym], pd.Series([KRX_SNAPSHOT[sym]], index=[session])])
    print(f"KR: added {session.date()} from KRX listing for {len(common)} symbols", file=sys.stderr)


def round_sig(v, digits=6):
    if v is None or not math.isfinite(v) or v == 0:
        return None if v is None or not math.isfinite(v) else 0
    return round(v, max(0, digits - int(math.floor(math.log10(abs(v)))) - 1))


def main():
    names = {}
    for source in (korean_universe, us_universe):
        try:
            names.update(source())
        except Exception as e:  # a listing outage should not kill the whole run
            print(f"listing failed: {source.__name__}: {e}", file=sys.stderr)
    names.update(extra_tickers())

    kr = sorted(s for s in names if s.endswith((".KS", ".KQ")))
    us = sorted(s for s in names if not s.endswith((".KS", ".KQ")))
    markets = {"KR": "KR", "US": "US"}
    by_market = {"KR": fetch_closes(kr, "Asia/Seoul"), "US": fetch_closes(us, "America/New_York")}
    add_krx_session(by_market["KR"])

    out = {"asOf": None, "markets": {}, "symbols": {}}
    for m, series in by_market.items():
        if not series:
            continue
        table = pd.DataFrame(series).sort_index().tail(KEEP_DAYS)
        out["markets"][markets[m]] = [d.strftime("%Y-%m-%d") for d in table.index]
        for sym in table.columns:
            col = table[sym]
            closes = [round_sig(float(v)) if pd.notna(v) else None for v in col]
            if sum(c is not None for c in closes) >= 2:
                out["symbols"][sym] = {"n": names.get(sym, sym), "m": markets[m], "c": closes}
    last_dates = [d[-1] for d in out["markets"].values() if d]
    out["asOf"] = max(last_dates) if last_dates else None
    out["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(out['symbols'])} symbols, asOf {out['asOf']}", file=sys.stderr)


if __name__ == "__main__":
    main()
