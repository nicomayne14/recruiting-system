"""
pages/4_Applications.py — Application tracker
Track formal applications, interview stages, and follow-ups.
"""

import sys
from pathlib import Path
from datetime import date
import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from supabase_helper import SupabaseHelper

st.set_page_config(page_title="Applications · CRM", page_icon="📋", layout="wide")

STATUS_OPTIONS   = ["Applied", "Screening", "Interview", "Offer", "Rejected", "Withdrawn"]
PLATFORM_OPTIONS = ["LinkedIn", "Company Website", "Referral", "HBS Career Hub",
                    "Email Direct", "Other"]

STATUS_COLOR = {
    "Applied":    "#4361ee",
    "Screening":  "#f72585",
    "Interview":  "#7209b7",
    "Offer":      "#06d6a0",
    "Rejected":   "#6c757d",
    "Withdrawn":  "#adb5bd",
}

@st.cache_resource
def get_db():
    return SupabaseHelper()

@st.cache_data(ttl=30)
def load_applications():
    return get_db().get_all_applications()

@st.cache_data(ttl=30)
def load_companies():
    return get_db().get_all_companies()

def refresh():
    st.cache_data.clear()
    st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────

st.title("📋 Applications")
st.caption("Track every formal application from submission to offer.")
st.divider()

applications = load_applications()
companies    = load_companies()

# ── Stage summary ─────────────────────────────────────────────────────────────

if applications:
    df_all = pd.DataFrame(applications)
    cols = st.columns(len(STATUS_OPTIONS))
    for i, status in enumerate(STATUS_OPTIONS):
        count = len(df_all[df_all.get("status", pd.Series(dtype=str)) == status])
        cols[i].metric(status, count)
    st.divider()

# ── Add Application form ──────────────────────────────────────────────────────

with st.expander("➕ Log New Application"):
    with st.form("add_application_form", clear_on_submit=True):
        company_names = ["— select —"] + sorted([c["name"] for c in companies])
        c1, c2 = st.columns(2)
        company_sel  = c1.selectbox("Company *", company_names)
        role         = c2.text_input("Role / Position *")

        c3, c4, c5 = st.columns(3)
        platform     = c3.selectbox("Platform", PLATFORM_OPTIONS)
        applied_date = c4.date_input("Applied Date", value=date.today())
        followup_due = c5.date_input("Follow-up Due", value=None)

        notes        = st.text_area("Notes", height=70)
        submitted    = st.form_submit_button("Log Application", type="primary")

        if submitted:
            if company_sel == "— select —" or not role.strip():
                st.error("Company and role are required.")
            else:
                db = get_db()
                company = next((c for c in companies if c["name"] == company_sel), None)
                if not company:
                    st.error("Company not found.")
                else:
                    record = {
                        "company_id":   company["id"],
                        "role":         role.strip(),
                        "platform":     platform,
                        "applied_date": applied_date.isoformat(),
                        "followup_due": followup_due.isoformat() if followup_due else None,
                        "status":       "Applied",
                        "notes":        notes.strip() or None,
                    }
                    try:
                        db.insert_application(record)
                        # Also update company status
                        db.update_company(company["id"], {"status": "Applied"})
                        st.success(f"✅ Logged application to **{company_sel}** for **{role}**")
                        refresh()
                    except Exception as e:
                        st.error(f"Error: {e}")

# ── Applications table ────────────────────────────────────────────────────────

if not applications:
    st.info("No applications yet. Log your first one above.")
    st.stop()

rows = []
for a in applications:
    co = a.get("companies") or {}
    rows.append({
        "id":           a.get("id"),
        "Company":      co.get("name", "?") if isinstance(co, dict) else "?",
        "Role":         a.get("role", ""),
        "Status":       a.get("status", "Applied"),
        "Platform":     a.get("platform", ""),
        "Applied":      a.get("applied_date", "")[:10] if a.get("applied_date") else "",
        "Follow-up":    a.get("followup_due", "")[:10] if a.get("followup_due") else "",
        "Notes":        a.get("notes", ""),
    })

df = pd.DataFrame(rows)

# Filter by status
status_filter = st.multiselect("Filter by status", STATUS_OPTIONS,
                                default=[s for s in STATUS_OPTIONS if s not in ("Rejected", "Withdrawn")])
if status_filter:
    df = df[df["Status"].isin(status_filter)]

df_display = df.drop(columns=["id"]).reset_index(drop=True)

edited = st.data_editor(
    df_display,
    use_container_width=True,
    height=400,
    column_config={
        "Status":    st.column_config.SelectboxColumn("Status",   options=STATUS_OPTIONS,   width="medium"),
        "Platform":  st.column_config.SelectboxColumn("Platform", options=PLATFORM_OPTIONS, width="medium"),
        "Applied":   st.column_config.DateColumn("Applied",    width="small"),
        "Follow-up": st.column_config.DateColumn("Follow-up",  width="small"),
    },
    disabled=["Company", "Role"],
)

# Save inline edits
if not edited.equals(df_display):
    db = get_db()
    changed = (edited != df_display).any(axis=1)
    saved = 0
    for idx in edited[changed].index:
        app_id = df.iloc[idx]["id"]
        updates = {}
        if edited.at[idx, "Status"]    != df_display.at[idx, "Status"]:
            updates["status"]           = edited.at[idx, "Status"]
        if edited.at[idx, "Notes"]     != df_display.at[idx, "Notes"]:
            updates["notes"]            = edited.at[idx, "Notes"]
        if edited.at[idx, "Follow-up"] != df_display.at[idx, "Follow-up"]:
            fu = edited.at[idx, "Follow-up"]
            updates["followup_due"] = str(fu) if fu else None
        if updates:
            db.client.table("applications").update(updates).eq("id", app_id).execute()
            saved += 1
    if saved:
        st.success(f"✅ Saved {saved} change(s)")
        refresh()
