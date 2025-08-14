# app.py — Live universes (India + Global) with bulk financials & Excel export
# requirements: streamlit, yfinance, pandas, openpyxl, fuzzywuzzy, python-Levenshtein, requests, lxml

import os, io, re, requests
import pandas as pd
import streamlit as st
import yfinance as yf
from fuzzywuzzy import process
# app.py — Polished UI/UX + Live universes + Bulk financials exporter
# requirements: streamlit, yfinance, pandas, openpyxl, fuzzywuzzy, python-Levenshtein, requests, lxml

# ---------- Page & Theme ----------

# ✅ Privacy note at the very top
st.warning(
    "⚠ *Privacy Notice:* This app does not store your inputs.\n"
    "Do not enter personal, confidential, or sensitive information."
)
st.set_page_config(
    page_title="Global & India Financials", layout="wide",
    page_icon="📊",
    layout="wide",
    menu_items={"about": "AI Financials — fetch, compare, and export financial statements fast."}
)

# Minimal CSS polish
st.markdown("""
<style>
/* Card-like containers */
.block-container {padding-top: 2rem; padding-bottom: 2rem;}
div.stButton > button, .stDownloadButton button { border-radius: 8px; padding: 0.6rem 1rem; font-weight: 600; }
.css-1dp5vir { padding-top: 0rem; }  /* reduce top gap on some themes */

/* Table tweaks */
[data-testid="stDataFrame"] .row_heading, [data-testid="stDataFrame"] .blank { display: none; }
[data-testid="stDataFrame"] table { border-radius: 8px; overflow: hidden; }

/* Subtle pill */
.pill {display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.85rem; background: #e6f4ff;}
.hero {padding: 12px 18px; border-radius: 12px; background: linear-gradient(90deg, rgba(98,161,255,.12), rgba(0,0,0,0));}
.small {opacity: 0.75;}
footer {visibility: hidden;} /* cleaner footer */
</style>
""", unsafe_allow_html=True)

# ---------- Header / Hero ----------
col1, col2 = st.columns([0.75, 0.25])
with col1:
    st.markdown("### 📊 AI‑Powered Financials")
    st.markdown(
        '<div class="hero">Fetch, compare, and export *Income, Balance Sheet, Cash Flow* for '
        '*Indian (₹ Crore)* and *Global (reported currency)* companies. Built for speed & clarity.</div>',
        unsafe_allow_html=True
    )
with col2:
    st.metric("Status", "Online")
    st.markdown('<span class="pill">Live universes</span> <span class="pill">Excel export</span> <span class="pill">Caching</span>', unsafe_allow_html=True)

# ---------- Optional OpenAI key (for free‑text parsing) ----------
def get_openai_key():
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return os.environ.get("OPENAI_API_KEY")

OPENAI_API_KEY = get_openai_key()
if OPENAI_API_KEY:
    import openai
    openai.api_key = OPENAI_API_KEY

with st.expander("Privacy & notes", expanded=False):
    st.write("• If OpenAI parsing is enabled, your text may be sent to OpenAI just to extract names.\n"
             "• Financials come from Yahoo Finance via yfinance. Some tickers may not expose statements.\n"
             "• Indian tickers (.NS) are displayed in ₹ Crore; global tickers in their reported currency.")

# ---------- Live universes (India + Global) ----------
NSE_URLS = {
    "NIFTY50":        "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTYNEXT50":    "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv",
    "NIFTY100":       "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTYMIDCAP100": "https://archives.nseindia.com/content/indices/ind_niftymidcap100list.csv",
}
WIKI_PAGES = {
    "SP100":      "https://en.wikipedia.org/wiki/S%26P_100",
    "SP500":      "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "NASDAQ100":  "https://en.wikipedia.org/wiki/NASDAQ-100",
    "FTSE100":    "https://en.wikipedia.org/wiki/FTSE_100_Index",
    "STOXX50":    "https://en.wikipedia.org/wiki/EURO_STOXX_50",
}

@st.cache_data(ttl=6*3600, show_spinner=True)
def build_india_universe():
    rows = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for uni, url in NSE_URLS.items():
        try:
            r = requests.get(url, timeout=20, headers=headers)
            r.raise_for_status()
            df = pd.read_csv(io.BytesIO(r.content))
            sym_col = next((c for c in df.columns if str(c).strip().lower().startswith("symbol")), None)
            name_col = next((c for c in df.columns if "company" in str(c).lower()), None)
            sector_col = next((c for c in df.columns if ("industry" in str(c).lower()) or ("sector" in str(c).lower())), None)
            symbol = df[sym_col].astype(str).str.upper().str.strip() if sym_col else None
            name = df[name_col].astype(str).str.strip() if name_col else symbol
            sector = df[sector_col].astype(str).str.strip() if sector_col else "NA"
            tmp = pd.DataFrame({
                "name": name,
                "symbol": symbol + ".NS",
                "market": uni,
                "sector": sector,
                "region": "India",
                "cap": ["Large" if any(x in uni for x in ("50","100")) else "NA"] * len(df),
            })
            rows.append(tmp)
        except Exception:
            continue
    return pd.concat(rows, ignore_index=True).drop_duplicates(subset=["symbol"]) if rows else pd.DataFrame()

def normalize_yahoo_symbol(sym: str) -> str:
    s = re.sub(r"\s+", "", str(sym).upper())
    return s.replace(".", "-")  # BRK.B -> BRK-B etc.

@st.cache_data(ttl=6*3600, show_spinner=True)
def build_global_universe():
    frames = []
    for uni, url in WIKI_PAGES.items():
        try:
            tables = pd.read_html(url)
            df = max(tables, key=lambda x: x.shape[0])
            tick_cols = [c for c in df.columns if re.search(r"(ticker|symbol|code)", str(c), re.I)]
            name_cols = [c for c in df.columns if re.search(r"(name|company)", str(c), re.I)]
            if not tick_cols: tick_cols = [df.columns[0]]
            if not name_cols: name_cols = [df.columns[1] if len(df.columns)>1 else df.columns[0]]
            ticks = df[tick_cols[0]].astype(str).str.strip().map(normalize_yahoo_symbol)
            names = df[name_cols[0]].astype(str).str.strip()
            g = pd.DataFrame({
                "name": names, "symbol": ticks,
                "market": uni, "sector": "NA", "region": "Global", "cap": "Large",
            })
            frames.append(g)
        except Exception:
            continue
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["symbol"]) if frames else pd.DataFrame()

india_universe  = build_india_universe()
global_universe = build_global_universe()

# ---------- Financials helpers ----------
def to_crore_if_nse(symbol, df):
    if isinstance(df, pd.DataFrame) and not df.empty and symbol.endswith(".NS"):
        df.iloc[:, 1:] = df.iloc[:, 1:].apply(pd.to_numeric, errors="ignore").applymap(
            lambda v: v/1e7 if isinstance(v, (int, float)) else v
        )
    return df

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_company_data(symbol):
    t = yf.Ticker(symbol)
    data = {
        "Income_Annual": t.financials.reset_index(),
        "Income_Qtr": t.quarterly_financials.reset_index(),
        "BS_Annual": t.balance_sheet.reset_index(),
        "BS_Qtr": t.quarterly_balance_sheet.reset_index(),
        "CF_Annual": t.cashflow.reset_index(),
        "CF_Qtr": t.quarterly_cashflow.reset_index(),
    }
    for k in data:
        data[k] = to_crore_if_nse(symbol, data[k])
    return data

def build_summary_row(symbol, data):
    units = "₹ Cr" if symbol.endswith(".NS") else "Reported"
    out = {"Company": symbol, "Latest Revenue": None, "Latest Net Income": None, "Units": units}
    inc = data.get("Income_Annual")
    if isinstance(inc, pd.DataFrame) and not inc.empty:
        latest = inc.rename(columns={"index":"Metric"}).iloc[:, [0,1]]
        s = latest["Metric"].astype(str).str.strip().str.lower()
        def pick(*keys):
            m = latest.loc[s.isin(keys)]
            return pd.to_numeric(m.iloc[0,1], errors="coerce") if not m.empty else None
        out["Latest Revenue"]    = pick("total revenue","totalrevenue")
        out["Latest Net Income"] = pick("net income","netincome")
    return out

# ---------- Tabs: Discover / Quick Search / Settings ----------
tab1, tab2, tab3 = st.tabs(["🧭 Discover & Compare", "🔎 Quick Search", "⚙ Settings"])

with tab1:
    # Filters row
    lcol, rcol = st.columns([0.65, 0.35])
    with lcol:
        market_choice = st.radio("Market universe", ["India","Global","Both"], horizontal=True)
    with rcol:
        st.caption("Tip: Pull 50–100 at a time on the free tier for best speed.")

    if market_choice == "India":
        uni = india_universe.copy()
    elif market_choice == "Global":
        uni = global_universe.copy()
    else:
        uni = pd.concat([india_universe, global_universe], ignore_index=True, sort=False)

    f1, f2, f3 = st.columns(3)
    with f1:
        by_list = st.multiselect("Filter by list", sorted(uni["market"].dropna().unique().tolist()))
    with f2:
        if "sector" in uni.columns:
            by_sector = st.multiselect("Sector (optional)", sorted(uni["sector"].dropna().unique().tolist()))
        else:
            by_sector = []
    with f3:
        search = st.text_input("Live search", placeholder="Type to filter by name or symbol...").strip().lower()

    if by_list:   uni = uni[uni["market"].isin(by_list)]
    if by_sector: uni = uni[uni["sector"].isin(by_sector)]
    if search:
        uni = uni[ uni["name"].str.lower().str.contains(search) | uni["symbol"].str.lower().str.contains(search) ]

    st.write(f"*Showing {len(uni)} companies*")
    st.dataframe(uni[["name","symbol","market","sector"]].reset_index(drop=True), use_container_width=True, height=360)

    # Selection row
    default_pick = min(50, len(uni))
    pick = st.multiselect("Select companies to fetch", options=uni["symbol"].tolist(), default=uni["symbol"].tolist()[:default_pick])
    c1, c2, c3 = st.columns([0.25,0.25,0.5])
    go = c1.button("🚀 Fetch Financials", use_container_width=True)
    clear = c2.button("Clear selection", use_container_width=True)
    if clear: pick = []

    if go:
        if not pick:
            st.warning("Select at least one company.")
            st.stop()

        # Progress row and stats cards
        pcol, k1, k2, k3 = st.columns([0.5, 0.166, 0.166, 0.166])
        progress = pcol.progress(0.0)
        fetched, failed = 0, 0

        rows, results, failures = [], {}, []
        for i, sym in enumerate(pick, start=1):
            try:
                data = fetch_company_data(sym)
                if any(isinstance(v, pd.DataFrame) and not v.empty for v in data.values()):
                    results[sym] = data
                    rows.append(build_summary_row(sym, data))
                    fetched += 1
                else:
                    failures.append(sym); failed += 1
            except Exception:
                failures.append(sym); failed += 1
            progress.progress(i/len(pick))
            k1.metric("Fetched", fetched)
            k2.metric("Failed", failed)
            k3.metric("Selected", len(pick))

        if failures:
            st.info("Skipped (no fundamentals): " + ", ".join(failures))

        summary = pd.DataFrame(rows)
        fmt = {}
        for col in ["Latest Revenue","Latest Net Income"]:
            if col in summary.columns and pd.api.types.is_numeric_dtype(summary[col]):
                fmt[col] = "{:,.2f}"

        st.subheader("📌 Financial Summary")
        st.dataframe(summary.style.format(fmt) if fmt else summary, use_container_width=True)

        # Export
        from io import BytesIO
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="Combined_Analysis", index=False)
            for sym, data in results.items():
                for key, df in data.items():
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        df = df.rename(columns={"index":"Metric"})
                        df.to_excel(writer, sheet_name=f"{sym}_{key}"[:31], index=False)
        bio.seek(0)
        st.download_button("📥 Download Excel", data=bio.read(),
                           file_name="financials_bulk.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

with tab2:
    st.write("Type names or tickers (comma or space separated).")
    q = st.text_input("e.g., Reliance, TCS, AAPL, MSFT", value="")
    if st.button("Detect & Preview"):
        if not q.strip():
            st.warning("Enter something to search.")
        else:
            # LLM parse if key present; else naive
            if OPENAI_API_KEY:
                try:
                    prompt = f'Extract company names/tickers from: "{q}". Return a comma-separated list only.'
                    resp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}])
                    text = resp.choices[0].message["content"].strip()
                    candidates = [x.strip() for x in text.split(",") if x.strip()]
                except Exception:
                    candidates = [x.strip() for x in q.replace(" and ", ",").split(",") if x.strip()]
            else:
                candidates = [x.strip() for x in q.replace(" and ", ",").split(",") if x.strip()]

            # India name map
            name_map = {r["name"]: r["symbol"] for _, r in india_universe.iterrows()}
            symbols = []
            for item in candidates:
                if item in name_map:
                    symbols.append(name_map[item])
                else:
                    # Accept tickers like AAPL, 7203.T, 0700.HK, BRK-B, INFY.NS
                    if re.match(r"^[A-Z0-9\-]+(\.[A-Z]{1,3})?$", item.upper()):
                        symbols.append(item.upper())
                    else:
                        match = process.extractOne(item, list(name_map.keys()))
                        if match and match[1] > 82:
                            symbols.append(name_map[match[0]])

            if not symbols:
                st.error("Couldn’t detect any valid tickers.")
            else:
                st.success("Detected: " + ", ".join(symbols))
                # light preview (top 10 of income annual)
                previews = []
                for s in symbols[:10]:
                    try:
                        data = fetch_company_data(s)
                        inc = data.get("Income_Annual")
                        if isinstance(inc, pd.DataFrame) and not inc.empty:
                            previews.append((s, inc.rename(columns={"index":"Metric"}).head(10)))
                    except Exception:
                        pass
                if previews:
                    for s, df in previews:
                        st.markdown(f"{s} — Income (Annual) sample**")
                        st.dataframe(df, use_container_width=True)

with tab3:
    st.write("*Settings*")
    st.write("- Caching: universes (6h), financials (30m).")
    st.write("- Indian tickers show ₹ Crore; global tickers show reported currency.")
    st.write("- Use the *Discover* tab for bulk fetch & export. Use *Quick Search* for ad‑hoc checks.")
    if OPENAI_API_KEY:
        st.success("LLM parsing: ON (key detected).")
    else:
        st.info("LLM parsing: OFF — set OPENAI_API_KEY in Secrets to enable.")
st.set_page_config(page_title="AI-Powered Global & India Financials", layout="wide")

# ---------------- Secrets / OpenAI (optional LLM parsing) ----------------
def get_openai_key():
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return os.environ.get("OPENAI_API_KEY")

OPENAI_API_KEY = get_openai_key()
if OPENAI_API_KEY:
    import openai
    openai.api_key = OPENAI_API_KEY
st.caption("Income, Balance Sheet, Cash Flow (Annual & Quarterly) • ₹ Crore for NSE • Excel export")

st.warning(
    "⚠ *Privacy Notice:* This app doesn’t store your inputs. "
    "If OpenAI parsing is enabled, your query text may be sent to OpenAI to extract company names. "
    "Please avoid entering personal/sensitive information."
)

# ---------------- Live builders: India (NSE) & Global universes ----------------
NSE_URLS = {
    "NIFTY50":        "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTYNEXT50":    "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv",
    "NIFTY100":       "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTYMIDCAP100": "https://archives.nseindia.com/content/indices/ind_niftymidcap100list.csv",
}

WIKI_PAGES = {
    "SP100":      "https://en.wikipedia.org/wiki/S%26P_100",
    "SP500":      "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "NASDAQ100":  "https://en.wikipedia.org/wiki/NASDAQ-100",
    "FTSE100":    "https://en.wikipedia.org/wiki/FTSE_100_Index",
    "STOXX50":    "https://en.wikipedia.org/wiki/EURO_STOXX_50",
}

@st.cache_data(ttl=6*3600, show_spinner=True)
def build_india_universe():
    rows = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for uni, url in NSE_URLS.items():
        try:
            r = requests.get(url, timeout=20, headers=headers)
            r.raise_for_status()
            df = pd.read_csv(io.BytesIO(r.content))

            sym_col   = next((c for c in df.columns if str(c).strip().lower().startswith("symbol")), None)
            name_col  = next((c for c in df.columns if "company" in str(c).lower()), None)
            sector_col= next((c for c in df.columns if ("industry" in str(c).lower()) or ("sector" in str(c).lower())), None)

            symbol = df[sym_col].astype(str).str.upper().str.strip() if sym_col else None
            name   = df[name_col].astype(str).str.strip() if name_col else symbol
            sector = df[sector_col].astype(str).str.strip() if sector_col else "NA"

            tmp = pd.DataFrame({
                "name": name,
                "symbol": symbol + ".NS",
                "market": uni,
                "sector": sector,
                "region": "India",
                "cap": ["Large" if any(x in uni for x in ("50","100")) else "NA"] * len(df),
            })
            rows.append(tmp)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame(columns=["name","symbol","market","sector","region","cap"])
    india = pd.concat(rows, ignore_index=True).drop_duplicates(subset=["symbol"])
    return india

def normalize_yahoo_symbol(sym: str) -> str:
    s = re.sub(r"\s+", "", str(sym).upper())
    return s.replace(".", "-")  # BRK.B -> BRK-B etc.

@st.cache_data(ttl=6*3600, show_spinner=True)
def build_global_universe():
    frames = []
    for uni, url in WIKI_PAGES.items():
        try:
            tables = pd.read_html(url)
            df = max(tables, key=lambda x: x.shape[0])  # largest table
            tick_cols = [c for c in df.columns if re.search(r"(ticker|symbol|code)", str(c), re.I)]
            name_cols = [c for c in df.columns if re.search(r"(name|company)", str(c), re.I)]
            if not tick_cols: tick_cols = [df.columns[0]]
            if not name_cols: name_cols = [df.columns[1] if len(df.columns)>1 else df.columns[0]]

            ticks = df[tick_cols[0]].astype(str).str.strip().map(normalize_yahoo_symbol)
            names = df[name_cols[0]].astype(str).str.strip()
            g = pd.DataFrame({
                "name": names,
                "symbol": ticks,
                "market": uni,
                "sector": "NA",
                "region": "Global",
                "cap": "Large",
            })
            frames.append(g)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["name","symbol","market","sector","region","cap"])
    global_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["symbol"])
    return global_df

# Build both (live)
india_universe  = build_india_universe()
global_universe = build_global_universe()

# ---------------- Financials helpers ----------------
def to_crore_if_nse(symbol, df):
    if isinstance(df, pd.DataFrame) and not df.empty and symbol.endswith(".NS"):
        df.iloc[:, 1:] = df.iloc[:, 1:].apply(pd.to_numeric, errors="ignore").applymap(
            lambda v: v/1e7 if isinstance(v, (int, float)) else v
        )
    return df

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_company_data(symbol):
    t = yf.Ticker(symbol)
    data = {
        "Income_Annual": t.financials.reset_index(),
        "Income_Qtr": t.quarterly_financials.reset_index(),
        "BS_Annual": t.balance_sheet.reset_index(),
        "BS_Qtr": t.quarterly_balance_sheet.reset_index(),
        "CF_Annual": t.cashflow.reset_index(),
        "CF_Qtr": t.quarterly_cashflow.reset_index(),
    }
    for k in data:
        data[k] = to_crore_if_nse(symbol, data[k])
    return data

def build_summary_row(symbol, data):
    units = "₹ Cr" if symbol.endswith(".NS") else "Reported Currency"
    out = {"Company": symbol, "Latest Revenue": None, "Latest Net Income": None, "Units": units}
    inc = data.get("Income_Annual")
    if isinstance(inc, pd.DataFrame) and not inc.empty:
        latest = inc.rename(columns={"index":"Metric"}).iloc[:, [0,1]]
        s = latest["Metric"].astype(str).str.strip().str.lower()
        def pick(*keys):
            m = latest.loc[s.isin(keys)]
            return pd.to_numeric(m.iloc[0,1], errors="coerce") if not m.empty else None
        out["Latest Revenue"]   = pick("total revenue","totalrevenue")
        out["Latest Net Income"]= pick("net income","netincome")
    return out

# ---------------- UI: universes & bulk fetch ----------------
st.sidebar.header("Universe")
market_choice = st.sidebar.radio("Select", ["India","Global","Both"], index=0)

if market_choice == "India":
    uni = india_universe.copy()
elif market_choice == "Global":
    uni = global_universe.copy()
else:
    uni = pd.concat([india_universe, global_universe], ignore_index=True, sort=False)

if uni.empty:
    st.error("Couldn’t load universes (network blocked?). Try again later.")
    st.stop()

by_market = st.sidebar.multiselect("Filter by list (optional)", sorted(uni["market"].dropna().unique().tolist()))
if by_market:
    uni = uni[uni["market"].isin(by_market)]

if "sector" in uni.columns:
    by_sector = st.sidebar.multiselect("Filter by sector (optional)", sorted(uni["sector"].dropna().unique().tolist()))
    if by_sector:
        uni = uni[uni["sector"].isin(by_sector)]

default_pick = min(50, len(uni))
symbols_to_pull = st.sidebar.multiselect(
    "Pick companies", options=uni["symbol"].tolist(), default=uni["symbol"].tolist()[:default_pick]
)
st.sidebar.write(f"Selected: {len(symbols_to_pull)}")

if st.button("Fetch Selected Companies"):
    if not symbols_to_pull:
        st.warning("No symbols selected.")
        st.stop()

    progress = st.progress(0.0)
    rows, results, failures = [], {}, []
    for i, sym in enumerate(symbols_to_pull, start=1):
        try:
            data = fetch_company_data(sym)
            if any(isinstance(v, pd.DataFrame) and not v.empty for v in data.values()):
                results[sym] = data
                rows.append(build_summary_row(sym, data))
            else:
                failures.append(sym)
        except Exception:
            failures.append(sym)
        progress.progress(i/len(symbols_to_pull))

    st.success(f"Fetched {len(results)} / {len(symbols_to_pull)}")
    if failures:
        st.warning("No fundamentals for: " + ", ".join(failures))

    summary = pd.DataFrame(rows)
    fmt = {}
    for col in ["Latest Revenue","Latest Net Income"]:
        if col in summary.columns and pd.api.types.is_numeric_dtype(summary[col]):
            fmt[col] = "{:,.2f}"

    st.subheader("📌 Financial Summary (Preview)")
    st.dataframe(summary.style.format(fmt) if fmt else summary, use_container_width=True)

    # Excel export
    from io import BytesIO
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Combined_Analysis", index=False)
        for sym, data in results.items():
            for key, df in data.items():
                if isinstance(df, pd.DataFrame) and not df.empty:
                    df = df.rename(columns={"index":"Metric"})
                    df.to_excel(writer, sheet_name=f"{sym}_{key}"[:31], index=False)
    bio.seek(0)
    st.download_button(
        "📥 Download All Financials (Excel)",
        data=bio.read(),
        file_name="financials_bulk.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ---------------- Optional: quick free‑text fetch ----------------
st.divider()
q = st.text_input("Quick fetch (names or tickers, comma/space separated):", "Reliance, TCS, AAPL, MSFT")
if st.button("Quick Fetch"):
    # simple parse (LLM optional)
    if OPENAI_API_KEY:
        try:
            prompt = f'Extract only company names/tickers from: "{q}". Return comma-separated, no extra words.'
            resp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}])
            text = resp.choices[0].message["content"].strip()
            candidates = [x.strip() for x in text.split(",") if x.strip()]
        except Exception:
            candidates = [x.strip() for x in q.replace(" and ", ",").split(",") if x.strip()]
    else:
        candidates = [x.strip() for x in q.replace(" and ", ",").split(",") if x.strip()]

    # quick resolve: use India names map first, else accept ticker-looking strings
    name_map = {r["name"]: r["symbol"] for _, r in india_universe.iterrows()}
    symbols = []
    for item in candidates:
        if item in name_map:
            symbols.append(name_map[item])
        else:
            # Accept raw tickers like AAPL, MSFT, TSM, 7203.T, 0700.HK, BRK-B, INFY.NS
            if re.match(r"^[A-Z0-9\-]+(\.[A-Z]{1,3})?$", item.upper()):
                symbols.append(item.upper())
            else:
                match = process.extractOne(item, list(name_map.keys()))
                if match and match[1] > 82:
                    symbols.append(name_map[match[0]])

    st.info("Detected: " + (", ".join(symbols) if symbols else "(none)"))
