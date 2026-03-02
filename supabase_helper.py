"""
supabase_helper.py — Shared Supabase client wrapper
Used by all agents. Handles CRUD operations on the 4 database tables.

Tables: companies, contacts, interactions, applications

Requires:
    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_SERVICE_KEY=eyJ...  (service_role key — has full DB access)
"""

import os
from typing import Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from rich.console import Console

load_dotenv()
console = Console()


class SupabaseHelper:
    def __init__(self):
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        if not url or not key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env\n"
                "Get them from: Supabase Dashboard → Project Settings → API"
            )
        self.client: Client = create_client(url, key)

    # ── Companies ─────────────────────────────────────────────────────────────

    def get_all_companies(self) -> list[dict]:
        """Return all company rows."""
        res = self.client.table("companies").select("*").execute()
        return res.data or []

    def get_company_by_name(self, name: str) -> Optional[dict]:
        """
        Look up a company by exact name (case-insensitive).
        Returns the first match or None.
        """
        res = (
            self.client.table("companies")
            .select("*")
            .ilike("name", name)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def company_exists(self, name: str) -> bool:
        """Return True if a company with this name already exists (case-insensitive)."""
        return self.get_company_by_name(name) is not None

    def insert_company(self, row: dict) -> dict:
        """
        Insert a company row. Returns the inserted row (with generated id).
        `row` should use the column names from the companies table.
        """
        res = self.client.table("companies").insert(row).execute()
        return res.data[0] if res.data else {}

    def upsert_company(self, row: dict) -> dict:
        """Insert or update a company (matches on `name`)."""
        res = (
            self.client.table("companies")
            .upsert(row, on_conflict="name")
            .execute()
        )
        return res.data[0] if res.data else {}

    def update_company(self, company_id: str, updates: dict) -> dict:
        """Update specific fields on a company row by UUID."""
        res = (
            self.client.table("companies")
            .update(updates)
            .eq("id", company_id)
            .execute()
        )
        return res.data[0] if res.data else {}

    def get_companies_by_status(self, status: str) -> list[dict]:
        """Return companies filtered by status."""
        res = (
            self.client.table("companies")
            .select("*")
            .eq("status", status)
            .execute()
        )
        return res.data or []

    def get_all_company_names(self) -> dict[str, str]:
        """Return {lowercase_name: company_id} for deduplication checks."""
        rows = self.get_all_companies()
        return {row["name"].lower(): row["id"] for row in rows if row.get("name")}

    # ── Contacts ──────────────────────────────────────────────────────────────

    def get_contacts_for_company(self, company_id: str) -> list[dict]:
        """Return all contacts linked to a company."""
        res = (
            self.client.table("contacts")
            .select("*")
            .eq("company_id", company_id)
            .execute()
        )
        return res.data or []

    def contact_exists(self, name: str, company_id: str) -> bool:
        """Return True if this contact already exists for this company."""
        res = (
            self.client.table("contacts")
            .select("id")
            .ilike("name", name)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        return len(res.data or []) > 0

    def insert_contact(self, row: dict) -> dict:
        """
        Insert a contact row. Returns the inserted row.
        Required fields: name, company_id
        """
        res = self.client.table("contacts").insert(row).execute()
        return res.data[0] if res.data else {}

    def update_contact(self, contact_id: str, updates: dict) -> dict:
        """Update specific fields on a contact."""
        res = (
            self.client.table("contacts")
            .update(updates)
            .eq("id", contact_id)
            .execute()
        )
        return res.data[0] if res.data else {}

    def get_contacts_by_status(self, status: str) -> list[dict]:
        """Return all contacts with the given outreach status."""
        res = (
            self.client.table("contacts")
            .select("*, companies(name)")
            .eq("status", status)
            .execute()
        )
        return res.data or []

    # ── Interactions ──────────────────────────────────────────────────────────

    def insert_interaction(self, row: dict) -> dict:
        """
        Insert an interaction row. Returns the inserted row.
        Required fields: type, company_id
        """
        res = self.client.table("interactions").insert(row).execute()
        return res.data[0] if res.data else {}

    def get_interactions_for_company(self, company_id: str) -> list[dict]:
        """Return all interactions for a company."""
        res = (
            self.client.table("interactions")
            .select("*")
            .eq("company_id", company_id)
            .order("date", desc=True)
            .execute()
        )
        return res.data or []

    def get_pending_followups(self) -> list[dict]:
        """Return interactions where a follow-up is due."""
        from datetime import date
        today = date.today().isoformat()
        res = (
            self.client.table("interactions")
            .select("*, companies(name), contacts(name)")
            .lte("followup_due", today)
            .is_("followup_sent", False)
            .execute()
        )
        return res.data or []

    # ── Applications ──────────────────────────────────────────────────────────

    def insert_application(self, row: dict) -> dict:
        """
        Insert an application row. Returns the inserted row.
        Required fields: company_id, role
        """
        res = self.client.table("applications").insert(row).execute()
        return res.data[0] if res.data else {}

    def get_all_applications(self) -> list[dict]:
        """Return all applications with company name joined."""
        res = (
            self.client.table("applications")
            .select("*, companies(name)")
            .order("applied_date", desc=True)
            .execute()
        )
        return res.data or []

    def application_exists(self, company_id: str, role: str) -> bool:
        """Return True if this company+role application already exists."""
        res = (
            self.client.table("applications")
            .select("id")
            .eq("company_id", company_id)
            .ilike("role", role)
            .limit(1)
            .execute()
        )
        return len(res.data or []) > 0

    # ── KPI helpers ───────────────────────────────────────────────────────────

    def get_pipeline_stats(self) -> dict:
        """
        Return a dict of KPI counts for the dashboard.
        """
        companies = self.get_all_companies()
        contacts  = (self.client.table("contacts").select("id, status").execute().data or [])
        interactions = (self.client.table("interactions").select("id, type").execute().data or [])
        applications = (self.client.table("applications").select("id, status").execute().data or [])

        return {
            "total_companies":    len(companies),
            "tier1_companies":    sum(1 for c in companies if c.get("outreach_tier") == "Tier 1"),
            "tier2_companies":    sum(1 for c in companies if c.get("outreach_tier") == "Tier 2"),
            "tier3_companies":    sum(1 for c in companies if c.get("outreach_tier") == "Tier 3"),
            "total_contacts":     len(contacts),
            "contacted":          sum(1 for c in contacts if c.get("status") != "Not Contacted"),
            "total_interactions": len(interactions),
            "total_applications": len(applications),
            "active_applications": sum(
                1 for a in applications
                if a.get("status") not in ("Rejected", "Withdrawn", "Offer Declined")
            ),
        }
