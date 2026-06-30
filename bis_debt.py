"""
BIS Total Non-Financial Debt-to-GDP — shared data layer.

Pulls "Total credit to the non-financial sector" (all lending sectors, market
value, % of GDP, adjusted for breaks) from the BIS Data Portal for a fixed set
of economies and builds the pre/post-COVID comparison table that mirrors the
printed BIS report. Imported by both server.py (the /bis-debt endpoint) and
bis_email.py (the scheduled email job), so the site and the email never drift.

BIS series key format:  Q.{COUNTRY}.C.A.M.770.A
  Q   = Quarterly
  {C} = country (ISO-2, e.g. US, JP; XM = Euro area)
  C   = Non-financial sector  (total: general govt + households + NFCs)
  A   = All lending sectors
  M   = Market value
  770 = Percentage of GDP
  A   = Adjusted for breaks

This "C / 770" combination is exactly the metric in the printed table:
"total non-financial debt to GDP, which includes both public and private debt."
"""
import csv
import io
from concurrent.futures import ThreadPoolExecutor

import requests

# The two display groups, in the exact order of the printed table.
BIS_GROUPS = [
    [("Japan", "JP"), ("France", "FR"), ("Canada", "CA"), ("China", "CN")],
    [("USA", "US"), ("Euro Area", "XM"), ("Italy", "IT"),
     ("UK", "GB"), ("Germany", "DE"), ("India", "IN")],
]

# Fixed pre-COVID baseline quarter. Only the "latest" column ever moves.
BASELINE_PERIOD = "2019-12-31"
BASELINE_LABEL = "4Q 2019"

_BASE = "https://data.bis.org/topics/TOTAL_CREDIT/BIS,WS_TC,2.0"
_HEADERS = {"User-Agent": "Mozilla/5.0 (BloombergTerminal BIS debt fetch)"}


def _series_url(code):
    return f"{_BASE}/Q.{code}.C.A.M.770.A?file_format=csv&format=long"


def _fetch_series(code):
    """Return {TIME_PERIOD: float} for one country, or {} on any failure.

    Worker swallows its own errors so a single bad country never kills the fan-out
    (same contract as server.py's _parallel workers).
    """
    try:
        r = requests.get(_series_url(code), headers=_HEADERS, timeout=30)
        r.raise_for_status()
        # The export has a 3-line metadata preamble before the real table, the
        # data header uses "CODE:Label" column names, and the DATAFLOW_ID column
        # is quoted and contains commas ("BIS,WS_TC,2.0") — so strip the BOM,
        # locate the header row, normalize names to the code, and use a real CSV
        # parser (never str.split(",")).
        lines = r.text.lstrip("﻿").splitlines()
        header_idx = next((i for i, ln in enumerate(lines)
                           if ln.startswith("DATAFLOW_ID")), None)
        if header_idx is None:
            return {}
        rows = list(csv.reader(io.StringIO("\n".join(lines[header_idx:]))))
        header = [c.split(":", 1)[0] for c in rows[0]]
        try:
            ti = header.index("TIME_PERIOD")
            vi = header.index("OBS_VALUE")
        except ValueError:
            return {}
        out = {}
        for row in rows[1:]:
            if len(row) <= max(ti, vi):
                continue
            period, raw = row[ti].strip(), row[vi].strip()
            if not period or not raw:
                continue
            try:
                out[period] = float(raw)
            except ValueError:
                continue
        return out
    except Exception:
        return {}


def _period_label(period):
    """'2025-12-31' -> '4Q 2025'. BIS uses end-of-quarter dates."""
    if not period:
        return "—"
    try:
        year, month, _ = period.split("-")
    except ValueError:
        return period
    q = {"03": "1Q", "06": "2Q", "09": "3Q", "12": "4Q"}.get(month, "")
    return f"{q} {year}".strip()


def build_table():
    """Fetch every country in parallel and assemble the comparison table.

    Returns a JSON-safe dict:
      {
        baseline_period, baseline_label,
        latest_period, latest_label,
        groups: [ [ {name, baseline, latest, change}, ... ], ... ],
        source,
      }
    Percentages are rounded ints (matching the printed table) or None when a
    figure is unavailable. `change` is latest − baseline of the rounded values,
    so it ties out to the displayed columns exactly.
    """
    codes = [code for grp in BIS_GROUPS for (_name, code) in grp]
    with ThreadPoolExecutor(max_workers=min(16, len(codes))) as ex:
        fetched = dict(zip(codes, ex.map(_fetch_series, codes)))

    # Newest quarter present across all series (ISO date strings sort correctly).
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
        "source": ("BIS Data Portal (WS_TC) — Total credit to the non-financial "
                   "sector, all lenders, % of GDP, adjusted for breaks"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build_table(), indent=2))
