"""
Batch-run the Value Screener over ~500 tickers and find companies that are
"green" (verdict_class == 'good') on 4 or 5 of the five methods.

Green meanings per method:
  Buffett  : UNDERVALUED   (10x avg pre-tax income >= market cap)
  Brandes  : PASS          (all 4 checklist items pass)
  Pabrai   : UNDERVALUED   (owner earnings x10 + cash >= market cap)
  HMH      : ATTRACTIVE    (avg ROE / P/B >= 0.15)
  Hempton  : CHEAP         (price/sales <= 2)
"""
import sys
import time
import json
import concurrent.futures as cf
import requests
import valuation as v

PROGRESS = "/tmp/screen500_progress.log"
RESULTS = "/tmp/screen500_results.json"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS, "a") as f:
        f.write(line + "\n")


def get_universe():
    """S&P 500 constituents (datahub mirror), normalized for SEC/yFinance."""
    urls = [
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            rows = r.text.strip().splitlines()[1:]
            syms = [row.split(",")[0].strip().strip('"') for row in rows]
            syms = [s.replace(".", "-") for s in syms if s]
            if len(syms) > 400:
                return syms
        except Exception as e:
            log(f"universe fetch failed ({url}): {e}")
    return []


def evaluate(sym):
    try:
        r = v.compute_valuation(sym)
        if "error" in r:
            return {"symbol": sym, "error": r["error"]}
        greens = []
        verdicts = {}
        for m in r["methods"]:
            verdicts[m["id"]] = m.get("verdict")
            if m.get("available") and m.get("verdict_class") == "good":
                greens.append(m["id"])
        return {
            "symbol": sym,
            "company": r.get("company"),
            "price": r.get("price"),
            "market_cap": r.get("market_cap"),
            "green_count": len(greens),
            "greens": greens,
            "verdicts": verdicts,
        }
    except Exception as e:
        return {"symbol": sym, "error": str(e)}


def main():
    open(PROGRESS, "w").close()
    syms = get_universe()
    if not syms:
        log("Could not fetch a ticker universe. Aborting.")
        sys.exit(1)
    log(f"Universe: {len(syms)} tickers")

    v.get_cik("AAPL")  # pre-warm CIK map before threading

    results = []
    done = 0
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    errors = 0
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
            if done % 25 == 0 or done == len(syms):
                elapsed = time.time() - t0
                log(f"{done}/{len(syms)} done ({elapsed:.0f}s) | "
                    f"errors={errors} | "
                    f"3g={counts[3]} 4g={counts[4]} 5g={counts[5]}")

    results.sort(key=lambda x: (-x["green_count"], -(x.get("market_cap") or 0)))
    with open(RESULTS, "w") as f:
        json.dump(results, f, indent=2, default=str)

    log("=" * 64)
    log(f"FINISHED in {time.time()-t0:.0f}s. Evaluated {len(results)} (errors {errors}).")
    log(f"Green distribution: " + "  ".join(f"{k}g={counts[k]}" for k in sorted(counts)))
    log("")
    top = [r for r in results if r["green_count"] >= 4]
    log(f"--- {len(top)} companies green on 4 or 5 methods ---")
    for r in top:
        mc = (r.get("market_cap") or 0) / 1e9
        log(f"  {r['green_count']}g  {r['symbol']:6s} {(r.get('company') or '')[:32]:32s} "
            f"${mc:.1f}B  green={','.join(r['greens'])}")
    log("")
    three = [r for r in results if r["green_count"] == 3]
    log(f"--- {len(three)} companies green on exactly 3 methods (runners-up) ---")
    for r in three[:40]:
        mc = (r.get("market_cap") or 0) / 1e9
        log(f"  3g  {r['symbol']:6s} {(r.get('company') or '')[:32]:32s} "
            f"${mc:.1f}B  green={','.join(r['greens'])}")
    log(f"\nFull results written to {RESULTS}")


if __name__ == "__main__":
    main()
