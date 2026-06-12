import json
import hashlib
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, date
from datetime import timezone
from pathlib import Path

st.set_page_config(page_title="52-Week New Highs / New Lows", page_icon=None, layout="wide")

_now = datetime.now(timezone.utc)
_market_open = _now.weekday() < 5 and (13 <= _now.hour < 20)

st.markdown("""
<style>
  .stApp { background-color: #ffffff; color: #111111; }
  .stApp header { background-color: #ffffff; }
  .block-container { padding-top: 2rem; padding-bottom: 1rem; }
  /* sidebar info panel */
  .bbg-field-row {
    display: flex; justify-content: space-between;
    font-family: monospace; font-size: 11px;
    padding: 3px 0; border-bottom: 1px solid #e0e0e0;
  }
  .bbg-field-key { color: #666; }
  .bbg-field-val { color: #111; }
  .bbg-field-val-y { color: #b8860b; }
  section[data-testid="stSidebar"] { background-color: #f5f5f5; }
  div[data-testid="stSelectbox"] div[data-baseweb="select"] > div { background-color: #f0f0f0 !important; color: #111 !important; border: 1px solid #ccc !important; }
  div[data-testid="stSelectbox"] div[data-baseweb="select"] span { color: #111 !important; }
  div[data-testid="stDataFrame"] * { color: #111 !important; }
  div[data-testid="stTabs"] button { color: #111 !important; }
</style>
""", unsafe_allow_html=True)

# ── NYSE fallback universe (used if NASDAQ Trader fetch fails) ─────────────────
NYSE_FALLBACK = [
    "JPM","BAC","WFC","C","GS","MS","BLK","AXP","USB","PNC","TFC","COF","BK","STT","SCHW",
    "JNJ","UNH","PFE","MRK","ABT","LLY","TMO","DHR","ELV","CI","HCA","CVS","MCK","CAH",
    "XOM","CVX","COP","EOG","SLB","BKR","HAL","OXY","PSX","MPC","VLO","DVN",
    "GE","HON","CAT","DE","BA","LMT","RTX","NOC","UPS","FDX","NSC","CSX","MMM","ITW","EMR",
    "PG","KO","PEP","WMT","TGT","HD","LOW","MCD","NKE","CL","MDLZ","MO","PM","KHC","GIS",
    "NEE","DUK","SO","AEP","EXC","SRE","D","PCG","ED","XEL",
    "PLD","AMT","CCI","EQIX","SPG","O","WELL","DLR","PSA","EXR","AVB","EQR","VTR","BXP",
    "LIN","APD","ECL","FCX","NEM","DOW","DD","PPG","SHW","NUE","VMC","MLM",
    "T","VZ","DIS","CMCSA","WBD","PARA",
    "BRK-B","V","MA","UNP","CB","MMC","AON","ICE","CME","SPGI","MCO","TRV","AFL","ALL","MET",
]
INDEX_TICKER = {"NYSE": "ES=F"}   # E-mini S&P 500 futures = Bloomberg ES1
INDEX_LABEL  = {"NYSE": "S&P 500 E-Mini Futures"}
INDEX_SYM    = {"NYSE": "ES1"}
BBG_HI      = {"NYSE": "NWHLNYHI"}
BBG_LO      = {"NYSE": "NWHLNYLO"}
BBG_NAME_HI = {"NYSE": "Bloomberg New 52 Week Highs NYSE"}
BBG_NAME_LO = {"NYSE": "Bloomberg New 52 Week Lows NYSE"}

exchange = "NYSE"

# ── Data helpers ──────────────────────────────────────────────────────────────
# First-paint strategy: serve whatever is on disk immediately and mark it
# stale; the deferred block at the bottom of the script tops it up *after*
# the page has rendered, then reruns. Only a first-ever run (empty disk)
# blocks on the network.
_CACHE_DIR    = Path(__file__).resolve().parent.parent / ".yf_cache"
_PRICES_FILE  = _CACHE_DIR / "nyse_prices.pkl"
_BREADTH_FILE = _CACHE_DIR / "nyse_breadth.pkl"
_INDEX_FILE   = _CACHE_DIR / "nyse_index.pkl"
_TICKERS_FILE = _CACHE_DIR / "nyse_tickers.json"

def _download_prices(ticker_list: list, start_str: str) -> pd.DataFrame:
    batch_size = 300
    frames = []
    for i in range(0, len(ticker_list), batch_size):
        batch = ticker_list[i : i + batch_size]
        try:
            raw = yf.download(batch, start=start_str, auto_adjust=True,
                              progress=False, threads=True)["Close"]
            if isinstance(raw, pd.Series):
                raw = raw.to_frame()
            frames.append(raw)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, axis=1)
    combined = combined.loc[:, ~combined.columns.duplicated()]
    combined.dropna(how="all", inplace=True)
    return combined.astype("float32")   # halves memory/disk for the 20Y panel

# cache_resource: shared object, no 50MB+ copy/hash per rerun (treat as read-only)
# Keyed by file mtime so a background top-up automatically invalidates it.
@st.cache_resource(max_entries=2, show_spinner=False)
def _read_prices_file(mtime: float) -> pd.DataFrame | None:
    try:
        cached = pd.read_pickle(_PRICES_FILE)
        if not all(d == "float32" for d in cached.dtypes):
            cached = cached.astype("float32")
        return cached
    except Exception:
        return None

def _prices_fresh(cached: pd.DataFrame) -> bool:
    last  = cached.index.max()
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    bdays_behind = len(pd.bdate_range(last.normalize(), today)) - 1
    age_sec = _now.timestamp() - _PRICES_FILE.stat().st_mtime
    return bdays_behind <= 0 and (not _market_open or age_sec < 1800)

def get_prices_swr(tickers: tuple, start_str: str):
    """Return (prices, stale). Serves the disk cache without touching the
    network; only a first-ever run (no usable disk file) blocks on a full
    download. Stale data is topped up by the deferred block after render."""
    if _PRICES_FILE.exists():
        cached = _read_prices_file(_PRICES_FILE.stat().st_mtime)
        if cached is not None and not cached.empty and \
           cached.index.min() <= pd.Timestamp(start_str) + pd.Timedelta(days=10):
            return cached, not _prices_fresh(cached)
    combined = _download_prices(list(tickers), start_str)
    if not combined.empty:
        try:
            _CACHE_DIR.mkdir(exist_ok=True)
            combined.to_pickle(_PRICES_FILE)
        except Exception:
            pass
    return combined, False

def _refresh_prices_on_disk(tickers: tuple, start_str: str) -> bool:
    """Top up the disk pickle's tail; True if the data actually changed."""
    cached = None
    if _PRICES_FILE.exists():
        cached = _read_prices_file(_PRICES_FILE.stat().st_mtime)
    if cached is None or cached.empty or \
       cached.index.min() > pd.Timestamp(start_str) + pd.Timedelta(days=10):
        combined = _download_prices(list(tickers), start_str)
        changed = not combined.empty
    else:
        last = cached.index.max()
        new = _download_prices(list(tickers), (last - pd.Timedelta(days=7)).strftime("%Y-%m-%d"))
        if new.empty:
            return False
        combined = pd.concat([cached[cached.index < new.index.min()], new])
        combined = combined[~combined.index.duplicated(keep="last")].astype("float32")
        changed = (combined.index[-1] != cached.index[-1]) or \
                  (combined.shape != cached.shape) or \
                  not combined.iloc[-1].equals(cached.iloc[-1])
    if combined.empty:
        return False
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        combined.to_pickle(_PRICES_FILE)
    except Exception:
        return False
    return changed

def _breadth_rows_for(price_df: pd.DataFrame, dates) -> pd.DataFrame:
    """Per-date high/low counts via explicit windows; matches the rolling
    semantics of the full compute (prior 252 sessions, min 126 obs)."""
    rows, idx_out = [], []
    for d in dates:
        i = price_df.index.get_loc(d)
        if i < 252:
            continue
        window    = price_df.iloc[i - 252 : i]
        today_row = price_df.iloc[i]
        valid     = window.count() >= 126
        rows.append((
            int((today_row.gt(window.max()) & valid).sum()),
            int((today_row.lt(window.min()) & valid).sum()),
        ))
        idx_out.append(d)
    out = pd.DataFrame(rows, index=idx_out, columns=["new_highs", "new_lows"])
    out.index.name = "date"
    return out

def _cols_key(price_df: pd.DataFrame) -> str:
    # built-in hash() is salted per process; md5 is stable across restarts
    return hashlib.md5("|".join(map(str, price_df.columns)).encode()).hexdigest()

# _price_df is excluded from the cache key (leading underscore); data_token —
# (shape, last date) — stands in for it so reruns don't hash the big frame.
@st.cache_data(ttl=3600, show_spinner=False)
def compute_breadth(_price_df: pd.DataFrame, data_token: tuple) -> pd.DataFrame:
    price_df = _price_df
    if price_df.empty or len(price_df) <= 252:
        return pd.DataFrame(columns=["new_highs", "new_lows"])

    # Disk fast path: a cold server reuses the saved series instead of
    # recomputing 20Y of rolling windows; a top-up only recomputes the tail.
    # The last stored rows are always healed because they may come from a
    # partial intraday bar or be restated by the 7-day price top-up.
    cols_key = _cols_key(price_df)
    try:
        if _BREADTH_FILE.exists():
            stored = pd.read_pickle(_BREADTH_FILE)
            if stored.get("cols_key") == cols_key and not stored["breadth"].empty:
                bdf = stored["breadth"]
                if stored.get("token") == data_token:
                    return bdf
                heal_pos   = max(0, len(bdf) - 7)
                heal_start = bdf.index[heal_pos]
                if heal_start in price_df.index:
                    dates = price_df.index[price_df.index >= heal_start]
                    if 0 < len(dates) <= 40:
                        out = pd.concat([bdf.iloc[:heal_pos],
                                         _breadth_rows_for(price_df, dates)])
                        _save_breadth(out, cols_key, data_token)
                        return out
    except Exception:
        pass

    # Rolling window over the prior 252 sessions, excluding today.
    # min_periods keeps recent listings from counting as instant highs/lows.
    prior     = price_df.shift(1)
    roll_high = prior.rolling(252, min_periods=126).max()
    roll_low  = prior.rolling(252, min_periods=126).min()
    out = pd.DataFrame({
        "new_highs": price_df.gt(roll_high).sum(axis=1).astype(int),
        "new_lows":  price_df.lt(roll_low).sum(axis=1).astype(int),
    })
    out.index.name = "date"
    out = out.iloc[252:]
    _save_breadth(out, cols_key, data_token)
    return out

def _save_breadth(breadth_df: pd.DataFrame, cols_key: str, data_token: tuple):
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        pd.to_pickle({"token": data_token, "cols_key": cols_key, "breadth": breadth_df},
                     _BREADTH_FILE)
    except Exception:
        pass


def get_constituents(price_df: pd.DataFrame, as_of: str):
    """Return (highs_df, lows_df) for a given date string YYYY-MM-DD."""
    if as_of not in price_df.index:
        # fall back to last available date
        as_of = price_df.index[price_df.index <= as_of][-1] if any(price_df.index <= as_of) else price_df.index[-1]

    idx = price_df.index.get_loc(as_of)
    if idx < 252:
        return pd.DataFrame(), pd.DataFrame()

    window      = price_df.iloc[idx - 252 : idx]
    today_row   = price_df.iloc[idx]
    valid       = window.count() >= 126
    roll_high   = window.max()
    roll_low    = window.min()

    hi_mask = today_row.gt(roll_high) & valid
    lo_mask = today_row.lt(roll_low)  & valid

    def build_table(mask, roll_ref, label):
        tickers = today_row[mask].index.tolist()
        if not tickers:
            return pd.DataFrame(columns=["Ticker", "Price", f"52W {label}", f"% vs 52W {label}"])
        rows = []
        for t in tickers:
            price    = round(float(today_row[t]), 2)
            ref      = round(float(roll_ref[t]), 2)
            chg_52   = round((price / ref - 1) * 100, 2) if ref else 0
            rows.append({"Ticker": t, "Price": price, f"52W {label}": ref, f"% vs 52W {label}": chg_52})
        return pd.DataFrame(rows).sort_values("Price", ascending=False).reset_index(drop=True)

    hi_df = build_table(hi_mask, roll_high, "High")
    lo_df = build_table(lo_mask, roll_low,  "Low")
    return hi_df, lo_df


def _download_index(ticker: str, start_str: str) -> pd.DataFrame:
    df = yf.download(ticker, start=start_str, auto_adjust=True, progress=False)
    df.index = pd.to_datetime(df.index)
    return df

@st.cache_resource(max_entries=2, show_spinner=False)
def _read_index_file(mtime: float) -> pd.DataFrame | None:
    try:
        return pd.read_pickle(_INDEX_FILE)
    except Exception:
        return None

def get_index_swr(ticker: str, start_str: str):
    """Return (index_df, stale). Live quotes come from the fast_info header
    fragment, so the historical panel can lag a little; refresh it in the
    deferred block instead of blocking render."""
    if _INDEX_FILE.exists():
        df = _read_index_file(_INDEX_FILE.stat().st_mtime)
        if df is not None and not df.empty:
            age = _now.timestamp() - _INDEX_FILE.stat().st_mtime
            bdays_behind = len(pd.bdate_range(
                df.index.max().normalize(),
                pd.Timestamp.now(tz="UTC").tz_localize(None).normalize())) - 1
            covers = df.index.min() <= pd.Timestamp(start_str) + pd.Timedelta(days=45)
            stale = (not covers) or bdays_behind > 0 or (_market_open and age > 900)
            return df, stale
    df = _download_index(ticker, start_str)
    if not df.empty:
        try:
            _CACHE_DIR.mkdir(exist_ok=True)
            df.to_pickle(_INDEX_FILE)
        except Exception:
            pass
    return df, False

def _refresh_index_on_disk(ticker: str, start_str: str) -> bool:
    old = _read_index_file(_INDEX_FILE.stat().st_mtime) if _INDEX_FILE.exists() else None
    try:
        df = _download_index(ticker, start_str)
    except Exception:
        return False
    if df.empty:
        return False
    changed = old is None or old.empty or df.index[-1] != old.index[-1] or \
              not df.iloc[-1].equals(old.iloc[-1])
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        df.to_pickle(_INDEX_FILE)
    except Exception:
        return False
    return changed

def safe_float(val):
    if hasattr(val, "iloc"):
        return float(val.iloc[0]) if len(val) > 0 else float("nan")
    return float(val)

@st.cache_data(ttl=86400, show_spinner=False)   # refresh once a day
def fetch_exchange_tickers(exchange: str) -> list:
    """
    Pull full NYSE listing from NASDAQ Trader.
    Falls back to S&P lists from Wikipedia, then to curated NYSE list.
    """
    import requests
    from io import StringIO

    # ── Primary: NASDAQ Trader official daily file (NYSE = code "N") ─────────
    try:
        url = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        df = pd.read_csv(StringIO(r.text), sep="|")
        mask = (
            (df["Exchange"] == "N") &
            (df["Test Issue"] == "N") &
            (df["ETF"] == "N") &                       # Bloomberg counts stocks only
            (df["ACT Symbol"].str.match(r"^[A-Z]{1,5}$"))
        )
        tickers = df[mask]["ACT Symbol"].tolist()
        if len(tickers) > 500:
            return tickers
    except Exception:
        pass

    # ── Fallback: Wikipedia S&P 500 + 400 + 600 (~1,500 tickers) ─────────────
    urls = [
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
    ]
    tickers = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            df = pd.read_html(StringIO(r.text))[0]
            col = "Symbol" if "Symbol" in df.columns else df.columns[0]
            tickers += df[col].str.replace(".", "-", regex=False).tolist()
        except Exception:
            pass

    # Supplement with hardcoded NYSE tickers not in S&P indices
    # Focus: CEFs, mREITs, BDCs, shipping, small-cap banks — these drive the big LOW spikes
    EXTRA_NYSE = [
        # ── mREITs (mortgage REITs — very volatile, spike hard on rate moves) ──
        "AGNC","NLY","MFA","RWT","MITT","ARR","TWO","IVR","CIM","PMT","RITM","NYMT",
        "BRMK","EARN","CHMI","ORC","NREF","GPMT","TRTX","KREF","RC","ACRE","BXMT",
        "LADR","FBRT","ACR","SACH","ARI","BRSP","GNL","ILPT","RLJ","SHO","PK","XHR",
        # ── BDCs (Business Development Companies — leveraged, sell off sharply) ──
        "ARCC","MAIN","ORCC","FS","HTGC","GBDC","BXSL","PSEC","GSBD","TPVG","GAIN",
        "GLAD","HRZN","MRCC","SLRC","PFLT","KCAP","WHF","TCPC","BCSF","CGBD","CSWC",
        "FDUS","FSK","NMFC","OCSL","PNNT","SCM","SUNS","TICC","TRIN","UFCS","SAR",
        # ── CEFs — Fixed Income (rate sensitive, big drawdowns) ──────────────────
        "PDI","PDO","PTY","PCI","PCN","PKO","PFN","PHK","PHT","PIM","PPT","PTA",
        "RFI","RQI","RSF","RNP","RCS","RVT","RMT","RHY","RFM","RFC","RFT","RFP",
        "UTF","UTG","USA","AWF","BIT","BLW","BME","BNY","BST","CII","CLM","CRF",
        "CSQ","DFP","EAD","EOS","ETV","ETW","EVN","EXG","FFC","FIF","FLC","FMN",
        "GAB","GAM","GCV","GDL","GDO","GGN","GGZ","GLQ","GOF","GRR","GUT","HIO",
        "HPS","HTD","HYB","HYT","IGA","IGD","IGR","JCE","JDD","JEQ","JGH","JHB",
        "JHD","JHS","JHY","JMT","JPI","KTF","LDP","LGI","MCI","MCN","MHD","MHF",
        "MHI","MIN","MIO","MLP","MMT","MNP","MOF","MPV","MQT","MSD","MUC","MUE",
        "MUI","MUS","MVF","MYD","MYF","MYN","NAD","NBB","NBD","NBH","NBO","NBW",
        "NCA","NCB","NCP","NCV","NCZ","NEA","NEV","NGZ","NHS","NID","NIM","NIQ",
        "NKX","NMI","NMO","NMS","NMT","NMZ","NPI","NPV","NQP","NQU","NRK","NUO",
        "NVG","NXP","NZF","OIA","PCF","PML","PMM","PMO","PMX","PNF","PNI","PPR",
        "PSF","PTX","PYN","RFI","RHY","RMM","RPT","RSF","RVP","SAF","SBI","SCD",
        "SCY","SDF","SDT","SGL","SIM","SJT","SOR","SQS","SRH","STO","SUS","SVT",
        "SZC","TDF","TEI","TFI","TLI","TLP","TMF","TOO","TPZ","TRF","TSI","TTP",
        "TUZ","TWN","TYG","TYW","UCO","UMH","USA","USB","UVV","VBF","VCV","VGM",
        "VHI","VJV","VMM","VPV","VST","VTN","WDI","WIA","WIW","WMC","WPC","WPG",
        # ── CEFs — Equity (convertible, covered call) ─────────────────────────
        "AGC","AGD","ASG","BIF","BOE","BRW","CAF","CBH","CEM","CHI","CHW","CHY",
        "CLM","CRF","DNI","DSU","EDD","EDI","EFT","EGF","EIA","EMD","EMF","EMO",
        "ENX","EOD","ERH","ETB","ETV","EVF","EVG","EVJ","EVN","EVO","EVP","EVT",
        "EVV","EVX","EWC","FAX","FCA","FCT","FEO","FFA","FFB","FFC","FFN","FFR",
        "FGB","FGI","FHY","FIF","FLC","FMN","FMO","FMY","FNB","FNF","FNI","FNX",
        # ── Shipping (extremely volatile, major low spikes) ───────────────────
        "DAC","SB","SBLK","GOGL","EGLE","SALT","GNK","IMOS","CPLP","TNP","NMM",
        "DSX","DHTX","FRO","INSW","NAT","Nordic","STNG","TK","TNK","TOO","TOPS",
        "TRMD","ASC","GRIN","MPCC","OET","PNFP","SFL","SHPW","SINO","SSW","GASS",
        # ── Small/micro cap NYSE stocks (key for low spikes) ─────────────────
        "AMR","AMRK","AMRS","AMSC","AMT","AMTB","AMTD","AMTI","AMTX","AMWD",
        "AMWL","ANF","ANGI","ANGO","ANH","ANIK","ANIP","ANNT","ANV","ANSS",
        # ── Small-cap regional banks (pile into lows during credit stress) ────
        "ABCB","ACNB","AMNB","ANCX","AROW","ARTNA","ASRV","ATLO","BANF",
        "BANR","BCBP","BDGE","BFIN","BFST","BHLB","BLMT","BMTC","BOKF",
        # ── Energy small caps (major sell-off candidates) ─────────────────────
        "BCEI","BATL","BRY","CDEV","CEQP","CLMT","CMLP","CNXM","CODI","CPAC",
        "CRGY","CVIA","DKL","DPM","EE","ESTE","GEL","GLP","GPOR","HESM","HEP",
        "HFC","HMLP","HTGM","HUSA","INDO","JCAP","KRP","LGCY","MCEP","MEMP",
        "MRC","MRVL","MTDR","MUSA","NCSM","NGL","NRGX","NRGY","NTI","NVGS",
        "OAS","OMP","PBFX","PDCE","PEGI","PNRG","PTEN","PW","REGI","REXX",
        "RMP","ROSE","ROYT","RRGB","RTLR","RUN","SDRL","SIRE","SMLP","SNDE",
        "SND","SNMP","SOGO","SPKE","SPRB","SRLP","SRMX","SRRK","SRTX","SS",
        # ── Small-cap consumer & retail (hit hard in downturns) ───────────────
        "CATO","DDS","CONN","GCO","HIBB","RCII","RENT","RUTH","SBH","SCVL",
        "TLYS","TURK","UEIC","URBN","VSTO","WINA","WLFC","WLTW","WOR","WS",
        # ── Specialty finance & leasing ───────────────────────────────────────
        "AEL","AGFS","AIZ","AJG","ALEX","AL","AXS","BOC","CATO","CFB","CFR",
        "CLBK","CNO","COOP","CSV","DFB","ENVA","EQBK","EFC","FBP","FCFS","FCNCA",
        "FFBC","FFBH","FFIN","FFNW","FISI","FLIC","FLY","FMBH","FNB","FNWB",
        "FULT","GABC","GCBC","GNTY","HAFC","HBCP","HBMD","HBNC","HCI","HFWA",
        "HIFS","HMN","HONE","HTBK","HTLF","HWBK","IIIV","ISTR","JFIN","JNCE",
        "LAD","LC","LKFN","LMST","LNDC","LOAN","LOB","LSCC","LTRX","MBIN",
        "MCB","MCBC","MFNB","MGYR","MNSB","MOFG","MRLN","MSBI","MSBF","NBTB",
        "NFBK","NKSH","NOBC","NRBC","NTRS","OFG","OPBK","OPHC","OPIC","OPY",
        "OSBC","OVBC","OVLY","PBIP","PBPB","PCSB","PEBO","PFBI","PFIS","PFNL",
        "PKBK","PLBC","PLYM","PMBC","PNFP","PRBM","PRSP","PVBC","PWOD","RBCAA",
        "RBNC","RCBK","RDUS","RELL","RNDB","RNST","RVSB","SASR","SBFG","SBSI",
        "SCBT","SFBC","SFNC","SFST","SGBX","SHBI","SIFI","SIVB","SLCT","SMBC",
        "SMMF","SNFCA","SNFS","SRBK","SSBK","SSBI","STBA","STBZ","STCN","STXB",
        "TCBK","TCFC","THBK","TBNK","TRMK","TROW","TRST","UBCP","UBFO","UBOH",
        "UBSI","UCBI","UMBF","UMPQ","UNTY","UVSP","VBTX","VFIN","VIRT","VNBC",
        "VRNF","VSEC","WABC","WAFD","WASH","WBNK","WBKC","WCFB","WDFC","WFBI",
        "WMPN","WNBI","WSBC","WSFS","WTBA","WTFC","WVFC","YDKN","YORW","ZION",
    ]
    if tickers:
        combined = list(dict.fromkeys(tickers + EXTRA_NYSE))
        return combined
    return list(dict.fromkeys(NYSE_FALLBACK + EXTRA_NYSE))

def _write_tickers_file(ticker_list: list):
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        _TICKERS_FILE.write_text(json.dumps(
            {"date": str(date.today()), "tickers": ticker_list}))
    except Exception:
        pass

def get_tickers_swr(exchange: str):
    """Return (tickers, stale). Yesterday's saved list paints the page now;
    the deferred block refreshes it once a day."""
    try:
        d = json.loads(_TICKERS_FILE.read_text())
        if isinstance(d.get("tickers"), list) and len(d["tickers"]) > 100:
            return d["tickers"], d.get("date") != str(date.today())
    except Exception:
        pass
    ticker_list = fetch_exchange_tickers(exchange)
    _write_tickers_file(ticker_list)
    return ticker_list, False

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    smoothing = st.slider("Smoothing (day MA)", 1, 10, 1)

    st.markdown("---")

    view_series  = st.radio("Series detail", ["Highs", "Lows"], horizontal=True)
    ticker_shown = BBG_HI[exchange] if view_series == "Highs" else BBG_LO[exchange]
    name_shown   = BBG_NAME_HI[exchange] if view_series == "Highs" else BBG_NAME_LO[exchange]

    st.markdown(f"<div style='color:#b8860b;font-family:monospace;font-size:13px;font-weight:bold'>{ticker_shown} Index</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='color:#00838f;font-family:monospace;font-size:11px;margin-bottom:6px'>{name_shown}</div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='color:#666;font-family:monospace;font-size:10px;border-left:2px solid #bbb;"
        "padding-left:6px;margin-bottom:8px;line-height:1.5'>"
        "The New Highs and New Lows indices represent the 52-week highs/lows for a specific exchange "
        "on a given day. Computed from closing prices using a rolling 252-trading-day window. "
        "This data excludes preferred shares.</div>",
        unsafe_allow_html=True,
    )
    for key, val in [
        ("Ticker",          f"{ticker_shown} Index"),
        ("Quote Type",      "Value"),
        ("Currency",        "US DOLLAR"),
        ("Country",         "UNITED STATES"),
        ("Price Frequency", "Daily"),
        ("Last Update",     datetime.today().strftime("%m/%d/%y")),
        ("Update Status",   "Subject to one-day lag"),
        ("Start Date",      "01/02/90"),
        ("Current Source",  "Yahoo Finance"),
        ("History",         "Close"),
        ("End Of Week",     "Friday"),
    ]:
        css = "bbg-field-val-y" if key == "Ticker" else "bbg-field-val"
        st.markdown(
            f"<div class='bbg-field-row'><span class='bbg-field-key'>{key}</span>"
            f"<span class='{css}'>{val}</span></div>",
            unsafe_allow_html=True,
        )

# ── Load data — 20Y display + 252-day rolling warmup + buffer ────────────────
fetch_start = (datetime.today() - timedelta(days=365*21 + 120)).strftime("%Y-%m-%d")

with st.spinner(f"Fetching {exchange} ticker list..."):
    full_list, tickers_stale = get_tickers_swr(exchange)
tickers = tuple(full_list)

index_sym = INDEX_TICKER[exchange]

with st.spinner(f"Loading {exchange} data..."):
    prices, prices_stale = get_prices_swr(tickers, fetch_start)
    # mtime in the token: any prices rewrite (incl. intraday value-only
    # updates with unchanged shape) triggers the cheap tail heal above
    prices_mtime = int(_PRICES_FILE.stat().st_mtime) if _PRICES_FILE.exists() else 0
    data_token = (prices.shape, str(prices.index[-1]), prices_mtime) if not prices.empty else ((0, 0), "", 0)
    breadth = compute_breadth(prices, data_token)
    idx_df, index_stale = get_index_swr(index_sym, fetch_start)

idx_trim = idx_df  # no upfront trimming; buttons/pickers do all filtering

breadth["hi_sm"] = breadth["new_highs"].rolling(smoothing).mean() if smoothing > 1 else breadth["new_highs"].astype(float)
breadth["lo_sm"] = breadth["new_lows"].rolling(smoothing).mean()  if smoothing > 1 else breadth["new_lows"].astype(float)

# ── Compute stats ─────────────────────────────────────────────────────────────
idx_close = idx_trim["Close"].squeeze().astype(float) if not idx_trim.empty else pd.Series(dtype=float)
idx_last  = safe_float(idx_close.iloc[-1]) if len(idx_close) > 0 else float("nan")
idx_prev  = safe_float(idx_close.iloc[-2]) if len(idx_close) > 1 else float("nan")
idx_chg   = idx_last - idx_prev
idx_pct   = idx_chg / idx_prev * 100 if idx_prev else 0
idx_hi    = safe_float(idx_trim["High"].squeeze().iloc[-1])  if not idx_trim.empty else float("nan")
idx_lo    = safe_float(idx_trim["Low"].squeeze().iloc[-1])   if not idx_trim.empty else float("nan")
idx_op    = safe_float(idx_trim["Open"].squeeze().iloc[-1])  if not idx_trim.empty else float("nan")
chg_color = "#00e676" if idx_chg >= 0 else "#ff4444"
chg_sign  = "+" if idx_chg >= 0 else ""

hi_last     = int(breadth["new_highs"].iloc[-1])  if not breadth.empty else 0
hi_max      = int(breadth["new_highs"].max())      if not breadth.empty else 0
hi_min      = int(breadth["new_highs"].min())      if not breadth.empty else 0
hi_avg      = round(float(breadth["new_highs"].mean()), 4) if not breadth.empty else 0
hi_max_date = breadth["new_highs"].idxmax().strftime("%m/%d/%y") if not breadth.empty else ""
hi_min_date = breadth["new_highs"].idxmin().strftime("%m/%d/%y") if not breadth.empty else ""

lo_last     = int(breadth["new_lows"].iloc[-1])   if not breadth.empty else 0
lo_max      = int(breadth["new_lows"].max())       if not breadth.empty else 0
lo_min      = int(breadth["new_lows"].min())       if not breadth.empty else 0
lo_avg      = round(float(breadth["new_lows"].mean()), 4) if not breadth.empty else 0
lo_max_date = breadth["new_lows"].idxmax().strftime("%m/%d/%y") if not breadth.empty else ""
lo_min_date = breadth["new_lows"].idxmin().strftime("%m/%d/%y") if not breadth.empty else ""

last_date_str = breadth.index[-1].strftime("%-m/%-d/%y") if not breadth.empty else datetime.today().strftime("%-m/%-d/%y")
date_range_str = (
    f"{idx_trim.index[0].strftime('%m/%d/%Y')} - {idx_trim.index[-1].strftime('%m/%d/%Y')}"
    if not idx_trim.empty else ""
)

# ── Header — live-refreshing fragment ─────────────────────────────────────────
@st.fragment(run_every=30)
def render_index_header():
    try:
        fi = yf.Ticker(index_sym).fast_info
        live_price = getattr(fi, "last_price", None)
        live_prev  = getattr(fi, "previous_close", None)
        live_open  = getattr(fi, "open", None)
        live_high  = getattr(fi, "day_high", None)
        live_low   = getattr(fi, "day_low", None)
    except Exception:
        live_price = live_prev = live_open = live_high = live_low = None

    price  = live_price  if live_price  is not None else idx_last
    prev   = live_prev   if live_prev   is not None else idx_prev
    open_  = live_open   if live_open   is not None else idx_op
    high   = live_high   if live_high   is not None else idx_hi
    low    = live_low    if live_low    is not None else idx_lo

    chg   = price - prev if prev else 0
    pct   = chg / prev * 100 if prev else 0
    color = "#00e676" if chg >= 0 else "#ff4444"
    sign  = "+" if chg >= 0 else ""

    st.markdown(
        f"### {INDEX_SYM[exchange]} Index &nbsp;&nbsp; {price:,.2f} &nbsp;&nbsp; "
        f"<span style='color:{color}'>{sign}{chg:,.2f} ({sign}{pct:.2f}%)</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"Op **{open_:,.2f}** &nbsp; Hi **{high:,.2f}** &nbsp; Lo **{low:,.2f}** "
        f"&nbsp; Prev **{prev:,.2f}** &nbsp;&nbsp; `{date_range_str}`",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<small style='color:#888'>"
        f"**{BBG_HI[exchange]}** Mid {last_date_str}: {hi_last} &nbsp;|&nbsp; "
        f"High {hi_max} ({hi_max_date}) &nbsp;|&nbsp; Avg {hi_avg} &nbsp;|&nbsp; Low {hi_min} ({hi_min_date})"
        f" &nbsp;&nbsp;&nbsp; "
        f"**{BBG_LO[exchange]}** Mid {last_date_str}: {lo_last} &nbsp;|&nbsp; "
        f"High {lo_max} ({lo_max_date}) &nbsp;|&nbsp; Avg {lo_avg} &nbsp;|&nbsp; Low {lo_min} ({lo_min_date})"
        f"</small>",
        unsafe_allow_html=True,
    )

render_index_header()

st.markdown("---")

# ── Period buttons + date pickers ─────────────────────────────────────────────
all_dates = breadth.index if not breadth.empty else pd.DatetimeIndex([])
min_d = all_dates.min().date() if len(all_dates) > 0 else date(2005, 1, 1)
max_d = all_dates.max().date() if len(all_dates) > 0 else date.today()

if "qp" not in st.session_state:
    st.session_state.qp = "2Y"  # default view

period_map = {"1M":30,"3M":91,"6M":182,"YTD":"ytd","1Y":365,"2Y":730,"5Y":1825,"10Y":3650,"20Y":7300,"ALL":99999}
btn_cols = st.columns(len(period_map))
for i, lbl in enumerate(period_map):
    if btn_cols[i].button(lbl, key=f"pb_{lbl}", use_container_width=True):
        st.session_state.qp = lbl

qp = st.session_state.qp
if qp == "YTD":
    qp_from, qp_to = date(datetime.today().year, 1, 1), max_d
elif qp == "ALL":
    qp_from, qp_to = min_d, max_d
elif qp in period_map and isinstance(period_map[qp], int):
    qp_from = max(min_d, (datetime.today() - timedelta(days=period_map[qp])).date())
    qp_to   = max_d
else:
    qp_from, qp_to = min_d, max_d

dc1, dc2, _ = st.columns([1, 1, 6])
date_from = dc1.date_input("From", value=qp_from, min_value=min_d, max_value=max_d, format="MM/DD/YYYY")
date_to   = dc2.date_input("To",   value=qp_to,   min_value=min_d, max_value=max_d, format="MM/DD/YYYY")

# ── Filter to window ──────────────────────────────────────────────────────────
bv = breadth[(breadth.index.date >= date_from) & (breadth.index.date <= date_to)]
if not idx_trim.empty:
    iv   = idx_trim[(idx_trim.index.date >= date_from) & (idx_trim.index.date <= date_to)]
    icv  = iv["Close"].squeeze().astype(float)
else:
    iv, icv = idx_trim, idx_close

# ── Build chart ───────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    row_heights=[0.60, 0.40],
    shared_xaxes=True,
    vertical_spacing=0.02,
)

# Panel 1 — index daily OHLC bars (Bloomberg-style); line for long ranges,
# where thousands of bars render slowly and read as noise
ohlc_mode = not iv.empty and (date_to - date_from).days <= 1100
if ohlc_mode:
    fig.add_trace(go.Ohlc(
        x=iv.index,
        open=iv["Open"].squeeze().astype(float),
        high=iv["High"].squeeze().astype(float),
        low=iv["Low"].squeeze().astype(float),
        close=icv,
        increasing=dict(line=dict(color="#2196f3", width=1.2)),
        decreasing=dict(line=dict(color="#90a4ae", width=1.2)),
        name=f"{INDEX_SYM[exchange]} Index - Last Price {idx_last:,.0f}",
    ), row=1, col=1)
elif not iv.empty:
    fig.add_trace(go.Scatter(
        x=iv.index, y=icv, mode="lines",
        line=dict(color="#2196f3", width=1.2),
        name=f"{INDEX_SYM[exchange]} Index - Last Price {idx_last:,.0f}",
        hovertemplate=f"<b>{INDEX_SYM[exchange]}</b> %{{y:,.2f}}<extra></extra>",
    ), row=1, col=1)

# Panel 2 — new lows (red, drawn first / behind)
fig.add_trace(go.Scatter(
    x=bv.index, y=bv["lo_sm"], mode="lines",
    name=f"{BBG_LO[exchange]} Index - Mid Price on {last_date_str}  {lo_last}",
    line=dict(color="#ef5350", width=1.0),
    fill=None,
    hovertemplate="<b>New Lows</b> %{y:.0f}<extra></extra>",
), row=2, col=1)

# Panel 2 — new highs (green, on top)
fig.add_trace(go.Scatter(
    x=bv.index, y=bv["hi_sm"], mode="lines",
    name=f"{BBG_HI[exchange]} Index - Mid Price on {last_date_str}  {hi_last}",
    line=dict(color="#66bb6a", width=1.0),
    fill=None,
    hovertemplate="<b>New Highs</b> %{y:.0f}<extra></extra>",
), row=2, col=1)

# ── Layout ────────────────────────────────────────────────────────────────────
spike = dict(showspikes=True, spikecolor="#aaa", spikethickness=1, spikedash="dot", spikemode="across")
ax_base = dict(
    showgrid=True, gridcolor="#e8e8e8", gridwidth=1,
    zeroline=False, linecolor="#ccc", showline=True,
    tickfont=dict(color="#555", size=10, family="monospace"),
    fixedrange=False, **spike,
)

fig.update_layout(
    plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
    font=dict(color="#333", family="monospace"),
    hovermode="x unified", dragmode="pan",
    legend=dict(
        bgcolor="rgba(255,255,255,0.9)", bordercolor="#ddd", borderwidth=1,
        font=dict(color="#333", size=10, family="monospace"),
        orientation="h", x=0, y=1.01, traceorder="reversed",
    ),
    margin=dict(l=55, r=55, t=40, b=10),
    height=680,
    modebar=dict(bgcolor="rgba(0,0,0,0)", color="#555", activecolor="#4fc3f7"),
)

# Both panels — single right-side y-axis; breadth panel anchored at zero
fig.update_yaxes(side="right", row=1, col=1, **ax_base)
fig.update_yaxes(side="right", rangemode="tozero", row=2, col=1, **ax_base)

xax = dict(showgrid=True, gridcolor="#e8e8e8", tickfont=dict(color="#555", size=10, family="monospace"),
           rangeslider_visible=False, **spike)
if ohlc_mode:   # weekend gaps only matter for bars; rangebreaks slow long-range panning
    xax["rangebreaks"] = [dict(bounds=["sat", "mon"])]
fig.update_xaxes(row=1, col=1, **xax)
fig.update_xaxes(row=2, col=1, **xax)

st.plotly_chart(fig, use_container_width=True, config={
    "scrollZoom": True, "displayModeBar": True, "displaylogo": False,
})

# ── Constituent tables ────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### 52-Week Highs & Lows — Constituents")

# Date selector for the constituent view
all_breadth_dates = breadth.index.date.tolist() if not breadth.empty else []
default_date = max_d
c_date = st.date_input(
    "View constituents as of",
    value=default_date,
    min_value=min_d,
    max_value=max_d,
    format="MM/DD/YYYY",
    key="const_date",
)

with st.spinner("Loading constituents..."):
    hi_df, lo_df = get_constituents(prices, str(c_date))

# Enrich constituents with full company names from SEC EDGAR

tab_hi, tab_lo = st.tabs([
    f"🟢  New 52-Week Highs  ({len(hi_df)})",
    f"🔴  New 52-Week Lows   ({len(lo_df)})",
])

with tab_hi:
    if hi_df.empty:
        st.caption("No new 52-week highs on this date.")
    else:
        st.dataframe(
            hi_df.style
                .format({"Price": "{:.2f}", "52W High": "{:.2f}", "% vs 52W High": "{:+.2f}%"})
                .map(lambda v: "color:#66bb6a" if isinstance(v, (int, float)) and v > 0 else "",
                     subset=["% vs 52W High"]),
            use_container_width=True,
            height=min(400, 36 * len(hi_df) + 38),
        )

with tab_lo:
    if lo_df.empty:
        st.caption("No new 52-week lows on this date.")
    else:
        st.dataframe(
            lo_df.style
                .format({"Price": "{:.2f}", "52W Low": "{:.2f}", "% vs 52W Low": "{:+.2f}%"})
                .map(lambda v: "color:#ef5350" if isinstance(v, (int, float)) and v < 0 else "",
                     subset=["% vs 52W Low"]),
            use_container_width=True,
            height=min(400, 36 * len(lo_df) + 38),
        )

# ── Raw data table ────────────────────────────────────────────────────────────
with st.expander("Raw Breadth Data"):
    display = breadth[["new_highs","new_lows"]].copy()
    display.columns = [f"{BBG_HI[exchange]} (New Highs)", f"{BBG_LO[exchange]} (New Lows)"]
    display.index = display.index.strftime("%m/%d/%Y")
    st.dataframe(display.iloc[::-1].head(120), use_container_width=True, height=320)

# ── Deferred refresh ──────────────────────────────────────────────────────────
# Everything above is already on screen; now top up whatever was served stale
# and rerun so the fresh data paints. The min-age gate paces retries when a
# refresh can't advance the data (e.g. Yahoo hasn't posted yesterday's close),
# which also prevents rerun loops.
_REFRESH_MIN_AGE = 600

def _file_age(path: Path) -> float:
    try:
        return _now.timestamp() - path.stat().st_mtime
    except OSError:
        return float("inf")

if tickers_stale or prices_stale or index_stale:
    data_changed = False
    if tickers_stale:
        try:
            fresh_list = fetch_exchange_tickers(exchange)
            if len(fresh_list) > 100:
                _write_tickers_file(fresh_list)
                tickers = tuple(fresh_list)
        except Exception:
            pass
    if prices_stale and _file_age(_PRICES_FILE) > _REFRESH_MIN_AGE:
        st.toast("Updating NYSE prices in the background…")
        data_changed |= _refresh_prices_on_disk(tickers, fetch_start)
    if index_stale and _file_age(_INDEX_FILE) > _REFRESH_MIN_AGE:
        data_changed |= _refresh_index_on_disk(index_sym, fetch_start)
    if data_changed:
        st.rerun()
