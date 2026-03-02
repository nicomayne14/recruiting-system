"""
agents/batch_research_contacts.py — Batch runner for Agent 2
Opens ONE browser session, logs in to HBS once, then iterates through
your top-N unresearched companies and scrapes alumni contacts for each.

Usage:
    python agents/batch_research_contacts.py                  # top 20, headless
    python agents/batch_research_contacts.py --limit 10       # top 10
    python agents/batch_research_contacts.py --dry-run        # no DB writes
    python agents/batch_research_contacts.py --headless false  # watch browser
    python agents/batch_research_contacts.py --min-fit 8      # only fit ≥ 8
    python agents/batch_research_contacts.py --tier 1         # Tier 1 only
"""

import os
import sys
import time
import argparse
import random
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, MofNCompleteColumn

sys.path.insert(0, str(Path(__file__).parent.parent))
from supabase_helper import SupabaseHelper
from agents.research_contacts import (
    hbs_login,
    make_context,
    search_alumni_by_company,
    check_second_time_founder,
    push_contact_to_supabase,
    update_company_flags,
    HBS_ALUMNI_URL,
    SESSION_FILE,
    REQUEST_DELAY,
)

load_dotenv()
console = Console()

INTER_COMPANY_DELAY = (8, 15)   # seconds between companies — be respectful


def get_unresearched_companies(
    db: SupabaseHelper,
    limit: int,
    min_fit: int,
) -> list[dict]:
    """
    Return companies ordered by fit_score that have never been
    researched for HBS alumni (outreach_tier is NULL).
    """
    res = (
        db.client.table("companies")
        .select("id, name, fit_score, stage_estimate, sector, hq_city")
        .gte("fit_score", min_fit)
        .is_("outreach_tier", "null")          # not yet researched
        .order("fit_score", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def research_one_company(
    page,
    db: SupabaseHelper,
    company: dict,
    dry_run: bool,
) -> dict:
    """
    Run the full HBS scrape + Supabase push for a single company.
    Returns a result summary dict.
    """
    name       = company["name"]
    company_id = company["id"]
    result     = {"name": name, "found": 0, "created": 0, "founders": 0,
                  "second_founders": 0, "error": None}

    try:
        contacts = search_alumni_by_company(page, name)
        result["found"] = len(contacts)

        # 2nd-time founder check for any founders found
        founders = [c for c in contacts if c.is_founder]
        result["founders"] = len(founders)
        if founders:
            for i, contact in enumerate(contacts):
                if contact.is_founder:
                    contacts[i] = check_second_time_founder(page, contact)
                    time.sleep(random.uniform(*REQUEST_DELAY))

        result["second_founders"] = sum(1 for c in contacts if c.second_time_founder)

        # Push to Supabase
        created = 0
        for contact in contacts:
            ok = push_contact_to_supabase(db, contact, company_id, dry_run=dry_run)
            if ok:
                created += 1
        result["created"] = created

        # Update company-level flags
        update_company_flags(db, company_id, contacts, dry_run=dry_run)

    except Exception as e:
        result["error"] = str(e)
        console.print(f"  [red]✗ Error on {name}: {e}[/red]")
        # Still mark as searched so we don't retry forever on broken pages
        if not dry_run:
            try:
                db.update_company(company_id, {"outreach_tier": "Tier 3 (Cold)"})
            except Exception:
                pass

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Batch-scrape HBS alumni for your top unresearched companies."
    )
    parser.add_argument("--limit",    type=int,   default=20,    help="Number of companies to process (default: 20)")
    parser.add_argument("--min-fit",  type=int,   default=5,     help="Minimum fit score to include (default: 5)")
    parser.add_argument("--headless", default="true",            help="Run browser headless: true/false (default: true)")
    parser.add_argument("--dry-run",  action="store_true",       help="Preview — no DB writes")
    args = parser.parse_args()

    headless = args.headless.lower() != "false"
    start_time = datetime.now()

    console.print(Panel.fit(
        f"[bold blue]Batch Contact Research[/bold blue]\n"
        f"Limit: [cyan]{args.limit}[/cyan]  |  "
        f"Min fit: [cyan]{args.min_fit}[/cyan]  |  "
        f"Headless: {headless}  |  "
        f"Dry run: {args.dry_run}",
        border_style="blue",
    ))
    if args.dry_run:
        console.print("[yellow]DRY RUN — no data will be written to Supabase[/yellow]\n")

    # ── 1. Fetch unresearched companies ───────────────────────────────────────
    db = SupabaseHelper()
    console.print("\n[bold]Step 1 — Loading target companies from Supabase[/bold]")
    companies = get_unresearched_companies(db, args.limit, args.min_fit)

    if not companies:
        console.print(
            "[yellow]No unresearched companies found.\n"
            "Either all companies have been researched, or none meet your --min-fit threshold.[/yellow]"
        )
        return

    console.print(f"  Found [cyan]{len(companies)}[/cyan] companies to research:\n")
    preview = Table(show_lines=False, box=None, padding=(0, 2))
    preview.add_column("#",        style="dim",  justify="right", width=3)
    preview.add_column("Company",  style="bold", width=35)
    preview.add_column("Stage",    width=12)
    preview.add_column("Fit",      justify="right", width=4)
    for i, c in enumerate(companies, 1):
        preview.add_row(
            str(i),
            c["name"][:34],
            c.get("stage_estimate") or "?",
            str(c.get("fit_score") or 0),
        )
    console.print(preview)

    # ── 2. Open browser, load session ─────────────────────────────────────────
    console.print(f"\n[bold]Step 2 — Opening browser & connecting to HBS[/bold]")

    if SESSION_FILE.exists():
        console.print(f"  [green]✓ Found saved session — skipping MFA[/green]")
    else:
        console.print(
            f"  [yellow]⚠ No saved session found.[/yellow]\n"
            f"  [dim]Run  python save_hbs_session.py  first to save your HBS session.\n"
            f"  This lets the batch runner skip MFA on every run.[/dim]"
        )
        return

    results = []
    with sync_playwright() as pw:
        browser, ctx, session_loaded = make_context(pw, headless)
        page = ctx.new_page()

        # Confirm the session is still valid
        page.goto(HBS_ALUMNI_URL, wait_until="domcontentloaded", timeout=30000)
        if "signin" in page.url.lower() or "login" in page.url.lower() or "microsoftonline" in page.url.lower():
            console.print(
                "[red]Saved session has expired.[/red]\n"
                "[dim]Run  python save_hbs_session.py  to refresh it, then try again.[/dim]"
            )
            browser.close()
            return
        console.print("  [green]✓ Session valid — ready to scrape[/green]")

        # ── 3. Scrape each company ─────────────────────────────────────────────
        console.print(f"\n[bold]Step 3 — Scraping {len(companies)} companies[/bold]\n")

        for i, company in enumerate(companies, 1):
            name = company["name"]
            console.print(
                f"[bold][{i}/{len(companies)}][/bold] "
                f"[cyan]{name}[/cyan]  "
                f"[dim](fit: {company.get('fit_score', '?')}, "
                f"{company.get('stage_estimate', '?')})[/dim]"
            )

            result = research_one_company(page, db, company, dry_run=args.dry_run)
            results.append(result)

            status_parts = [f"found [cyan]{result['found']}[/cyan] alumni"]
            if result["created"]:
                status_parts.append(f"[green]+{result['created']} new[/green]")
            if result["second_founders"]:
                status_parts.append(f"[yellow]★ {result['second_founders']} 2nd-founder[/yellow]")
            if result["error"]:
                status_parts.append(f"[red]error[/red]")
            console.print(f"  → {' | '.join(status_parts)}")

            # Polite delay between companies (skip after last one)
            if i < len(companies):
                delay = random.uniform(*INTER_COMPANY_DELAY)
                console.print(f"  [dim]Waiting {delay:.0f}s before next company…[/dim]")
                time.sleep(delay)

        browser.close()

    # ── 4. Summary ────────────────────────────────────────────────────────────
    elapsed = (datetime.now() - start_time).seconds
    total_found   = sum(r["found"]          for r in results)
    total_created = sum(r["created"]        for r in results)
    total_2nd     = sum(r["second_founders"] for r in results)
    total_errors  = sum(1 for r in results if r["error"])
    companies_with_alumni = sum(1 for r in results if r["found"] > 0)

    console.print("\n")
    summary_table = Table(title="Results by Company", show_lines=True)
    summary_table.add_column("Company",      style="bold", width=35)
    summary_table.add_column("Alumni",       justify="center", width=8)
    summary_table.add_column("New contacts", justify="center", width=12)
    summary_table.add_column("2nd founder",  justify="center", width=12)
    summary_table.add_column("Status",       width=10)

    for r in results:
        summary_table.add_row(
            r["name"][:34],
            str(r["found"]) if not r["error"] else "—",
            str(r["created"]) if not r["error"] else "—",
            "★" if r["second_founders"] else "",
            "[red]error[/red]" if r["error"] else "[green]✓[/green]",
        )
    console.print(summary_table)

    console.print(Panel.fit(
        f"[green]Companies researched:[/green]  {len(results)}\n"
        f"[green]Companies with alumni:[/green] {companies_with_alumni}\n"
        f"[green]Total alumni found:[/green]    {total_found}\n"
        f"[green]New contacts added:[/green]    {total_created}\n"
        f"[yellow]2nd-time founders:[/yellow]   {total_2nd}\n"
        f"[red]Errors:[/red]               {total_errors}\n"
        f"[dim]Time elapsed:          {elapsed}s[/dim]",
        title="[bold]Batch Summary[/bold]",
        border_style="green" if total_created > 0 else "yellow",
    ))

    if total_2nd > 0:
        console.print(
            "\n[yellow]★ 2nd-time founders found — these are Tier 1 priority contacts.[/yellow]"
        )
    if args.dry_run:
        console.print("\n[dim]DRY RUN — nothing was written. Re-run without --dry-run to commit.[/dim]")


if __name__ == "__main__":
    main()
