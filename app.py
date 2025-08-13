# app.py — Live universes (India + Global) with bulk financials & Excel export
# requirements: streamlit, yfinance, pandas, openpyxl, fuzzywuzzy, python-Levenshtein, requests, lxml

import os, io, re, requests
import pandas as pd
import streamlit as st
import yfinance as yf
from fuzzywuzzy import process

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
