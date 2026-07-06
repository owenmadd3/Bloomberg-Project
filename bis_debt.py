"""
BIS Total Non-Financial Debt-to-GDP — shared data layer.

Pulls "Total credit to the non-financial sector" (all lending sectors, market
value, % of GDP, adjusted for breaks) from the BIS SDMX API for a fixed set of
economies and builds the pre/post-COVID comparison table that mirrors the
printed BIS report. Imported by both server.py (the /bis-debt endpoint) and
bis_email.py (the scheduled email job), so the site and the email never drift.

Data source: the BIS SDMX REST API at stats.bis.org. All 10 economies come back
in ONE request using a multi-value key (US+JP+...), then we group by country.

  https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0/Q.{codes}.C.A.M.770.A?format=csv

Series key dimensions:  Q.{country}.C.A.M.770.A
  Q   = Quarterly
  {C} = country (ISO-2, e.g. US, JP; XM = Euro area)
  C   = Non-financial sector  (total: general govt + households + NFCs)
  A   = All lending sectors
  M   = Market value
  770 = Percentage of GDP
  A   = Adjusted for breaks

This "C / 770" combination is exactly the metric in the printed table:
"total non-financial debt to GDP, which includes both public and private debt."

NOTE: this replaced the old data.bis.org "Time Series Search Export" download URL,
which BIS retired (it now 404s). The SDMX API returns clean CSV (standard headers,
no metadata preamble) and reports periods as "2025-Q4" rather than "2025-12-31".
"""
import csv
import io

import requests

# The two display groups, in the exact order of the printed table.
BIS_GROUPS = [
    [("Japan", "JP"), ("France", "FR"), ("Canada", "CA"), ("China", "CN")],
    [("USA", "US"), ("Euro Area", "XM"), ("Italy", "IT"),
     ("UK", "GB"), ("Germany", "DE"), ("India", "IN")],
]

# Fixed pre-COVID baseline quarter. Only the "latest" column ever moves.
BASELINE_PERIOD = "2019-Q4"
BASELINE_LABEL = "4Q 2019"

_API = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0"
_HEADERS = {"User-Agent": "Mozilla/5.0 (BloombergTerminal BIS debt fetch)"}


def _all_codes():
    return [code for grp in BIS_GROUPS for (_name, code) in grp]


def _series_url(codes):
    key = f"Q.{'+'.join(codes)}.C.A.M.770.A"
    return f"{_API}/{key}?format=csv"


def _fetch_all():
    """Return {country_code: {TIME_PERIOD: float}} for every economy in one call.

    Raises on network/HTTP failure so build_table() can decide how to degrade.
    """
    codes = _all_codes()
    r = requests.get(_series_url(codes), headers=_HEADERS, timeout=45)
    r.raise_for_status()
    out = {c: {} for c in codes}
    for row in csv.DictReader(io.StringIO(r.text)):
        cty = (row.get("BORROWERS_CTY") or "").strip()
        period = (row.get("TIME_PERIOD") or "").strip()
        raw = (row.get("OBS_VALUE") or "").strip()
        if cty not in out or not period or not raw:
            continue
        try:
            out[cty][period] = float(raw)
        except ValueError:
            continue
    return out


def _period_label(period):
    """'2025-Q4' -> '4Q 2025'."""
    if not period:
        return "—"
    try:
        year, q = period.split("-")
    except ValueError:
        return period
    return f"{q.replace('Q', '')}Q {year}"


def build_table():
    """Fetch every country and assemble the comparison table.

    Returns a JSON-safe dict:
      {
        baseline_period, baseline_label,
        latest_period, latest_label,
        groups: [ [ {name, baseline, latest, period, change}, ... ], ... ],
        source,
      }
    Percentages are rounded ints (matching the printed table) or None when a
    figure is unavailable. `change` is latest − baseline of the rounded values,
    so it ties out to the displayed columns exactly.
    """
    try:
        fetched = _fetch_all()
    except Exception:
        fetched = {c: {} for c in _all_codes()}

    # Newest quarter present across all series. Period strings are "YYYY-QN",
    # which sort chronologically as plain strings (fixed-width year, then quarter).
    all_periods = set()
    for series in fetched.values():
        all_periods.update(series.keys())
    latest_period = max(all_periods) if all_periods else None

    def _row(name, code):
        series = fetched.get(code, {})
        base = series.get(BASELINE_PERIOD)
        # Prefer the global latest quarter; fall back to this country's own most
        # recent point if it lags the others.
        lp = latest_period if latest_period in series else (max(series) if series else None)
        latest = series.get(lp) if lp else None
        base_r = round(base) if base is not None else None
        latest_r = round(latest) if latest is not None else None
        change = (latest_r - base_r) if (base_r is not None and latest_r is not None) else None
        return {"name": name, "baseline": base_r, "latest": latest_r,
                "period": lp, "change": change}

    groups = [[_row(name, code) for (name, code) in grp] for grp in BIS_GROUPS]

    return {
        "baseline_period": BASELINE_PERIOD,
        "baseline_label": BASELINE_LABEL,
        "latest_period": latest_period,
        "latest_label": _period_label(latest_period),
        "groups": groups,
        "source": ("BIS SDMX API (WS_TC) — Total credit to the non-financial "
                   "sector, all lenders, % of GDP, adjusted for breaks"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build_table(), indent=2))
