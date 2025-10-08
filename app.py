# --- Small Dams – Daily Dashboard ---
# Works with a normal Google Sheets link (edit/share) or a published CSV.
# If no secret is set, you can paste the URL in the sidebar.

import re
import pandas as pd
import streamlit as st
import plotly.express as px
from dateutil import parser
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Small Dams Dashboard", layout="wide")
st.title("🏞️ Small Dams – Daily Dashboard")

# ---- Auto-refresh every 5 minutes (change/remove)
st_autorefresh(interval=300_000, key="auto")  # 5 minutes

# ---- Your sheet link (fallback). You can keep/replace this with your link.
DEFAULT_SHEET_LINK = "https://docs.google.com/spreadsheets/d/1FIrts6crhKvuqc566gh-PTNYshT30NvfUV1pxCvDxp0/edit?usp=sharing"

def to_csv_url(any_google_sheet_url: str) -> str:
    """
    Accepts:
      - /edit?usp=sharing link
      - published /pub?output=csv link
      - /export?format=csv&gid=... link
    Returns a CSV endpoint. Tries to preserve gid (tab).
    """
    if not any_google_sheet_url:
        return ""

    u = any_google_sheet_url.strip()

    # Already a published CSV or export CSV
    if "output=csv" in u or "format=csv" in u:
        return u

    # Typical share link: https://docs.google.com/spreadsheets/d/<ID>/edit?gid=123#gid=123
    try:
        parts = u.split("/")
        doc_id = parts[5]  # after '/d/'
    except Exception:
        return u

    # Try to preserve gid if present
    qs_gid = None
    try:
        parsed = urlparse(u)
        q = parse_qs(parsed.query)
        if "gid" in q:
            qs_gid = q["gid"][0]
    except Exception:
        pass

    if qs_gid:
        return f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv&gid={qs_gid}"
    else:
        # default to first sheet if gid unknown
        return f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv"

# ---------- Resolve sheet URL (secret → fallback → sidebar) ----------
sheet_url_raw = st.secrets.get("SHEET_PUBLISHED_CSV", DEFAULT_SHEET_LINK)
sheet_csv_url = to_csv_url(sheet_url_raw)

if not sheet_csv_url:
    st.sidebar.warning("Paste your Google Sheet link below (edit/share or published CSV).")
    pasted = st.sidebar.text_input("Google Sheet URL", value="")
    sheet_csv_url = to_csv_url(pasted)
    if not sheet_csv_url:
        st.stop()

# ---- Load sheet
@st.cache_data(ttl=300)  # 5min cache
def load_sheet(csv_url: str) -> pd.DataFrame:
    df = pd.read_csv(csv_url)
    # normalize headers (based on your screenshot)
    df.columns = [c.strip() for c in df.columns]
    rename_map = {
        "SR. No": "SR_No",
        "Name Of Dam": "Dam",
        "Top of Dam FT": "Top_FT",
        "H.F.L Ft": "HFL_FT",
        "D.S.L Ft": "DSL_FT",
        "N.P.L Ft": "NPL_FT",
        "P.P.L Ft": "PPL_FT",
        "Spill_Diff": "Spill_Diff",
        "Total Live Storage": "Live_Storage",
        "Status": "Status",
        "Date": "Date",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # parse Date (looks like dd/mm/yy in your sheet)
    def parse_date(x):
        try:
            return parser.parse(str(x), dayfirst=True).date()
        except Exception:
            return pd.NaT

    if "Date" in df.columns:
        df["Date"] = df["Date"].apply(parse_date)
    else:
        st.error("No 'Date' column found after loading. Check your sheet headers.")
        return pd.DataFrame()

    # extract numeric "Live depth" from Status like "9.80 Ft Live"; keep NaN for "Dead"
    def extract_live_ft(s):
        if pd.isna(s):
            return pd.NA
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*Ft", str(s))
        return float(m.group(1)) if m else pd.NA

    if "Status" in df.columns:
        df["LiveDepth_FT"] = df["Status"].apply(extract_live_ft)
    else:
        df["LiveDepth_FT"] = pd.NA

    # basic flags
    if "Spill_Diff" in df.columns:
        df["Is_Spilling"] = pd.to_numeric(df["Spill_Diff"], errors="coerce") < 0
    else:
        df["Is_Spilling"] = False

    # dam column
    if "Dam" not in df.columns:
        # attempt a fallback if header slightly differs
        candidates = [c for c in df.columns if "name" in c.lower() and "dam" in c.lower()]
        if candidates:
            df = df.rename(columns={candidates[0]: "Dam"})
        else:
            df["Dam"] = "Unknown"

    return df

df = load_sheet(sheet_csv_url).copy()
if df.empty:
    st.stop()

# ---- sidebar filters
st.sidebar.header("Filters")
dates = sorted(d for d in df["Date"].dropna().unique())
date_sel = st.sidebar.selectbox("Date", options=dates, index=len(dates) - 1 if dates else 0)
dams = ["All"] + sorted(df["Dam"].dropna().unique().tolist())
dam_sel = st.sidebar.selectbox("Dam", options=dams, index=0)

# ---- filter data
df_day = df[df["Date"] == date_sel].copy()
if dam_sel != "All":
    df_view = df[(df["Dam"] == dam_sel)].sort_values("Date")
else:
    df_view = df_day.copy()

# ---- KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Dams reported", f"{df_day['Dam'].nunique()}")
c2.metric("Spilling (count)", f"{int(df_day['Is_Spilling'].sum())}")
live_today = df_day["LiveDepth_FT"].dropna()
c3.metric("Median Live Depth (ft)", f"{live_today.median():.2f}" if not live_today.empty else "—")
c4.metric("Dead / No Live", f"{int(df_day['LiveDepth_FT'].isna().sum())}")

# ---- Chart 1: Today’s Live Depth by Dam (bar)
st.subheader(f"Live Depth by Dam — {date_sel}")
bar_cols = ["Dam", "LiveDepth_FT"]
if all(col in df_day.columns for col in bar_cols) and not df_day.empty:
    fig_bar = px.bar(
        df_day.sort_values("LiveDepth_FT", na_position="last"),
        x="Dam", y="LiveDepth_FT", color="Is_Spilling",
        title="LiveDepth_FT (ft) — red = spilling",
    )
    st.plotly_chart(fig_bar, use_container_width=True)
else:
    st.info("No data for selected date.")

# ---- Chart 2: Time series for a selected dam (or overview)
if dam_sel != "All":
    st.subheader(f"Trend — {dam_sel}")
    fig_line = px.line(
        df_view.sort_values("Date"),
        x="Date", y=["LiveDepth_FT"],
        markers=True, title=f"LiveDepth_FT over time — {dam_sel}"
    )
    st.plotly_chart(fig_line, use_container_width=True)
else:
    st.subheader("Today — table view")
    show_cols = [c for c in ["Dam","LiveDepth_FT","Spill_Diff","HFL_FT","NPL_FT","PPL_FT","DSL_FT","Live_Storage","Status"] if c in df_day.columns]
    st.dataframe(df_day[show_cols].sort_values("Dam"), use_container_width=True, height=420)

st.caption(f"Last refreshed: {datetime.now():%Y-%m-%d %H:%M:%S} • Auto-refresh every 5 min • Edit columns/names in app.py")
