"""
app.py — Recruiting CRM Dashboard (home page)
Run with: streamlit run app.py
"""

import sys
from pathlib import Path
from datetime import date

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent))
from supabase_helper import SupabaseHelper

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Recruiting CRM",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 2rem; }
    .block-container { padding-top: 1.5rem; }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ── DB connection ─────────────────────────────────────────────────────────────

@st.cache_resource
def get_db():
    return SupabaseHelper()

@st.cache_data(ttl=30)
def load_companies():
    return get_db().get_all_companies()

@st.cache_data(ttl=30)
def load_contacts():
    db = get_db()
    res = db.client.table("contacts").select("*, companies(name)").execute()
    return res.data or []

@st.cache_data(ttl=30)
def load_interactions():
    db = get_db()
    res = db.client.table("interactions").select("*, companies(name), contacts(name)").execute()
    return res.data or []

@st.cache_data(ttl=30)
def load_applications():
    return get_db().get_all_applications()

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🚀 Recruiting CRM")
st.caption(f"HBS MBA 2027 · Series A Internship Pipeline · {date.today().strftime('%B %d, %Y')}")
st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────

try:
    companies    = load_companies()
    contacts     = load_contacts()
    interactions = load_interactions()
    applications = load_applications()
except Exception as e:
    st.error(f"Could not connect to Supabase: {e}")
    st.info("Make sure SUPABASE_URL and SUPABASE_SERVICE_KEY are set in your .env file.")
    st.stop()

df_co  = pd.DataFrame(companies)
df_con = pd.DataFrame(contacts)
df_int = pd.DataFrame(interactions)
df_app = pd.DataFrame(applications)

# ── KPI metrics ───────────────────────────────────────────────────────────────

col1, col2, col3, col4, col5, col6 = st.columns(6)

total          = len(df_co)
tier1          = len(df_co[df_co.get("outreach_tier", pd.Series(dtype=str)) == "Tier 1 (HBS/Warm)"]) if not df_co.empty else 0
hbs_companies  = int(df_co["hbs_alumni_at_company"].sum()) if not df_co.empty and "hbs_alumni_at_company" in df_co.columns else 0
total_contacts = len(df_con)
messaged       = len(df_con[df_con.get("status", pd.Series(dtype=str)) != "Not Contacted"]) if not df_con.empty else 0
active_apps    = len(df_app[~df_app.get("status", pd.Series(dtype=str)).isin(["Rejected", "Withdrawn"])]) if not df_app.empty else 0

col1.metric("Companies", total)
col2.metric("Tier 1 (HBS)", tier1)
col3.metric("HBS Alumni Found", hbs_companies)
col4.metric("Contacts", total_contacts)
col5.metric("Messaged", messaged)
col6.metric("Applications", active_apps)

st.divider()

# ── Main layout ───────────────────────────────────────────────────────────────

left, right = st.columns([6, 4])

# ── Pipeline funnel ───────────────────────────────────────────────────────────

with left:
    st.subheader("📊 Pipeline Funnel")

    status_order = [
        "Not Started", "Researching", "Contacted",
        "Replied", "Coffee Chat Scheduled", "Coffee Chat Done", "Applied"
    ]

    if not df_co.empty and "status" in df_co.columns:
        status_counts = df_co["status"].value_counts().to_dict()
        funnel_vals  = [status_counts.get(s, 0) for s in status_order]
        funnel_vals  = [v for v, s in zip(funnel_vals, status_order) if v > 0]
        funnel_labels = [s for s, v in zip(status_order, [status_counts.get(s, 0) for s in status_order]) if v > 0]

        fig = go.Figure(go.Funnel(
            y=funnel_labels,
            x=funnel_vals,
            textinfo="value+percent initial",
            marker=dict(color=[
                "#6c757d", "#adb5bd", "#4361ee",
                "#3a0ca3", "#f72585", "#b5179e", "#7209b7"
            ][:len(funnel_labels)]),
            connector=dict(line=dict(color="#dee2e6", width=1)),
        ))
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=10),
            height=320,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(size=13),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No company data yet — run `filter_companies.py` first.")

    # Status breakdown table
    if not df_co.empty and "status" in df_co.columns:
        breakdown = df_co["status"].value_counts().reset_index()
        breakdown.columns = ["Status", "Count"]
        st.dataframe(breakdown, hide_index=True, use_container_width=True, height=200)

# ── Action items ──────────────────────────────────────────────────────────────

with right:
    st.subheader("⚡ Action Items")

    # Follow-ups due
    today_str = date.today().isoformat()
    if not df_int.empty and "followup_due" in df_int.columns:
        overdue = df_int[
            (df_int["followup_due"].notna()) &
            (df_int["followup_due"] <= today_str) &
            (df_int.get("followup_sent", pd.Series([True]*len(df_int))) == False)
        ]
        if len(overdue) > 0:
            st.error(f"🔔 **{len(overdue)} follow-up(s) due today**")
            for _, row in overdue.head(3).iterrows():
                co_name = row.get("companies", {})
                if isinstance(co_name, dict):
                    co_name = co_name.get("name", "?")
                st.caption(f"↩ {co_name} — {row.get('type', 'Follow-up')}")
        else:
            st.success("✅ No follow-ups overdue")
    else:
        st.success("✅ No follow-ups overdue")

    st.divider()

    # Top uncontacted Tier 1 companies (HBS alumni, not started)
    st.markdown("**🎯 Top Tier 1 — Not Yet Contacted**")
    if not df_co.empty:
        uncontacted_t1 = df_co[
            (df_co.get("outreach_tier", pd.Series(dtype=str)) == "Tier 1 (HBS/Warm)") &
            (df_co.get("status", pd.Series(dtype=str)) == "Not Started")
        ].sort_values("fit_score", ascending=False).head(5)

        if len(uncontacted_t1) > 0:
            for _, row in uncontacted_t1.iterrows():
                st.markdown(
                    f"• **{row['name']}** "
                    f"<span style='color:#6c757d;font-size:0.85rem'>"
                    f"{row.get('stage_estimate','?')} · fit {row.get('fit_score','?')}"
                    f"</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("All Tier 1 companies have been contacted 🎉")
    else:
        st.caption("No companies loaded yet.")

    st.divider()

    # Recently added contacts
    st.markdown("**👥 Recently Added Contacts**")
    if not df_con.empty:
        recent = df_con.sort_values("created_at", ascending=False).head(5) if "created_at" in df_con.columns else df_con.head(5)
        for _, row in recent.iterrows():
            co = row.get("companies", {})
            co_name = co.get("name", "?") if isinstance(co, dict) else "?"
            hbs = "🎓 " if row.get("hbs_alumni") else ""
            st.caption(f"{hbs}{row.get('name','?')} @ {co_name}")
    else:
        st.caption("No contacts yet — run the batch scraper first.")

# ── Weekly KPI targets ────────────────────────────────────────────────────────

st.divider()
st.subheader("📈 Weekly Targets")

kpi1, kpi2, kpi3, kpi4 = st.columns(4)

week_contacted  = len(df_int[df_int["created_at"] >= f"{date.today().isoformat()[:8]}01"] ) if not df_int.empty and "created_at" in df_int.columns else 0

kpi1.metric("Outreach sent (target: 10/wk)",  week_contacted,  delta=f"{week_contacted - 10} vs target")
kpi2.metric("Coffee chats (target: 3/wk)",
    len(df_int[df_int.get("type", pd.Series(dtype=str)) == "Coffee Chat"]) if not df_int.empty else 0)
kpi3.metric("New contacts found",  total_contacts)
kpi4.metric("Active applications", active_apps)
