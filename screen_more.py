"""
Run the Value Screener over the S&P MidCap 400 + SmallCap 600 (~1000 more
companies beyond the large-cap 500 already screened). Finds names green
(verdict_class == 'good') on 4 or 5 of the five methods.
"""
import time
import json
import io
import concurrent.futures as cf
import requests
import pandas as pd
import valuation as v
from screen_500 import evaluate  # reuse the per-ticker evaluator

PROGRESS = "/tmp/screenmore_progress.log"
RESULTS = "/tmp/screenmore_results.json"
UA = {"User-Agent": "Mozilla/5.0 (research) bloomberg-project"}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS, "a") as f:
        f.write(line + "\n")


def syms_from(url):
    html = requests.get(url, headers=UA, timeout=25).text
    for t in pd.read_html(io.StringIO(html)):
        cols = [str(c).lower() for c in t.columns]
        for cand in ("symbol", "ticker"):
            for i, c in enumerate(cols):
                if cand in c:
                    return [str(s).strip().replace(".", "-")
                            for s in t.iloc[:, i].tolist() if str(s).strip()]
    return []


def get_universe():
    syms = []
    for name, url in [
        ("S&P400", "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"),
        ("S&P600", "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"),
    ]:
        try:
            got = syms_from(url)
            log(f"{name}: {len(got)} tickers")
            syms += got
        except Exception as e:
            log(f"{name} fetch failed: {e}")
    # dedupe, preserve order
    seen, out = set(), []
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def main():
    open(PROGRESS, "w").close()
    syms = get_universe()
    if not syms:
        log("No universe fetched. Aborting.")
        return
    log(f"Universe (deduped): {len(syms)} tickers")
    v.get_cik("AAPL")  # pre-warm CIK map

    results, done, errors = [], 0, 0
    counts = {i: 0 for i in range(6)}
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(evaluate, s): s for s in syms}
        for fut in cf.as_completed(futs):
            res = fut.result()
            done += 1
            if "error" in res:
                errors += 1
            else:
                results.append(res)
                counts[res["green_count"]] += 1
            if done % 50 == 0 or done == len(syms):
                log(f"{done}/{len(syms)} ({time.time()-t0:.0f}s) | errors={errors} | "
                    f"3g={counts[3]} 4g={counts[4]} 5g={counts[5]}")

    results.sort(key=lambda x: (-x["green_count"], -(x.get("market_cap") or 0)))
    with open(RESULTS, "w") as f:
        json.dump(results, f, indent=2, default=str)

    log("=" * 64)
    log(f"FINISHED in {time.time()-t0:.0f}s. Evaluated {len(results)} (errors {errors}).")
    log("Green distribution: " + "  ".join(f"{k}g={counts[k]}" for k in sorted(counts)))
    log("")
    for label, lo, hi, cap in [("green on 4 or 5 methods", 4, 5, 999),
                               ("green on exactly 3 methods", 3, 3, 60)]:
        sel = [r for r in results if lo <= r["green_count"] <= hi]
        log(f"--- {len(sel)} companies {label} ---")
        for r in sel[:cap]:
            mc = (r.get("market_cap") or 0) / 1e9
            log(f"  {r['green_count']}g  {r['symbol']:6s} {(r.get('company') or '')[:32]:32s} "
                f"${mc:.1f}B  green={','.join(r['greens'])}")
        log("")
    log(f"Full results written to {RESULTS}")


if __name__ == "__main__":
    main()
