"""
setup_supabase.py — One-time Supabase schema setup

This script prints the SQL you need to run in the Supabase SQL editor,
then tests your connection using the credentials in .env.

Usage:
    python setup_supabase.py               # print SQL + test connection
    python setup_supabase.py --print-sql   # only print the SQL (no connection test)
"""

import os
import sys
import argparse
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

load_dotenv()
console = Console()

# ── SQL schema ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- ============================================================
-- Recruiting System — Supabase schema
-- Run this in: Supabase Dashboard → SQL Editor → New query
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── companies ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL UNIQUE,
    website                 TEXT,
    sector                  TEXT[],                          -- e.g. ['Mobility', 'CleanTech']
    hq_city                 TEXT,
    total_funding_m         NUMERIC,
    year_founded            INTEGER,
    stage_estimate          TEXT,                            -- 'Seed' | 'Series A' | 'Series B' | 'Series C+'
    description             TEXT,
    source                  TEXT,                            -- 'Bussgang USA' | 'Existing Research' | …
    fit_score               INTEGER,                         -- 1–10
    outreach_tier           TEXT,                            -- 'Tier 1' | 'Tier 2' | 'Tier 3'
    hbs_alumni_at_company   BOOLEAN NOT NULL DEFAULT FALSE,
    second_time_founder     BOOLEAN NOT NULL DEFAULT FALSE,
    vc_connection           BOOLEAN NOT NULL DEFAULT FALSE,
    gift_prepared           BOOLEAN NOT NULL DEFAULT FALSE,
    status                  TEXT NOT NULL DEFAULT 'Not Started',
    next_action             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── contacts ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    role_title      TEXT,
    company_id      UUID REFERENCES companies(id) ON DELETE SET NULL,
    linkedin_url    TEXT,
    email           TEXT,
    hbs_alumni      BOOLEAN NOT NULL DEFAULT FALSE,
    hbs_grad_year   INTEGER,
    outreach_tier   TEXT,                                    -- 'Tier 1 (HBS/Warm)' | 'Tier 2 (Founder Direct)' | 'Tier 3 (Cold)'
    status          TEXT NOT NULL DEFAULT 'Not Contacted',   -- 'Not Contacted' | 'Messaged' | 'Replied' | 'Coffee Chat Scheduled' | 'Coffee Chat Done'
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, company_id)
);

-- ── interactions ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS interactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type            TEXT NOT NULL,                           -- 'LinkedIn DM' | 'HBS Email' | 'Direct Email' | 'Coffee Chat' | 'Follow-up'
    company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,
    date            DATE,
    message_sent    TEXT,
    response        TEXT,
    gift_prepared   BOOLEAN NOT NULL DEFAULT FALSE,
    followup_due    DATE,
    followup_sent   BOOLEAN NOT NULL DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── applications ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS applications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    platform        TEXT,                                    -- 'LinkedIn' | 'Company Website' | 'Referral' | …
    applied_date    DATE,
    status          TEXT NOT NULL DEFAULT 'Applied',         -- 'Applied' | 'Screening' | 'Interview' | 'Offer' | 'Rejected' | 'Withdrawn'
    followup_due    DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── indexes ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_companies_status        ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_outreach_tier ON companies(outreach_tier);
CREATE INDEX IF NOT EXISTS idx_contacts_company_id     ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_status         ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_interactions_company_id ON interactions(company_id);
CREATE INDEX IF NOT EXISTS idx_interactions_followup   ON interactions(followup_due) WHERE followup_sent = FALSE;
CREATE INDEX IF NOT EXISTS idx_applications_company_id ON applications(company_id);
CREATE INDEX IF NOT EXISTS idx_applications_status     ON applications(status);

-- ── updated_at triggers ──────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_companies_updated_at  ON companies;
DROP TRIGGER IF EXISTS trg_contacts_updated_at   ON contacts;
DROP TRIGGER IF EXISTS trg_applications_updated_at ON applications;

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_contacts_updated_at
    BEFORE UPDATE ON contacts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_applications_updated_at
    BEFORE UPDATE ON applications
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Print Supabase schema SQL + test connection")
    parser.add_argument("--print-sql", action="store_true", help="Only print SQL, skip connection test")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold blue]Supabase Setup[/bold blue]\n"
        "Prints schema SQL + tests your connection",
        border_style="blue",
    ))

    # ── Print SQL ─────────────────────────────────────────────────────────────
    console.print("\n[bold]Step 1 — Copy this SQL into Supabase → SQL Editor → New query → Run[/bold]\n")
    console.print(Syntax(SCHEMA_SQL.strip(), "sql", theme="monokai", line_numbers=False))

    if args.print_sql:
        return

    # ── Test connection ───────────────────────────────────────────────────────
    console.print("\n[bold]Step 2 — Testing connection with your .env credentials…[/bold]")

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        console.print(
            "[red]SUPABASE_URL or SUPABASE_SERVICE_KEY not set in .env[/red]\n"
            "[dim]Get them from: Supabase Dashboard → Project Settings → API[/dim]"
        )
        sys.exit(1)

    try:
        from supabase import create_client
        sb = create_client(url, key)

        # Try a lightweight query on each table
        tables = ["companies", "contacts", "interactions", "applications"]
        for t in tables:
            try:
                res = sb.table(t).select("id").limit(1).execute()
                console.print(f"  [green]✓[/green] {t} — accessible")
            except Exception as e:
                console.print(f"  [red]✗[/red] {t} — {e}")
                console.print(
                    f"  [dim]Run the SQL above first if the table doesn't exist yet.[/dim]"
                )

        console.print("\n[green]Connection test complete.[/green]")
        console.print(
            "\n[bold]Next steps:[/bold]\n"
            "  1. python agents/filter_companies.py          — import companies\n"
            "  2. python agents/research_contacts.py --company \"Revel\"  — find HBS alumni\n"
            "  3. streamlit run app.py                       — launch dashboard"
        )

    except ImportError:
        console.print("[red]supabase package not installed. Run: pip install supabase[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Connection failed: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
