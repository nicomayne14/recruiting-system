"""
agents/research_contacts.py — Agent 2
For a given company, scrapes the HBS Alumni Directory for alumni currently
working there, detects 2nd-time founders, and pushes contacts to Supabase.

Usage:
    python agents/research_contacts.py --company "Revel"
    python agents/research_contacts.py --company "Revel" --headless false
    python agents/research_contacts.py --company "Revel" --dry-run
"""

import os
import sys
import re
import time
import random
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

sys.path.insert(0, str(Path(__file__).parent.parent))
from supabase_helper import SupabaseHelper

load_dotenv()
console = Console()

# ── Constants ─────────────────────────────────────────────────────────────────

HBS_ALUMNI_URL   = "https://www.alumni.hbs.edu/community/Pages/alumni-directory.aspx"
HBS_LOGIN_URL    = "https://www.alumni.hbs.edu"
SESSION_FILE     = Path(__file__).parent.parent / "hbs_session.json"
REQUEST_DELAY    = (1.5, 3.5)
MAX_RESULTS      = 50
FOUNDER_KEYWORDS = {"founder", "co-founder", "cofounder", "ceo", "chief executive"}
STARTUP_SKIP     = {
    "mckinsey", "bain", "bcg", "goldman sachs", "jpmorgan", "morgan stanley",
    "google", "meta", "apple", "amazon", "microsoft", "harvard", "mit",
    "stanford", "consulting", "capital", "management", "university",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class AlumContact:
    name: str
    title: str
    company: str
    grad_year: Optional[int]
    profile_url: str
    is_founder: bool = False
    second_time_founder: bool = False
    prior_companies: list[str] = field(default_factory=list)
    notes: str = ""


# ── Session helpers ───────────────────────────────────────────────────────────

def make_context(pw, headless: bool):
    """
    Create a browser context. If hbs_session.json exists, load saved cookies
    (skips login + MFA). Otherwise return a fresh context and require login.
    Returns (browser, context, session_loaded: bool).
    """
    browser = pw.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    if SESSION_FILE.exists():
        ctx = browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 800},
            storage_state=str(SESSION_FILE),
        )
        return browser, ctx, True
    else:
        ctx = browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 800},
        )
        return browser, ctx, False


# ── Browser helpers ───────────────────────────────────────────────────────────

def _pause(lo: float = REQUEST_DELAY[0], hi: float = REQUEST_DELAY[1]):
    time.sleep(random.uniform(lo, hi))


def _safe_text(page: Page, selector: str, default: str = "") -> str:
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=3000)
        return el.inner_text().strip()
    except Exception:
        return default


# ── HBS Login ─────────────────────────────────────────────────────────────────

def hbs_login(page: Page) -> bool:
    """
    Log into the HBS alumni portal.
    Returns True on success, False on failure.
    """
    email    = os.getenv("HBS_EMAIL", "")
    password = os.getenv("HBS_PASSWORD", "")

    if not email or not password:
        console.print("[red]HBS_EMAIL or HBS_PASSWORD not set in .env[/red]")
        return False

    console.print("  → Navigating to HBS alumni portal…")
    page.goto(HBS_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    _pause(1, 2)

    try:
        for label in ["Sign In", "Log In", "Login", "Sign in"]:
            btn = page.get_by_role("link", name=label)
            if btn.count() > 0:
                btn.first.click()
                _pause(1.5, 2.5)
                break

        email_field = page.locator(
            "input[type='email'], input[name='loginfmt'], input[id*='email' i], "
            "input[placeholder*='email' i], input[name='username']"
        ).first
        email_field.wait_for(state="visible", timeout=10000)
        email_field.fill(email)
        _pause(0.5, 1)

        for next_label in ["Next", "Continue", "Submit"]:
            nxt = page.get_by_role("button", name=next_label)
            if nxt.count() > 0:
                nxt.first.click()
                _pause(1, 2)
                break

        pw_field = page.locator(
            "input[type='password'], input[name='passwd'], input[id*='password' i]"
        ).first
        pw_field.wait_for(state="visible", timeout=10000)
        pw_field.fill(password)
        _pause(0.5, 1)

        page.keyboard.press("Enter")
        _pause(2, 4)

        if "signin" in page.url.lower() or "login" in page.url.lower():
            console.print("[red]  Login may have failed — still on login page[/red]")
            return False

        console.print("[green]  ✓ Logged in successfully[/green]")
        return True

    except PWTimeout:
        console.print("[red]  Login timed out — check credentials or MFA settings[/red]")
        return False
    except Exception as e:
        console.print(f"[red]  Login error: {e}[/red]")
        return False


# ── Alumni Directory Search ───────────────────────────────────────────────────

def search_alumni_by_company(page: Page, company_name: str) -> list[AlumContact]:
    """
    Navigate to the HBS alumni directory and search for people at the given company.
    Returns a list of AlumContact objects.
    """
    contacts: list[AlumContact] = []

    console.print("  → Opening alumni directory…")
    page.goto(HBS_ALUMNI_URL, wait_until="domcontentloaded", timeout=30000)
    _pause(2, 3)

    try:
        employer_field = page.locator(
            "input[placeholder*='employer' i], input[id*='employer' i], "
            "input[name*='employer' i], input[aria-label*='employer' i], "
            "input[placeholder*='company' i], input[id*='company' i]"
        ).first
        employer_field.wait_for(state="visible", timeout=10000)
        employer_field.fill(company_name)
        _pause(0.8, 1.5)
    except PWTimeout:
        console.print("[yellow]  Employer field not found — trying generic search[/yellow]")
        try:
            search_box = page.locator("input[type='search'], input[type='text']").first
            search_box.fill(company_name)
            _pause(0.8, 1.5)
        except Exception:
            console.print("[red]  Could not locate any search field[/red]")
            return contacts

    page.keyboard.press("Enter")
    _pause(2, 3.5)

    contacts = _parse_directory_results(page, company_name)
    console.print(f"  → Found [cyan]{len(contacts)}[/cyan] alumni at {company_name}")
    return contacts


def _parse_directory_results(page: Page, company_name: str) -> list[AlumContact]:
    contacts: list[AlumContact] = []
    page_num = 1

    while len(contacts) < MAX_RESULTS:
        _pause(1, 2)

        result_cards = page.locator(
            ".alumni-result, .directory-result, .person-card, "
            "[class*='result' i], [class*='alumnus' i], [class*='member' i], "
            "li.search-result, div.search-result, article"
        ).all()

        if not result_cards:
            result_cards = page.locator("table tbody tr").all()

        if not result_cards:
            console.print(f"  [dim]No result cards found on page {page_num}[/dim]")
            break

        for card in result_cards:
            try:
                contact = _extract_contact_from_card(card, company_name)
                if contact:
                    contacts.append(contact)
            except Exception as e:
                console.print(f"  [dim]Skipping card: {e}[/dim]")

        next_btn = page.locator(
            "a[aria-label='Next'], button[aria-label='Next'], "
            "a:has-text('Next'), a:has-text('>'), .pagination-next"
        ).first

        if next_btn.count() == 0 or not next_btn.is_visible():
            break

        next_btn.click()
        page_num += 1
        _pause(1.5, 2.5)

    return contacts[:MAX_RESULTS]


def _extract_contact_from_card(card, company_name: str) -> Optional[AlumContact]:
    name = ""
    for sel in ["h2", "h3", "h4", "strong", "a", ".name", "[class*='name' i]"]:
        try:
            el = card.locator(sel).first
            if el.count() > 0:
                t = el.inner_text().strip()
                if t and len(t) > 2 and len(t) < 80:
                    name = t
                    break
        except Exception:
            pass

    if not name:
        return None

    title = ""
    for sel in [".title", ".role", ".position", "[class*='title' i]",
                "[class*='role' i]", "p", "span"]:
        try:
            el = card.locator(sel).first
            if el.count() > 0:
                t = el.inner_text().strip()
                if t and t != name and len(t) < 120:
                    title = t
                    break
        except Exception:
            pass

    full_text = ""
    try:
        full_text = card.inner_text()
    except Exception:
        pass

    grad_year = None
    year_match = re.search(r"\b(19[6-9]\d|20[0-2]\d)\b", full_text)
    if year_match:
        grad_year = int(year_match.group())

    profile_url = ""
    try:
        link = card.locator("a").first
        if link.count() > 0:
            href = link.get_attribute("href") or ""
            if href:
                profile_url = href if href.startswith("http") else f"https://www.alumni.hbs.edu{href}"
    except Exception:
        pass

    title_lower = title.lower()
    is_founder = any(kw in title_lower for kw in FOUNDER_KEYWORDS)

    return AlumContact(
        name=name,
        title=title,
        company=company_name,
        grad_year=grad_year,
        profile_url=profile_url,
        is_founder=is_founder,
    )


# ── 2nd-time Founder Detection ────────────────────────────────────────────────

def check_second_time_founder(page: Page, contact: AlumContact) -> AlumContact:
    """
    Visit the contact's profile page to check for prior startup experience.
    Sets contact.second_time_founder and contact.prior_companies.
    """
    if not contact.profile_url or not contact.is_founder:
        return contact

    console.print(f"    → Checking founder history for [bold]{contact.name}[/bold]…")

    try:
        page.goto(contact.profile_url, wait_until="domcontentloaded", timeout=20000)
        _pause(1.5, 2.5)

        full_text = page.inner_text("body")

        experience_sections = page.locator(
            "[class*='experience' i], [class*='history' i], "
            "[class*='career' i], [class*='work' i]"
        ).all()

        prior_companies = []
        for section in experience_sections:
            try:
                text = section.inner_text()
                for line in text.split("\n"):
                    line = line.strip()
                    if (2 < len(line) < 60
                            and line.istitle()
                            and line.lower() not in STARTUP_SKIP
                            and line.lower() != contact.company.lower()):
                        prior_companies.append(line)
            except Exception:
                pass

        if not prior_companies:
            found_matches = re.findall(
                r"(?:founded|co-founded|started)\s+([A-Z][A-Za-z0-9\s]{2,40})",
                full_text,
                re.IGNORECASE,
            )
            prior_companies = [m.strip() for m in found_matches if m.strip()]

        prior_companies = [
            c for c in prior_companies
            if c.lower() != contact.company.lower()
            and not any(skip in c.lower() for skip in STARTUP_SKIP)
        ]

        if prior_companies:
            contact.second_time_founder = True
            contact.prior_companies = prior_companies[:5]
            contact.notes = f"Prior startups: {', '.join(contact.prior_companies)}"
            console.print(
                f"    [green]★ 2nd-time founder[/green] — "
                f"prior: {', '.join(contact.prior_companies[:2])}"
            )
        else:
            console.print(f"    [dim]No prior startup found[/dim]")

    except PWTimeout:
        console.print(f"    [yellow]Profile page timed out[/yellow]")
    except Exception as e:
        console.print(f"    [dim]Profile check error: {e}[/dim]")

    _pause(*REQUEST_DELAY)
    return contact


# ── Supabase push ─────────────────────────────────────────────────────────────

def get_company_id(db: SupabaseHelper, company_name: str) -> Optional[str]:
    """Look up the company UUID in Supabase by name."""
    row = db.get_company_by_name(company_name)
    return row["id"] if row else None


def push_contact_to_supabase(
    db: SupabaseHelper,
    contact: AlumContact,
    company_id: str,
    dry_run: bool = False,
) -> bool:
    """Create a contacts row. Returns True if created."""
    if db.contact_exists(contact.name, company_id):
        console.print(f"  [dim]↩ {contact.name} already in Contacts — skipping[/dim]")
        return False

    tier = "Tier 1 (HBS/Warm)"

    notes_parts = []
    if contact.second_time_founder:
        notes_parts.append("[2nd-time founder]")
    if contact.notes:
        notes_parts.append(contact.notes)
    if contact.profile_url:
        notes_parts.append(f"Profile: {contact.profile_url}")

    record = {
        "name":           contact.name,
        "role_title":     contact.title or "Unknown",
        "company_id":     company_id,
        "hbs_alumni":     True,
        "hbs_grad_year":  contact.grad_year,
        "linkedin_url":   contact.profile_url or None,
        "outreach_tier":  tier,
        "status":         "Not Contacted",
        "notes":          " | ".join(notes_parts) or None,
    }

    if dry_run:
        console.print(
            f"  [dim][DRY RUN] Would create contact: {contact.name} "
            f"({contact.title}, HBS '{str(contact.grad_year)[-2:] if contact.grad_year else '?'})"
            f"{'  ★ 2nd founder' if contact.second_time_founder else ''}[/dim]"
        )
        return True

    try:
        db.insert_contact(record)
        console.print(
            f"  [green]✓[/green] {contact.name} "
            f"[dim]({contact.title}"
            f"{', HBS ' + str(contact.grad_year) if contact.grad_year else ''})"
            f"{'  [yellow]★ 2nd founder[/yellow]' if contact.second_time_founder else ''}[/dim]"
        )
        return True
    except Exception as e:
        console.print(f"  [red]✗ Failed to create {contact.name}: {e}[/red]")
        return False


def update_company_flags(
    db: SupabaseHelper,
    company_id: str,
    contacts: list[AlumContact],
    dry_run: bool = False,
):
    """Update company-level flags: hbs_alumni_at_company + outreach_tier."""
    has_alumni          = len(contacts) > 0
    has_second_founder  = any(c.second_time_founder for c in contacts)
    tier = "Tier 1 (HBS/Warm)" if has_alumni else "Tier 2 (Founder Direct)"

    if dry_run:
        console.print(
            f"  [dim][DRY RUN] Would set company: "
            f"hbs_alumni_at_company={has_alumni}, outreach_tier={tier}[/dim]"
        )
        return

    try:
        db.update_company(company_id, {
            "hbs_alumni_at_company": has_alumni,
            "outreach_tier":         tier,
        })
        console.print(
            f"  [green]✓[/green] Company updated — "
            f"HBS alumni: {has_alumni}, Tier: {tier}"
            f"{'  [yellow]★ 2nd-time founder found[/yellow]' if has_second_founder else ''}"
        )
    except Exception as e:
        console.print(f"  [yellow]⚠ Could not update company flags: {e}[/yellow]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Research HBS alumni contacts for a target company."
    )
    parser.add_argument("--company",  required=True, help="Company name (must exist in Supabase companies table)")
    parser.add_argument("--headless", default="true", help="Run browser headless (true/false)")
    parser.add_argument("--dry-run",  action="store_true", help="Preview without writing to Supabase")
    args = parser.parse_args()

    headless = args.headless.lower() != "false"
    company  = args.company.strip()

    console.print(Panel.fit(
        f"[bold blue]Contact Research Agent[/bold blue]\n"
        f"Company: [cyan]{company}[/cyan]  |  "
        f"Headless: {headless}  |  "
        f"Dry run: {args.dry_run}",
        border_style="blue",
    ))

    # ── 1. Find company in Supabase ───────────────────────────────────────────
    db = SupabaseHelper()
    company_id = get_company_id(db, company)

    if not company_id:
        console.print(
            f"[red]Company '{company}' not found in Supabase.[/red]\n"
            f"[dim]Run filter_companies.py first, or check the exact name.[/dim]"
        )
        sys.exit(1)

    console.print(f"[green]✓[/green] Found company in Supabase: [dim]{company_id}[/dim]")

    # ── 2. Browser automation ──────────────────────────────────────────────────
    contacts: list[AlumContact] = []

    with sync_playwright() as pw:
        browser, ctx, session_loaded = make_context(pw, headless)
        page = ctx.new_page()

        console.print("\n[bold]Step 1 — HBS login[/bold]")
        if session_loaded:
            console.print("  [green]✓ Loaded saved session (hbs_session.json) — skipping login[/green]")
            # Navigate to the directory to confirm session is still valid
            page.goto(HBS_ALUMNI_URL, wait_until="domcontentloaded", timeout=30000)
            if "signin" in page.url.lower() or "login" in page.url.lower() or "microsoftonline" in page.url.lower():
                console.print(
                    "  [yellow]⚠ Saved session has expired.[/yellow]\n"
                    "  [dim]Run: python save_hbs_session.py  to refresh it.[/dim]"
                )
                browser.close()
                sys.exit(1)
        else:
            console.print(
                "  [yellow]No saved session found.[/yellow]\n"
                "  [dim]Tip: run  python save_hbs_session.py  once to save your session\n"
                "  and avoid MFA prompts in future runs.[/dim]"
            )
            logged_in = hbs_login(page)
            if not logged_in:
                console.print("[red]Cannot proceed without login. Check HBS_EMAIL / HBS_PASSWORD.[/red]")
                browser.close()
                sys.exit(1)

        console.print(f"\n[bold]Step 2 — Alumni directory search for '{company}'[/bold]")
        contacts = search_alumni_by_company(page, company)

        if contacts:
            founders = [c for c in contacts if c.is_founder]
            if founders:
                console.print(f"\n[bold]Step 3 — 2nd-time founder check ({len(founders)} founder(s))[/bold]")
                for i, contact in enumerate(contacts):
                    if contact.is_founder:
                        contacts[i] = check_second_time_founder(page, contact)
                        _pause(*REQUEST_DELAY)
            else:
                console.print("\n[bold]Step 3 — No founders found, skipping history check[/bold]")

        browser.close()

    # ── 3. Push to Supabase ───────────────────────────────────────────────────
    console.print(f"\n[bold]Step 4 — Push to Supabase[/bold]")

    if not contacts:
        console.print(f"[yellow]No HBS alumni found at {company}.[/yellow]")
        update_company_flags(db, company_id, [], dry_run=args.dry_run)
    else:
        created = 0
        for contact in contacts:
            ok = push_contact_to_supabase(db, contact, company_id, dry_run=args.dry_run)
            if ok:
                created += 1

        update_company_flags(db, company_id, contacts, dry_run=args.dry_run)

        table = Table(title=f"HBS Alumni @ {company}", show_lines=True)
        table.add_column("Name",        style="bold")
        table.add_column("Title",       style="dim")
        table.add_column("HBS Year",    justify="center")
        table.add_column("Founder",     justify="center")
        table.add_column("2nd Founder", justify="center")

        for c in contacts:
            table.add_row(
                c.name,
                c.title or "—",
                str(c.grad_year) if c.grad_year else "—",
                "✓" if c.is_founder else "",
                "★" if c.second_time_founder else "",
            )

        console.print(table)
        console.print(
            f"\n[green]Done.[/green] "
            f"{'[DRY RUN] Would have created' if args.dry_run else 'Created'} "
            f"[bold]{created}[/bold] of {len(contacts)} contacts."
        )


if __name__ == "__main__":
    main()
