import os
import streamlit as st
import pandas as pd
import yfinance as yf
from fuzzywuzzy import process

# ---------- CONFIG ----------
# Read OpenAI key from Streamlit secrets (set in Streamlit Cloud)
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY", None)
if OPENAI_KEY:
    import openai
    openai.api_key = OPENAI_KEY
else:
    openai = None  # we’ll gracefully degrade if not set

st.set_page_config(page_title="AI Financials (India)", page_icon="📊", layout="wide")

# Minimal map—extend as you like
COMPANY_MAP = {
    "Reliance": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "Tata Consultancy": "TCS.NS",
    "HDFC Bank": "HDFCBANK.NS",
    "Infosys": "INFY.NS",
    "Wipro": "WIPRO.NS",
    "ICICI Bank": "ICICIBANK.NS",
    "Axis Bank": "AXISBANK.NS",
    "HUL": "HINDUNILVR.NS",
}

# ---------- HELPERS ----------
def match_company(name: str) -> str:
    """Fuzzy map plain names to NSE tickers; else return as-is (assume ticker)."""
    m, s = process.extractOne(name, COMPANY_MAP.keys())
    return COMPANY_MAP[m] if s > 70 else name.strip()

def to_crore(val):
    try:
        return val / 1e7
    except Exception:
        return val

def add_growth(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns[1:]:
        if pd.api.types.is_numeric_dtype(out[col]):
            out[f"{col}_Growth%"] = out[col].pct_change() * 100
    return out

@st.cache_data(show_spinner=False)
def fetch_company_data(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    data = {
        "Income_Annual": t.financials.reset_index(),
        "Income_Qtr": t.quarterly_financials.reset_index(),
        "BS_Annual": t.balance_sheet.reset_index(),
        "BS_Qtr": t.quarterly_balance_sheet.reset_index(),
        "CF_Annual": t.cashflow.reset_index(),
        "CF_Qtr": t.quarterly_cashflow.reset_index(),
    }
    for k in list(data.keys()):
        df = data[k]
        if df.empty:
            # protect against tickers with no fundamentals on Yahoo
            continue
        df.iloc[:, 1:] = df.iloc[:, 1:].applymap(to_crore)
        data[k] = add_growth(df)
    return data

def build_summary_row(symbol: str, data: dict) -> dict:
    inc = data.get("Income_Annual")
    rev = ni = None
    if isinstance(inc, pd.DataFrame) and not inc.empty:
        latest = inc.iloc[:, [0, 1]]
        try:
            rev = latest[latest["index"].isin(["Total Revenue","TotalRevenue","Total revenue"])].iloc[0, 1]
        except Exception:
            pass
        try:
            ni = latest[latest["index"].isin(["Net Income","NetIncome","Net income"])].iloc[0, 1]
        except Exception:
            pass
    return {"Company": symbol, "Latest Revenue (₹ Cr)": rev, "Latest Net Income (₹ Cr)": ni}

def parse_companies_from_text(q: str) -> list:
    """If OpenAI key is set, use LLM; else naive split on commas."""
    if openai is None:
        # fallback: split by commas and spaces
        rough = [x.strip() for x in q.replace(" and ", ",").split(",") if x.strip()]
        return rough
    prompt = f'Extract only company names from: "{q}". Return a plain comma-separated list, no extra words.'
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}]
        )
        text = resp.choices[0].message["content"].strip()
        return [x.strip() for x in text.split(",") if x.strip()]
    except Exception:
        # graceful degradation
        return [x.strip() for x in q.replace(" and ", ",").split(",") if x.strip()]

def generate_excel(symbols: list) -> bytes:
    """Return Excel file bytes for download."""
    from io import BytesIO
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        combined = []
        for sym in symbols:
            data = fetch_company_data(sym)
            for key, df in data.items():
                if isinstance(df, pd.DataFrame) and not df.empty:
                    # Rename metric column nicely
                    df = df.rename(columns={"index": "Metric"})
                    sheet = f"{sym}_{key}"[:31]  # Excel sheet name limit
                    df.to_excel(writer, sheet_name=sheet, index=False)
            combined.append(build_summary_row(sym, data))
        pd.DataFrame(combined).to_excel(writer, sheet_name="Combined_Analysis", index=False)
    bio.seek(0)
    return bio.read()

# ---------- UI ----------
st.title("📊 AI-Powered Indian Stock Financials (Streamlit Cloud)")
# ✅ Privacy note
st.warning(
    "⚠ *Privacy Notice:* This app does not store your inputs or data. "
    "If OpenAI parsing is enabled, your query text is sent securely to OpenAI for processing. "
    "Do not enter personal, confidential, or sensitive information."
)

st.caption("Income, Balance Sheet, Cash Flow (Annual & Quarterly) • ₹ Crore • YoY/QoQ growth • Excel export")

q = st.text_input(
    "Ask for financials (names or tickers, comma-separated or natural language):",
    "Reliance, TCS, Infosys"
)

go = st.button("Fetch Financials")
if go:
    with st.spinner("Parsing companies…"):
        names = parse_companies_from_text(q)
        symbols = [match_company(n) for n in names]
        st.write("*Detected symbols:*", ", ".join(symbols))

    # Preview summary
    rows = []
    for sym in symbols:
        with st.spinner(f"Fetching {sym}…"):
            data = fetch_company_data(sym)
            rows.append(build_summary_row(sym, data))

    summary = pd.DataFrame(rows)
    st.subheader("📌 Financial Summary (Preview)")
    st.dataframe(summary.style.format({"Latest Revenue (₹ Cr)":"{:,.2f}", "Latest Net Income (₹ Cr)":"{:,.2f}"}), use_container_width=True)

    # Download full Excel
    excel_bytes = generate_excel(symbols)
    st.download_button(
        "📥 Download Full Financials Excel",
        data=excel_bytes,
        file_name="company_financials.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

st.markdown(
    """
    *Notes*
    - Data source: Yahoo Finance fundamentals via yfinance.  
    - All figures converted to ₹ Crore. Growth % is computed column-wise.  
    - If you don’t set OPENAI_API_KEY, the app still works (basic parsing).
    """
)
