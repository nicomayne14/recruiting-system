"""
agents/research_contacts.py — Agent 2
For a given company, scrapes the HBS Alumni Directory for alumni currently
working there, detects 2nd-time founders, and pushes contacts to Notion.

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
from notion_helper import NotionHelper

load_dotenv()
console = Console()

# ── Constants ─────────────────────────────────────────────────────────────────

HBS_ALUMNI_URL   = "https://www.alumni.hbs.edu/community/Pages/alumni-directory.aspx"
HBS_LOGIN_URL    = "https://www.alumni.hbs.edu"
REQUEST_DELAY    = (1.5, 3.5)   # random sleep range between page actions (seconds)
MAX_RESULTS      = 50           # cap per company to avoid abuse
FOUNDER_KEYWORDS = {"founder", "co-founder", "cofounder", "ceo", "chief executive"}
STARTUP_SKIP     = {            # prior employer names that aren't startups
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

    console.print(f"  → Navigating to HBS alumni portal…")
    page.goto(HBS_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    _pause(1, 2)

    # HBS uses an SSO/Azure AD login — look for the sign-in button or form
    try:
        # Try clicking a "Sign In" / "Log In" link first
        for label in ["Sign In", "Log In", "Login", "Sign in"]:
            btn = page.get_by_role("link", name=label)
            if btn.count() > 0:
                btn.first.click()
                _pause(1.5, 2.5)
                break

        # Fill email field
        email_field = page.locator(
            "input[type='email'], input[name='loginfmt'], input[id*='email' i], "
            "input[placeholder*='email' i], input[name='username']"
        ).first
        email_field.wait_for(state="visible", timeout=10000)
        email_field.fill(email)
        _pause(0.5, 1)

        # Click Next if present (Microsoft SSO pattern)
        for next_label in ["Next", "Continue", "Submit"]:
            nxt = page.get_by_role("button", name=next_label)
            if nxt.count() > 0:
                nxt.first.click()
                _pause(1, 2)
                break

        # Fill password
        pw_field = page.locator(
            "input[type='password'], input[name='passwd'], input[id*='password' i]"
        ).first
        pw_field.wait_for(state="visible", timeout=10000)
        pw_field.fill(password)
        _pause(0.5, 1)

        # Submit
        page.keyboard.press("Enter")
        _pause(2, 4)

        # Check if we made it past login
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

    console.print(f"  → Opening alumni directory…")
    page.goto(HBS_ALUMNI_URL, wait_until="domcontentloaded", timeout=30000)
    _pause(2, 3)

    # ── Find and fill the "Current Employer" search field ─────────────────────
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
        # Fallback: try a generic search box
        console.print("[yellow]  Employer field not found — trying generic search[/yellow]")
        try:
            search_box = page.locator("input[type='search'], input[type='text']").first
            search_box.fill(company_name)
            _pause(0.8, 1.5)
        except Exception:
            console.print("[red]  Could not locate any search field[/red]")
            return contacts

    # Submit the search
    page.keyboard.press("Enter")
    _pause(2, 3.5)

    # ── Parse results ──────────────────────────────────────────────────────────
    contacts = _parse_directory_results(page, company_name)
    console.print(f"  → Found [cyan]{len(contacts)}[/cyan] alumni at {company_name}")
    return contacts


def _parse_directory_results(page: Page, company_name: str) -> list[AlumContact]:
    """
    Extract alumni entries from the directory results page.
    Handles multiple possible layouts the HBS directory uses.
    """
    contacts: list[AlumContact] = []
    page_num = 1

    while len(contacts) < MAX_RESULTS:
        _pause(1, 2)

        # Try common result-card selectors
        result_cards = page.locator(
            ".alumni-result, .directory-result, .person-card, "
            "[class*='result' i], [class*='alumnus' i], [class*='member' i], "
            "li.search-result, div.search-result, article"
        ).all()

        if not result_cards:
            # Try table rows as fallback
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

        # Try to go to next page
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
    """Extract a single AlumContact from a result card element."""
    # Name — try heading tags, strong, or link text
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

    # Title / role
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

    # Graduation year — look for 4-digit year starting with 19 or 20
    full_text = ""
    try:
        full_text = card.inner_text()
    except Exception:
        pass

    grad_year = None
    year_match = re.search(r"\b(19[6-9]\d|20[0-2]\d)\b", full_text)
    if year_match:
        grad_year = int(year_match.group())

    # Profile URL
    profile_url = ""
    try:
        link = card.locator("a").first
        if link.count() > 0:
            href = link.get_attribute("href") or ""
            if href:
                profile_url = href if href.startswith("http") else f"https://www.alumni.hbs.edu{href}"
    except Exception:
        pass

    # Founder detection
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

        # Extract company names from profile (look for experience sections)
        experience_sections = page.locator(
            "[class*='experience' i], [class*='history' i], "
            "[class*='career' i], [class*='work' i]"
        ).all()

        prior_companies = []
        for section in experience_sections:
            try:
                text = section.inner_text()
                # Find lines that look like company names (title-cased, short)
                for line in text.split("\n"):
                    line = line.strip()
                    if (2 < len(line) < 60
                            and line.istitle()
                            and line.lower() not in STARTUP_SKIP
                            and line.lower() != contact.company.lower()):
                        prior_companies.append(line)
            except Exception:
                pass

        # Simpler fallback: look for "Founded" or "Co-founded" in body text
        if not prior_companies:
            found_matches = re.findall(
                r"(?:founded|co-founded|started)\s+([A-Z][A-Za-z0-9\s]{2,40})",
                full_text,
                re.IGNORECASE,
            )
            prior_companies = [m.strip() for m in found_matches if m.strip()]

        # Filter out current company and big-co noise
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


# ── Notion push ───────────────────────────────────────────────────────────────

def get_company_page_id(notion: NotionHelper, company_name: str) -> Optional[str]:
    """Look up the company page ID in the Companies DB."""
    companies_db = os.getenv("NOTION_COMPANIES_DB_ID", "")
    if not companies_db:
        console.print("[red]NOTION_COMPANIES_DB_ID not set in .env[/red]")
        return None

    pages = notion.query_database(
        companies_db,
        filter_={"property": "Name", "title": {"equals": company_name}},
    )
    if not pages:
        # Fuzzy fallback — try contains
        pages = notion.query_database(
            companies_db,
            filter_={"property": "Name", "title": {"contains": company_name}},
        )
    return pages[0]["id"] if pages else None


def contact_exists(notion: NotionHelper, name: str, company_page_id: str) -> bool:
    """Return True if this contact is already in the Contacts DB."""
    contacts_db = os.getenv("NOTION_CONTACTS_DB_ID", "")
    existing = notion.query_database(
        contacts_db,
        filter_={"property": "Name", "title": {"equals": name}},
    )
    for page in existing:
        relations = page["properties"].get("Company", {}).get("relation", [])
        if any(r["id"].replace("-", "") == company_page_id.replace("-", "")
               for r in relations):
            return True
    return False


def push_contact_to_notion(
    notion: NotionHelper,
    contact: AlumContact,
    company_page_id: str,
    dry_run: bool = False,
) -> bool:
    """Create a Contacts DB page for the contact. Returns True if created."""
    contacts_db = os.getenv("NOTION_CONTACTS_DB_ID", "")
    if not contacts_db:
        console.print("[red]NOTION_CONTACTS_DB_ID not set in .env[/red]")
        return False

    if contact_exists(notion, contact.name, company_page_id):
        console.print(f"  [dim]↩ {contact.name} already in Contacts — skipping[/dim]")
        return False

    # Determine outreach tier
    tier = "Tier 1 (HBS/Warm)"   # All HBS alumni are Tier 1 by default

    notes_parts = []
    if contact.notes:
        notes_parts.append(contact.notes)
    if contact.second_time_founder:
        notes_parts.insert(0, "[2nd-time founder]")
    if contact.profile_url:
        notes_parts.append(f"Profile: {contact.profile_url}")

    props = {
        **notion.title(contact.name),
        "Role / Title":  notion.rich_text(contact.title or "Unknown"),
        "Company":       notion.relation([company_page_id]),
        "HBS Alumni":    notion.checkbox(True),
        "Outreach Tier": notion.select(tier),
        "Status":        notion.select("Not Contacted"),
        "Notes":         notion.rich_text(" | ".join(notes_parts)),
    }

    if contact.grad_year:
        props["HBS Grad Year"] = notion.number(contact.grad_year)
    if contact.profile_url:
        props["LinkedIn URL"] = notion.url(contact.profile_url)

    if dry_run:
        console.print(
            f"  [dim][DRY RUN] Would create contact: {contact.name} "
            f"({contact.title}, HBS '{str(contact.grad_year)[-2:] if contact.grad_year else '?'})"
            f"{'  ★ 2nd founder' if contact.second_time_founder else ''}[/dim]"
        )
        return True

    try:
        notion.create_page(contacts_db, props)
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
    notion: NotionHelper,
    company_page_id: str,
    contacts: list[AlumContact],
    dry_run: bool = False,
):
    """Update company-level flags: HBS Alumni checkbox + Outreach Tier."""
    has_alumni = len(contacts) > 0
    has_second_founder = any(c.second_time_founder for c in contacts)

    tier = "Tier 1 (HBS/Warm)" if has_alumni else "Tier 2 (Founder Direct)"

    if dry_run:
        console.print(
            f"  [dim][DRY RUN] Would set company: "
            f"HBS_Alumni={has_alumni}, Tier={tier}[/dim]"
        )
        return

    try:
        notion.update_page(company_page_id, {
            "HBS Alumni at Company": notion.checkbox(has_alumni),
            "Outreach Tier":         notion.select(tier),
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
    parser.add_argument("--company",   required=True,  help="Company name (must exist in Notion Companies DB)")
    parser.add_argument("--headless",  default="true",  help="Run browser headless (true/false)")
    parser.add_argument("--dry-run",   action="store_true", help="Preview without writing to Notion")
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

    # ── 1. Find company in Notion ──────────────────────────────────────────────
    notion = NotionHelper()
    company_page_id = get_company_page_id(notion, company)

    if not company_page_id:
        console.print(
            f"[red]Company '{company}' not found in Notion Companies DB.[/red]\n"
            f"[dim]Run filter_companies.py first, or check the exact name.[/dim]"
        )
        sys.exit(1)

    console.print(f"[green]✓[/green] Found company in Notion: [dim]{company_page_id}[/dim]")

    # ── 2. Browser automation ──────────────────────────────────────────────────
    contacts: list[AlumContact] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        # Step 1: login
        console.print("\n[bold]Step 1 — HBS login[/bold]")
        logged_in = hbs_login(page)
        if not logged_in:
            console.print("[red]Cannot proceed without login. Check HBS_EMAIL / HBS_PASSWORD.[/red]")
            browser.close()
            sys.exit(1)

        # Step 2: search alumni directory
        console.print(f"\n[bold]Step 2 — Alumni directory search for '{company}'[/bold]")
        contacts = search_alumni_by_company(page, company)

        # Step 3: check founder histories
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

    # ── 3. Push to Notion ──────────────────────────────────────────────────────
    console.print(f"\n[bold]Step 4 — Push to Notion[/bold]")

    if not contacts:
        console.print(f"[yellow]No HBS alumni found at {company}.[/yellow]")
        # Still update company to avoid re-searching
        update_company_flags(notion, company_page_id, [], dry_run=args.dry_run)
    else:
        created = 0
        for contact in contacts:
            ok = push_contact_to_notion(notion, contact, company_page_id, dry_run=args.dry_run)
            if ok:
                created += 1

        update_company_flags(notion, company_page_id, contacts, dry_run=args.dry_run)

        # ── Summary table ──────────────────────────────────────────────────────
        table = Table(title=f"HBS Alumni @ {company}", show_lines=True)
        table.add_column("Name",         style="bold")
        table.add_column("Title",        style="dim")
        table.add_column("HBS Year",     justify="center")
        table.add_column("Founder",      justify="center")
        table.add_column("2nd Founder",  justify="center")

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
            f"[bold]{created}[/bold] of {len(contacts)} contacts in Notion."
        )


if __name__ == "__main__":
    main()
