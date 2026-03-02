"""
pages/2_Contacts.py — Contact directory
View, add, and update contacts across all companies.
"""

import sys
from pathlib import Path
import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from supabase_helper import SupabaseHelper

st.set_page_config(page_title="Contacts · CRM", page_icon="👥", layout="wide")

STATUS_OPTIONS = ["Not Contacted", "Messaged", "Replied",
                  "Coffee Chat Scheduled", "Coffee Chat Done"]
TIER_OPTIONS   = ["Tier 1 (HBS/Warm)", "Tier 2 (Founder Direct)", "Tier 3 (Cold)"]

@st.cache_resource
def get_db():
    return SupabaseHelper()

@st.cache_data(ttl=30)
def load_contacts():
    db = get_db()
    res = db.client.table("contacts").select("*, companies(name)").order("created_at", desc=True).execute()
    return res.data or []

@st.cache_data(ttl=30)
def load_companies():
    return get_db().get_all_companies()

def refresh():
    st.cache_data.clear()
    st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────

st.title("👥 Contacts")
st.caption("All HBS alumni and direct contacts across your target companies.")
st.divider()

contacts  = load_contacts()
companies = load_companies()

# ── Sidebar filters ────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("🔍 Filters")
    status_filter = st.multiselect("Status", STATUS_OPTIONS)
    tier_filter   = st.multiselect("Tier",   TIER_OPTIONS)
    hbs_only      = st.checkbox("HBS Alumni Only")
    search_name   = st.text_input("Search name")

# ── Add Contact form ──────────────────────────────────────────────────────────

with st.expander("➕ Add Contact Manually"):
    with st.form("add_contact_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name          = c1.text_input("Full Name *")
        role_title    = c2.text_input("Role / Title")

        company_names = ["(none)"] + sorted([c["name"] for c in companies])
        c3, c4 = st.columns(2)
        company_sel   = c3.selectbox("Company", company_names)
        linkedin_url  = c4.text_input("LinkedIn / HBS Profile URL")

        c5, c6, c7 = st.columns(3)
        hbs_alumni    = c5.checkbox("HBS Alumni")
        grad_year     = c6.number_input("HBS Grad Year", min_value=1950, max_value=2030, value=2020, step=1)
        tier          = c7.selectbox("Outreach Tier", TIER_OPTIONS)

        email         = st.text_input("Email (optional)")
        notes         = st.text_area("Notes", height=70)

        submitted = st.form_submit_button("Add Contact", type="primary")
        if submitted:
            if not name.strip():
                st.error("Name is required.")
            else:
                db = get_db()
                company_id = None
                if company_sel != "(none)":
                    row = next((c for c in companies if c["name"] == company_sel), None)
                    if row:
                        company_id = row["id"]
                record = {
                    "name":          name.strip(),
                    "role_title":    role_title.strip() or None,
                    "company_id":    company_id,
                    "linkedin_url":  linkedin_url.strip() or None,
                    "hbs_alumni":    hbs_alumni,
                    "hbs_grad_year": int(grad_year) if hbs_alumni else None,
                    "outreach_tier": tier,
                    "email":         email.strip() or None,
                    "notes":         notes.strip() or None,
                    "status":        "Not Contacted",
                }
                try:
                    db.insert_contact(record)
                    st.success(f"✅ Added **{name}**")
                    refresh()
                except Exception as e:
                    st.error(f"Error: {e}")

# ── Build display dataframe ───────────────────────────────────────────────────

if not contacts:
    st.info("No contacts yet. Run the batch scraper or add contacts manually.")
    st.stop()

rows = []
for c in contacts:
    co = c.get("companies") or {}
    rows.append({
        "id":           c.get("id"),
        "Name":         c.get("name", ""),
        "Company":      co.get("name", "—") if isinstance(co, dict) else "—",
        "Role":         c.get("role_title", ""),
        "Tier":         c.get("outreach_tier", ""),
        "Status":       c.get("status", "Not Contacted"),
        "HBS Alumni":   c.get("hbs_alumni", False),
        "HBS Year":     c.get("hbs_grad_year"),
        "LinkedIn":     c.get("linkedin_url", ""),
        "Notes":        c.get("notes", ""),
    })
df = pd.DataFrame(rows)

# Apply filters
mask = pd.Series([True] * len(df))
if status_filter:
    mask &= df["Status"].isin(status_filter)
if tier_filter:
    mask &= df["Tier"].isin(tier_filter)
if hbs_only:
    mask &= df["HBS Alumni"] == True
if search_name:
    mask &= df["Name"].str.contains(search_name, case=False, na=False)

df_filtered = df[mask].copy()
st.markdown(f"**{len(df_filtered)}** contacts match your filters")

# ── Contacts table ────────────────────────────────────────────────────────────

display_cols = ["Name", "Company", "Role", "Tier", "Status", "HBS Alumni", "HBS Year", "LinkedIn"]
df_display = df_filtered[display_cols].reset_index(drop=True)

edited = st.data_editor(
    df_display,
    use_container_width=True,
    height=500,
    column_config={
        "Status":     st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, width="medium"),
        "Tier":       st.column_config.SelectboxColumn("Tier",   options=TIER_OPTIONS,   width="medium"),
        "HBS Alumni": st.column_config.CheckboxColumn("HBS Alumni", width="small"),
        "LinkedIn":   st.column_config.LinkColumn("LinkedIn", width="medium"),
    },
    disabled=["Name", "Company", "Role", "HBS Year"],
)

# Save inline edits
if not edited.equals(df_display):
    db = get_db()
    changed = (edited != df_display).any(axis=1)
    saved = 0
    for idx in edited[changed].index:
        contact_name = edited.at[idx, "Name"]
        original = df_filtered[df_filtered["Name"] == contact_name]
        if original.empty:
            continue
        contact_id = original.iloc[0]["id"]
        updates = {}
        if edited.at[idx, "Status"]     != df_display.at[idx, "Status"]:
            updates["status"]            = edited.at[idx, "Status"]
        if edited.at[idx, "Tier"]       != df_display.at[idx, "Tier"]:
            updates["outreach_tier"]     = edited.at[idx, "Tier"]
        if edited.at[idx, "HBS Alumni"] != df_display.at[idx, "HBS Alumni"]:
            updates["hbs_alumni"]        = bool(edited.at[idx, "HBS Alumni"])
        if updates:
            db.update_contact(contact_id, updates)
            saved += 1
    if saved:
        st.success(f"✅ Saved {saved} change(s)")
        refresh()
