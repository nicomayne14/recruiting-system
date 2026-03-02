"""
pages/3_Log_Outreach.py — Daily outreach logger
The page you use every time you send a message or have a coffee chat.
"""

import sys
from pathlib import Path
from datetime import date, timedelta
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from supabase_helper import SupabaseHelper

st.set_page_config(page_title="Log Outreach · CRM", page_icon="✉️", layout="wide")

INTERACTION_TYPES = [
    "LinkedIn DM", "HBS Email", "Direct Email",
    "Coffee Chat", "Follow-up", "Referral Introduction", "Other"
]

CONTACT_STATUS_MAP = {
    "LinkedIn DM":            "Messaged",
    "HBS Email":              "Messaged",
    "Direct Email":           "Messaged",
    "Coffee Chat":            "Coffee Chat Done",
    "Follow-up":              "Messaged",
    "Referral Introduction":  "Messaged",
    "Other":                  "Messaged",
}

@st.cache_resource
def get_db():
    return SupabaseHelper()

@st.cache_data(ttl=30)
def load_companies():
    db = get_db()
    res = db.client.table("companies").select("id, name, outreach_tier, status").order("fit_score", desc=True).execute()
    return res.data or []

@st.cache_data(ttl=30)
def load_contacts_for_company(company_id: str):
    db = get_db()
    res = db.client.table("contacts").select("id, name, role_title, outreach_tier").eq("company_id", company_id).execute()
    return res.data or []

@st.cache_data(ttl=30)
def load_recent_interactions():
    db = get_db()
    res = (
        db.client.table("interactions")
        .select("*, companies(name), contacts(name)")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return res.data or []

def refresh():
    st.cache_data.clear()
    st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────

st.title("✉️ Log Outreach")
st.caption("Record every message, coffee chat, and follow-up. This is your daily log.")
st.divider()

left, right = st.columns([5, 4])

# ── Log Outreach Form ─────────────────────────────────────────────────────────

with left:
    st.subheader("New Interaction")
    companies = load_companies()

    with st.form("log_outreach_form", clear_on_submit=True):
        # Company selector
        company_names = [f"{c['name']}  [{c.get('outreach_tier','?')}]" for c in companies]
        company_sel   = st.selectbox("Company *", ["— select —"] + company_names)

        # Contact selector (populated dynamically — shows after company pick)
        selected_company = None
        contact_options  = ["No specific contact / general outreach"]
        if company_sel and company_sel != "— select —":
            co_name = company_sel.split("  [")[0]
            selected_company = next((c for c in companies if c["name"] == co_name), None)
            if selected_company:
                contacts = load_contacts_for_company(selected_company["id"])
                contact_options += [
                    f"{c['name']}  ({c.get('role_title','')})  [{c.get('outreach_tier','')}]"
                    for c in contacts
                ]

        contact_sel    = st.selectbox("Contact", contact_options)
        outreach_type  = st.selectbox("Type *", INTERACTION_TYPES)

        col1, col2 = st.columns(2)
        outreach_date  = col1.date_input("Date", value=date.today())
        default_followup = date.today() + timedelta(days=7)
        followup_date  = col2.date_input("Follow-up Due", value=default_followup)

        message        = st.text_area("Message Sent", height=160,
                                      placeholder="Paste the message you sent…")
        response       = st.text_area("Response (if any)", height=80,
                                      placeholder="Paste their reply, or leave blank if no response yet…")
        gift_prepared  = st.checkbox("🎁 Gift prepared (LATAM insight / article / data shared)")
        notes          = st.text_input("Notes")

        submitted = st.form_submit_button("💾 Log Interaction", type="primary", use_container_width=True)

        if submitted:
            if not selected_company:
                st.error("Please select a company.")
            else:
                db = get_db()

                # Resolve contact ID
                contact_id = None
                if contact_sel != "No specific contact / general outreach":
                    contact_name = contact_sel.split("  (")[0]
                    contact_rows = load_contacts_for_company(selected_company["id"])
                    match = next((c for c in contact_rows if c["name"] == contact_name), None)
                    if match:
                        contact_id = match["id"]

                interaction = {
                    "type":          outreach_type,
                    "company_id":    selected_company["id"],
                    "contact_id":    contact_id,
                    "date":          outreach_date.isoformat(),
                    "message_sent":  message.strip() or None,
                    "response":      response.strip() or None,
                    "gift_prepared": gift_prepared,
                    "followup_due":  followup_date.isoformat(),
                    "followup_sent": False,
                    "notes":         notes.strip() or None,
                }

                try:
                    db.insert_interaction(interaction)

                    # Update company status
                    new_co_status = "Coffee Chat Done" if outreach_type == "Coffee Chat" else "Contacted"
                    db.update_company(selected_company["id"], {"status": new_co_status})

                    # Update contact status
                    if contact_id:
                        new_contact_status = CONTACT_STATUS_MAP.get(outreach_type, "Messaged")
                        db.update_contact(contact_id, {"status": new_contact_status})

                    st.success(f"✅ Logged **{outreach_type}** with **{selected_company['name']}**")
                    refresh()
                except Exception as e:
                    st.error(f"Error saving: {e}")

# ── Recent interactions ───────────────────────────────────────────────────────

with right:
    st.subheader("Recent Activity")

    interactions = load_recent_interactions()
    if not interactions:
        st.caption("No interactions logged yet.")
    else:
        for row in interactions:
            co = row.get("companies") or {}
            cn = row.get("contacts")  or {}
            co_name  = co.get("name", "?") if isinstance(co, dict) else "?"
            cn_name  = cn.get("name", "")  if isinstance(cn, dict) else ""
            itype    = row.get("type", "?")
            idate    = row.get("date", "")[:10] if row.get("date") else ""
            response = row.get("response")
            gift     = "🎁 " if row.get("gift_prepared") else ""
            followup = row.get("followup_due", "")[:10] if row.get("followup_due") else ""

            status_icon = "↩️ " if response else ""

            with st.container():
                st.markdown(
                    f"**{gift}{status_icon}{itype}** · {co_name}"
                    + (f" / {cn_name}" if cn_name else "")
                    + f"  <span style='color:#6c757d;font-size:0.82rem'>{idate}"
                    + (f" · follow-up {followup}" if followup else "")
                    + "</span>",
                    unsafe_allow_html=True,
                )
                if response:
                    st.caption(f"💬 {response[:120]}{'…' if len(response) > 120 else ''}")
            st.divider()
