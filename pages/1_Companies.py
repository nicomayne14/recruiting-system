"""
pages/1_Companies.py — Company pipeline view
Browse, filter, add, and update companies.
"""

import sys
from pathlib import Path
import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from supabase_helper import SupabaseHelper

st.set_page_config(page_title="Companies · CRM", page_icon="🏢", layout="wide")

# ── Constants ──────────────────────────────────────────────────────────────────

STATUS_OPTIONS  = ["Not Started", "Researching", "Contacted", "Replied",
                   "Coffee Chat Scheduled", "Coffee Chat Done", "Applied", "Pass"]
TIER_OPTIONS    = ["Tier 1 (HBS/Warm)", "Tier 2 (Founder Direct)", "Tier 3 (Cold)"]
STAGE_OPTIONS   = ["Seed", "Series A", "Series B", "Series C+", "Unknown"]
SECTOR_OPTIONS  = ["Mobility", "Marketplace", "Vertical SaaS", "CleanTech",
                   "DataCenters", "AI", "FinTech", "Other"]

@st.cache_resource
def get_db():
    return SupabaseHelper()

@st.cache_data(ttl=30)
def load_companies():
    return get_db().get_all_companies()

def refresh():
    st.cache_data.clear()
    st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────

st.title("🏢 Companies")
st.caption("Your filtered target list. Click any row to update status.")
st.divider()

companies = load_companies()
if not companies:
    st.info("No companies loaded yet. Run `python agents/filter_companies.py --data-dir ~/Desktop/Recruiting/data` first.")
    st.stop()

df = pd.DataFrame(companies)

# ── Sidebar filters ────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("🔍 Filters")

    status_filter = st.multiselect("Status", STATUS_OPTIONS, default=[])
    tier_filter   = st.multiselect("Outreach Tier", TIER_OPTIONS, default=[])
    stage_filter  = st.multiselect("Stage", STAGE_OPTIONS, default=[])
    fit_min       = st.slider("Min Fit Score", 0, 10, 5)
    hbs_only      = st.checkbox("HBS Alumni Only", value=False)
    founders_only = st.checkbox("2nd-Time Founders Only", value=False)

    st.divider()
    st.caption(f"Total: {len(df)} companies")

# ── Apply filters ─────────────────────────────────────────────────────────────

mask = pd.Series([True] * len(df))
if status_filter:
    mask &= df["status"].isin(status_filter)
if tier_filter:
    mask &= df["outreach_tier"].isin(tier_filter)
if stage_filter:
    mask &= df["stage_estimate"].isin(stage_filter)
if "fit_score" in df.columns:
    mask &= df["fit_score"].fillna(0) >= fit_min
if hbs_only and "hbs_alumni_at_company" in df.columns:
    mask &= df["hbs_alumni_at_company"] == True
if founders_only and "second_time_founder" in df.columns:
    mask &= df["second_time_founder"] == True

df_filtered = df[mask].copy()

st.markdown(f"**{len(df_filtered)}** companies match your filters")

# ── Add Company form ──────────────────────────────────────────────────────────

with st.expander("➕ Add Company Manually"):
    with st.form("add_company_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name        = c1.text_input("Company Name *")
        website     = c2.text_input("Website")
        hq_city     = c3.text_input("HQ City")

        c4, c5, c6 = st.columns(3)
        sector      = c4.multiselect("Sector", SECTOR_OPTIONS)
        stage       = c5.selectbox("Stage", STAGE_OPTIONS)
        fit_score   = c6.slider("Fit Score", 0, 10, 7)

        c7, c8 = st.columns(2)
        funding     = c7.number_input("Total Funding ($M)", min_value=0.0, step=1.0)
        tier        = c8.selectbox("Outreach Tier", TIER_OPTIONS)

        description = st.text_area("Description / Why Relevant", height=80)

        c9, c10 = st.columns(2)
        hbs_alumni  = c9.checkbox("HBS Alumni at Company")
        founder_2nd = c10.checkbox("2nd-Time Founder")

        submitted = st.form_submit_button("Add Company", type="primary")
        if submitted:
            if not name.strip():
                st.error("Company name is required.")
            else:
                db = get_db()
                record = {
                    "name":                  name.strip(),
                    "website":               website.strip() or None,
                    "hq_city":               hq_city.strip() or None,
                    "sector":                sector or None,
                    "stage_estimate":        stage,
                    "fit_score":             fit_score,
                    "total_funding_m":       funding or None,
                    "outreach_tier":         tier,
                    "description":           description.strip() or None,
                    "hbs_alumni_at_company": hbs_alumni,
                    "second_time_founder":   founder_2nd,
                    "status":                "Not Started",
                }
                try:
                    db.insert_company(record)
                    st.success(f"✅ Added **{name}**")
                    refresh()
                except Exception as e:
                    st.error(f"Error: {e}")

# ── Company table ─────────────────────────────────────────────────────────────

display_cols = ["name", "status", "outreach_tier", "stage_estimate",
                "fit_score", "hbs_alumni_at_company", "second_time_founder",
                "hq_city", "website"]
display_cols = [c for c in display_cols if c in df_filtered.columns]

df_display = df_filtered[display_cols].copy()
df_display = df_display.rename(columns={
    "name":                  "Company",
    "status":                "Status",
    "outreach_tier":         "Tier",
    "stage_estimate":        "Stage",
    "fit_score":             "Fit",
    "hbs_alumni_at_company": "HBS Alumni",
    "second_time_founder":   "2nd Founder",
    "hq_city":               "HQ",
    "website":               "Website",
})

df_display = df_display.sort_values(["Fit"], ascending=False).reset_index(drop=True)

edited = st.data_editor(
    df_display,
    use_container_width=True,
    height=500,
    column_config={
        "Status":      st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, width="medium"),
        "Tier":        st.column_config.SelectboxColumn("Tier",   options=TIER_OPTIONS,   width="medium"),
        "Fit":         st.column_config.NumberColumn("Fit", min_value=0, max_value=10, step=1, width="small"),
        "HBS Alumni":  st.column_config.CheckboxColumn("HBS Alumni", width="small"),
        "2nd Founder": st.column_config.CheckboxColumn("2nd Founder", width="small"),
        "Website":     st.column_config.LinkColumn("Website", width="medium"),
    },
    disabled=["Company", "Stage", "HQ", "Website"],
)

# ── Detect and save inline edits ──────────────────────────────────────────────

if not edited.equals(df_display):
    db  = get_db()
    df_orig = df_filtered[display_cols].rename(columns={
        "name": "Company", "status": "Status", "outreach_tier": "Tier",
        "stage_estimate": "Stage", "fit_score": "Fit",
        "hbs_alumni_at_company": "HBS Alumni", "second_time_founder": "2nd Founder",
        "hq_city": "HQ", "website": "Website",
    }).reset_index(drop=True)

    changed = (edited != df_orig).any(axis=1)
    rows_changed = edited[changed]
    orig_rows    = df_orig[changed]

    saved = 0
    for idx in rows_changed.index:
        company_name = edited.at[idx, "Company"]
        row = df_filtered[df_filtered["name"] == company_name]
        if row.empty:
            continue
        company_id = row.iloc[0]["id"]
        updates = {}
        if edited.at[idx, "Status"]      != df_orig.at[idx, "Status"]:
            updates["status"]                = edited.at[idx, "Status"]
        if edited.at[idx, "Tier"]        != df_orig.at[idx, "Tier"]:
            updates["outreach_tier"]         = edited.at[idx, "Tier"]
        if edited.at[idx, "Fit"]         != df_orig.at[idx, "Fit"]:
            updates["fit_score"]             = int(edited.at[idx, "Fit"])
        if edited.at[idx, "HBS Alumni"]  != df_orig.at[idx, "HBS Alumni"]:
            updates["hbs_alumni_at_company"] = bool(edited.at[idx, "HBS Alumni"])
        if edited.at[idx, "2nd Founder"] != df_orig.at[idx, "2nd Founder"]:
            updates["second_time_founder"]   = bool(edited.at[idx, "2nd Founder"])
        if updates:
            db.update_company(company_id, updates)
            saved += 1

    if saved:
        st.success(f"✅ Saved {saved} change(s)")
        refresh()
