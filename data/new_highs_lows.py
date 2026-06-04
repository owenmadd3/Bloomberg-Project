import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, date
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="52-Week New Highs / New Lows", page_icon=None, layout="wide")

# Auto-refresh — only runs during market hours (9:30–16:00 ET Mon–Fri)
from datetime import timezone
_now = datetime.now(timezone.utc)
_market_open = _now.weekday() < 5 and (13 <= _now.hour < 20)   # 9:30–16:00 ET = 13:30–20:00 UTC
_refresh_interval = 15_000   # 15 seconds
if _market_open:
    st_autorefresh(interval=_refresh_interval, key="live_refresh")

st.markdown("""
<style>
  .stApp { background-color: #ffffff; color: #111111; }
  .stApp header { background-color: #ffffff; }
  .block-container { padding-top: 2rem; padding-bottom: 1rem; }
  /* sidebar info panel */
  .bbg-field-row {
    display: flex; justify-content: space-between;
    font-family: monospace; font-size: 11px;
    padding: 3px 0; border-bottom: 1px solid #1e1e1e;
  }
  .bbg-field-key { color: #666; }
  .bbg-field-val { color: #111; }
  .bbg-field-val-y { color: #b8860b; }

  /* Buttons */
  div[data-testid="stButton"] button {
    background-color: #f0f0f0;
    color: #111111;
    border: 1px solid #ccc;
    font-family: monospace;
    font-size: 12px;
  }
  div[data-testid="stButton"] button:hover {
    background-color: #1565c0;
    color: #ffffff;
    border-color: #1565c0;
  }

  /* Date inputs */
  div[data-testid="stDateInput"] input {
    color: #111111;
    background-color: #f9f9f9;
    border: 1px solid #ccc;
  }
  div[data-testid="stDateInput"] label { color: #444; font-size: 12px; }

  /* Selectbox / slider labels */
  div[data-testid="stSelectbox"] label,
  div[data-testid="stRadio"] label,
  div[data-testid="stSlider"] label { color: #333; font-size: 12px; }

  /* Selectbox dropdown text */
  div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    background-color: #f0f0f0 !important;
    color: #111111 !important;
    border: 1px solid #ccc !important;
  }
  div[data-testid="stSelectbox"] div[data-baseweb="select"] span {
    color: #111111 !important;
  }
  div[data-testid="stSelectbox"] svg { fill: #111111 !important; }

  /* Sidebar background */
  section[data-testid="stSidebar"] { background-color: #f5f5f5; }
  section[data-testid="stSidebar"] * { color: #111; }

  /* Dataframe / table text */
  div[data-testid="stDataFrame"] * { color: #111111 !important; }
  div[data-testid="stDataFrame"] th { background-color: #f0f0f0 !important; color: #111 !important; }
  div[data-testid="stDataFrame"] td { background-color: #ffffff !important; color: #111 !important; }

  /* Tabs */
  div[data-testid="stTabs"] button { color: #111111 !important; }
  div[data-testid="stTabs"] button[aria-selected="true"] { color: #1565c0 !important; border-bottom-color: #1565c0 !important; }

  /* Expander */
  div[data-testid="stExpander"] summary { color: #111111 !important; }
  div[data-testid="stExpander"] p { color: #111111 !important; }
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
def get_constituents(price_df: pd.DataFrame, as_of: str) -> tuple[pd.DataFrame, pd.DataFrame]:
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
    Pull full exchange listing from NASDAQ Trader (official daily file).
    Returns clean common-stock tickers only (no warrants/rights/test issues).
    Falls back to curated list if the fetch fails.
    """
    import requests
    from io import StringIO

    exchange_code = {"NYSE": "N", "NASDAQ": "Q", "AMEX": "A"}

    # otherlisted.txt covers NYSE, AMEX, ARCA; nasdaqlisted.txt covers NASDAQ
    if exchange == "NASDAQ":
        url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    else:
        url = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        df = pd.read_csv(StringIO(r.text), sep="|")

        if exchange == "NASDAQ":
            # nasdaqlisted has no Exchange column — all rows are NASDAQ
            mask = (
                (df["Test Issue"] == "N") &
                (df["Symbol"].str.match(r"^[A-Z]{1,5}$"))
            )
            return df[mask]["Symbol"].tolist()
        else:
            code = exchange_code.get(exchange, "N")
            mask = (
                (df["Exchange"] == code) &
                (df["Test Issue"] == "N") &
                (df["ACT Symbol"].str.match(r"^[A-Z]{1,5}$"))
            )
            return df[mask]["ACT Symbol"].tolist()
    except Exception:
        return EXCHANGE_TICKERS[exchange]   # fallback to curated list

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    exchange  = st.selectbox("Exchange", ["NYSE", "NASDAQ", "AMEX"], index=0)
    st.markdown("---")
    smoothing = st.slider("Smoothing (day MA)", 1, 10, 1)

    st.markdown("---")
    if st.button("🔄 Force Refresh Data", use_container_width=True):
        load_price_data.clear()
        compute_breadth.clear()
        get_constituents.clear()
        st.success("Cache cleared — reloading data...")
        st.rerun()
    st.caption("Today's closing data available after 4:30 PM ET. Click to pull the latest.")
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
fetch_start = (datetime.today() - timedelta(days=365*5 + 270)).strftime("%Y-%m-%d")

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
_live_badge = (
    "<span style='background:#1a3a1a;color:#00e676;font-size:11px;padding:2px 7px;"
    "border-radius:3px;font-family:monospace;margin-left:12px'>● LIVE</span>"
    if _market_open else
    "<span style='background:#2a2a2a;color:#888;font-size:11px;padding:2px 7px;"
    "border-radius:3px;font-family:monospace;margin-left:12px'>MARKET CLOSED</span>"
)
_updated = datetime.now().strftime("%I:%M:%S %p")
st.markdown(
    f"### {INDEX_SYM[exchange]} Index &nbsp;&nbsp; {idx_last:,.2f} &nbsp;&nbsp; "
    f"<span style='color:{chg_color}'>{chg_sign}{idx_chg:,.2f} ({chg_sign}{idx_pct:.2f}%)</span>"
    f"{_live_badge}"
    f"<span style='color:#555;font-size:11px;font-family:monospace;margin-left:10px'>Updated {_updated}</span>",
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
        line=dict(color="#1565c0", width=1.2),
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
    modebar=dict(bgcolor="rgba(0,0,0,0)", color="#999", activecolor="#1565c0"),
)

# Both panels — single right-side y-axis
fig.update_yaxes(side="right", row=1, col=1, **ax_base)
fig.update_yaxes(side="right", row=2, col=1, **ax_base)

fig.update_xaxes(showgrid=True, gridcolor="#161616", tickfont=dict(color="#666", size=10, family="monospace"),
                 rangeslider_visible=False, **spike, row=1, col=1)
fig.update_xaxes(showgrid=True, gridcolor="#161616", tickfont=dict(color="#666", size=10, family="monospace"),
                 rangeslider_visible=False, **spike, row=2, col=1)

st.plotly_chart(fig, width="stretch", config={
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
    st.dataframe(display.iloc[::-1].head(120), width="stretch", height=320)
