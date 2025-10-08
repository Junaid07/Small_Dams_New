import re
import pandas as pd
import streamlit as st
import plotly.express as px
from dateutil import parser
from datetime import datetime

st.set_page_config(page_title="Small Dams Dashboard", layout="wide")
st.title("🏞️ Small Dams – Daily Dashboard")

# ---- Auto-refresh every 5 minutes (change or remove)
st.autorefresh(interval=300_000, key="auto")

# ---- Load sheet
@st.cache_data(ttl=300)  # 5min cache
def load_sheet():
    url = st.secrets["SHEET_PUBLISHED_CSV"]
    df = pd.read_csv(url)

    # --- normalize headers you showed in the screenshot
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
    df = df.rename(columns={k:v for k,v in rename_map.items() if k in df.columns})

    # --- parse Date (your sheet looks like dd/mm/yy)
    def parse_date(x):
        try:
            return parser.parse(str(x), dayfirst=True).date()
        except Exception:
            return pd.NaT
    df["Date"] = df["Date"].apply(parse_date)

    # --- extract numeric "Live depth" from Status like "9.80 Ft Live", keep NaN for "Dead"
    def extract_live_ft(s):
        if pd.isna(s): return pd.NA
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*Ft", str(s))
        return float(m.group(1)) if m else pd.NA
    df["LiveDepth_FT"] = df["Status"].apply(extract_live_ft)

    # --- basic flags
    if "Spill_Diff" in df.columns:
        # negative Spill_Diff looks like spill (per your screenshot)
        df["Is_Spilling"] = pd.to_numeric(df["Spill_Diff"], errors="coerce") < 0
    else:
        df["Is_Spilling"] = False

    return df

df = load_sheet().copy()

# ---- sidebar filters
st.sidebar.header("Filters")
dates = sorted(d for d in df["Date"].dropna().unique())
date_sel = st.sidebar.selectbox("Date", options=dates, index=len(dates)-1 if dates else 0)
dams = ["All"] + sorted(df["Dam"].dropna().unique().tolist())
dam_sel = st.sidebar.selectbox("Dam", options=dams, index=0)

# ---- filter data
df_day = df[df["Date"] == date_sel].copy()
if dam_sel != "All":
    df_view = df[(df["Dam"] == dam_sel)].sort_values("Date")
else:
    df_view = df[df["Date"] == date_sel].copy()

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
