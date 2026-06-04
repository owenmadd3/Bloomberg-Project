import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, date
from datetime import timezone

st.set_page_config(page_title="52-Week New Highs / New Lows", page_icon=None, layout="wide")

_now = datetime.now(timezone.utc)
_market_open = _now.weekday() < 5 and (13 <= _now.hour < 20)

st.markdown("""
<style>
  .stApp { background-color: #0a0a0a; color: #e0e0e0; }
  .stApp header { background-color: #0a0a0a; }
  .block-container { padding-top: 2rem; padding-bottom: 1rem; }
  /* sidebar info panel */
  .bbg-field-row {
    display: flex; justify-content: space-between;
    font-family: monospace; font-size: 11px;
    padding: 3px 0; border-bottom: 1px solid #1e1e1e;
  }
  .bbg-field-key { color: #777; }
  .bbg-field-val { color: #e0e0e0; }
  .bbg-field-val-y { color: #ffd600; }
</style>
""", unsafe_allow_html=True)

# ── Universes ─────────────────────────────────────────────────────────────────
EXCHANGE_TICKERS = {
    "NYSE": [
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
    ],
    "NASDAQ": [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","QCOM",
        "ADBE","CRM","ORCL","INTU","NOW","SNOW","PANW","CRWD","FTNT","ZS","OKTA","DDOG","MDB",
        "TEAM","HUBS","WDAY","VEEV","ANSS","CDNS","KLAC","LRCX","AMAT","MRVL",
        "AMD","INTC","MU","MCHP","SWKS","MPWR","ON","ADI","TXN","NXPI",
        "AMGN","GILD","BIIB","REGN","VRTX","MRNA","IDXX","ALGN","ILMN","BMRN","ALNY",
        "COST","SBUX","PYPL","EBAY","BKNG","EXPE","ABNB","UBER","DASH","CHWY",
        "COIN","SQ","SOFI","HOOD","AFRM","RIVN","NIO","XPEV","LI","ENPH","SEDG","FSLR","PLUG",
        "NFLX","SPOT","TTD","ROKU","CSCO","ANET","ZM","DOCU",
    ],
    "AMEX": [
        "GLD","SLV","GDX","GDXJ","IAU","SIVR","PPLT","PALL","RING","SIL",
        "XLE","OIH","XOP","AMLP","USO","UNG","VXX","UVXY","SVXY",
        "TQQQ","SQQQ","SPXL","SPXS","UPRO","UDOW","SDOW","TNA","TZA","LABU","LABD",
        "XLF","XLK","XLV","XLI","XLU","XLRE","XLB","XLY","XLP","XLC",
        "IWM","IJR","MDY","VBR","VBK","IWS","IWD","IWF",
        "EEM","EFA","FXI","EWZ","GXC","INDA","EWY","EWJ","VGK","MCHI",
        "TLT","IEF","SHY","HYG","LQD","JNK","EMB","TIP",
        "BTG","AG","EGO","PAAS","FSM","HL","CDE",
        "NOG","SM","CIVI","VTLE","TALO","REI","BORR","TDW",
    ],
}
INDEX_TICKER = {"NYSE": "^NYA",  "NASDAQ": "^IXIC", "AMEX": "^XAX"}
INDEX_LABEL  = {"NYSE": "NYSE Composite", "NASDAQ": "NASDAQ Composite", "AMEX": "AMEX Composite"}
INDEX_SYM    = {"NYSE": "ES1",   "NASDAQ": "IXIC",  "AMEX": "XAX"}
BBG_HI = {"NYSE": "NWHLNYHI", "NASDAQ": "NWHLNDHI", "AMEX": "NWHLAXHI"}
BBG_LO = {"NYSE": "NWHLNYLO", "NASDAQ": "NWHLNDLO", "AMEX": "NWHLAXLO"}
BBG_NAME_HI = {"NYSE": "Bloomberg New 52 Week Highs NYSE", "NASDAQ": "Bloomberg New 52 Week Highs NASDAQ", "AMEX": "Bloomberg New 52 Week Highs AMEX"}
BBG_NAME_LO = {"NYSE": "Bloomberg New 52 Week Lows NYSE",  "NASDAQ": "Bloomberg New 52 Week Lows NASDAQ",  "AMEX": "Bloomberg New 52 Week Lows AMEX"}

# ── Data helpers ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def load_price_data(tickers: tuple, start_str: str) -> pd.DataFrame:
    batch_size = 200
    ticker_list = list(tickers)
    frames = []
    for i in range(0, len(ticker_list), batch_size):
        batch = ticker_list[i : i + batch_size]
        try:
            raw = yf.download(batch, start=start_str, auto_adjust=True,
                              progress=False, threads=False)["Close"]
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
    return combined

@st.cache_data(ttl=3600, show_spinner=False)
def compute_breadth(price_df: pd.DataFrame) -> pd.DataFrame:
    records = []
    n = len(price_df)
    for i in range(252, n):
        window = price_df.iloc[i - 252:i]
        today  = price_df.iloc[i]
        nh = int((today >= window.max() * 0.999).sum())
        nl = int((today <= window.min() * 1.001).sum())
        records.append({"date": price_df.index[i], "new_highs": nh, "new_lows": nl})
    return pd.DataFrame(records).set_index("date")

@st.cache_data(ttl=3600, show_spinner=False)
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
    roll_high   = window.max()
    roll_low    = window.min()

    hi_mask = today_row >= roll_high * 0.999
    lo_mask = today_row <= roll_low  * 1.001

    def build_table(mask, roll_ref, label):
        tickers = today_row[mask].index.tolist()
        rows = []
        for t in tickers:
            price    = round(float(today_row[t]), 2)
            ref      = round(float(roll_ref[t]), 2)
            chg_52   = round((price / ref - 1) * 100, 2) if ref else 0
            rows.append({"Ticker": t, "Price": price, f"52W {label}": ref, f"% vs 52W {label}": chg_52})
        df = pd.DataFrame(rows).sort_values("Price", ascending=False).reset_index(drop=True)
        return df

    hi_df = build_table(hi_mask, roll_high, "High")
    lo_df = build_table(lo_mask, roll_low,  "Low")
    return hi_df, lo_df

@st.cache_data(ttl=3600, show_spinner=False)
def get_company_names(tickers: tuple) -> dict:
    """Fetch longName for each ticker via yfinance."""
    names = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            names[t] = info.get("longName") or info.get("shortName") or t
        except Exception:
            names[t] = t
    return names

@st.cache_data(ttl=15, show_spinner=False)   # 15s to match refresh interval
def load_index(ticker: str, start_str: str) -> pd.DataFrame:
    df = yf.download(ticker, start=start_str, auto_adjust=True, progress=False)
    df.index = pd.to_datetime(df.index)
    return df

def safe_float(val):
    if hasattr(val, "iloc"):
        return float(val.iloc[0]) if len(val) > 0 else float("nan")
    return float(val)

@st.cache_data(ttl=86400, show_spinner=False)   # refresh once a day
def fetch_exchange_tickers(exchange: str) -> list:
    """
    Pull full exchange listing from NASDAQ Trader (~2,400 NYSE tickers).
    Falls back to S&P lists from Wikipedia, then to curated list.
    """
    import requests
    from io import StringIO

    # ── Primary: NASDAQ Trader official daily file ────────────────────────────
    try:
        if exchange == "NASDAQ":
            url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            df = pd.read_csv(StringIO(r.text), sep="|")
            mask = (df["Test Issue"] == "N") & (df["Symbol"].str.match(r"^[A-Z]{1,5}$"))
            return df[mask]["Symbol"].tolist()
        else:
            exchange_code = {"NYSE": "N", "AMEX": "A"}
            url = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            df = pd.read_csv(StringIO(r.text), sep="|")
            code = exchange_code.get(exchange, "N")
            mask = (
                (df["Exchange"] == code) &
                (df["Test Issue"] == "N") &
                (df["ACT Symbol"].str.match(r"^[A-Z]{1,5}$"))
            )
            tickers = df[mask]["ACT Symbol"].tolist()
            if len(tickers) > 500:   # sanity check — should be ~2,400
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
    return list(dict.fromkeys(EXCHANGE_TICKERS[exchange] + EXTRA_NYSE))

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    exchange  = st.selectbox("Exchange", ["NYSE", "NASDAQ", "AMEX"], index=0)
    st.markdown("---")
    smoothing = st.slider("Smoothing (day MA)", 1, 10, 1)

    st.markdown("---")

    view_series  = st.radio("Series detail", ["Highs", "Lows"], horizontal=True)
    ticker_shown = BBG_HI[exchange] if view_series == "Highs" else BBG_LO[exchange]
    name_shown   = BBG_NAME_HI[exchange] if view_series == "Highs" else BBG_NAME_LO[exchange]

    st.markdown(f"<div style='color:#ffd600;font-family:monospace;font-size:13px;font-weight:bold'>{ticker_shown} Index</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='color:#00bcd4;font-family:monospace;font-size:11px;margin-bottom:6px'>{name_shown}</div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='color:#666;font-family:monospace;font-size:10px;border-left:2px solid #333;"
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

# ── Load data — fetch 2 years (252 days rolling window + 1 year display) ─────
fetch_start = (datetime.today() - timedelta(days=365*2 + 270)).strftime("%Y-%m-%d")

with st.spinner(f"Fetching {exchange} ticker list..."):
    full_list = fetch_exchange_tickers(exchange)
tickers = tuple(full_list)

index_sym = INDEX_TICKER[exchange]

with st.spinner(f"Loading {exchange} data..."):
    prices  = load_price_data(tickers, fetch_start)
    breadth = compute_breadth(prices)
    idx_df  = load_index(index_sym, fetch_start)

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

# ── Header — plain Streamlit, no HTML ────────────────────────────────────────
st.markdown(
    f"### {INDEX_SYM[exchange]} Index &nbsp;&nbsp; {idx_last:,.2f} &nbsp;&nbsp; "
    f"<span style='color:{chg_color}'>{chg_sign}{idx_chg:,.2f} ({chg_sign}{idx_pct:.2f}%)</span>",
    unsafe_allow_html=True,
)
st.markdown(f"Op **{idx_op:,.2f}** &nbsp; Hi **{idx_hi:,.2f}** &nbsp; Lo **{idx_lo:,.2f}** "
            f"&nbsp; Prev **{idx_prev:,.2f}** &nbsp;&nbsp; `{date_range_str}`",
            unsafe_allow_html=True)
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

# Panel 1 — index price line
if not iv.empty:
    fig.add_trace(go.Scatter(
        x=iv.index, y=icv, mode="lines",
        line=dict(color="#4fc3f7", width=1.2),
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
spike = dict(showspikes=True, spikecolor="#444", spikethickness=1, spikedash="dot", spikemode="across")
ax_base = dict(
    showgrid=True, gridcolor="#161616", gridwidth=1,
    zeroline=False, linecolor="#2a2a2a", showline=True,
    tickfont=dict(color="#666", size=10, family="monospace"),
    fixedrange=False, **spike,
)

fig.update_layout(
    plot_bgcolor="#0d0d0d", paper_bgcolor="#0a0a0a",
    font=dict(color="#aaa", family="monospace"),
    hovermode="x unified", dragmode="pan",
    legend=dict(
        bgcolor="rgba(13,13,13,0.85)", bordercolor="#2a2a2a", borderwidth=1,
        font=dict(color="#ccc", size=10, family="monospace"),
        orientation="h", x=0, y=1.01, traceorder="reversed",
    ),
    margin=dict(l=55, r=55, t=40, b=10),
    height=680,
    modebar=dict(bgcolor="rgba(0,0,0,0)", color="#555", activecolor="#4fc3f7"),
)

# Both panels — single right-side y-axis
fig.update_yaxes(side="right", row=1, col=1, **ax_base)
fig.update_yaxes(side="right", row=2, col=1, **ax_base)

fig.update_xaxes(showgrid=True, gridcolor="#161616", tickfont=dict(color="#666", size=10, family="monospace"),
                 rangeslider_visible=False, **spike, row=1, col=1)
fig.update_xaxes(showgrid=True, gridcolor="#161616", tickfont=dict(color="#666", size=10, family="monospace"),
                 rangeslider_visible=False, **spike, row=2, col=1)

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

# Optionally enrich with company names (cached separately so it doesn't slow the main loop)
show_names = st.checkbox("Show company names (slower first load)", value=False)
if show_names and (not hi_df.empty or not lo_df.empty):
    all_tickers = tuple(set(hi_df["Ticker"].tolist() + lo_df["Ticker"].tolist()))
    with st.spinner("Fetching company names..."):
        names = get_company_names(all_tickers)
    if not hi_df.empty:
        hi_df.insert(1, "Company", hi_df["Ticker"].map(names))
    if not lo_df.empty:
        lo_df.insert(1, "Company", lo_df["Ticker"].map(names))

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
