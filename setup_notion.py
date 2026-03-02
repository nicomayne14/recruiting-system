"""
setup_notion.py — ONE-TIME setup: creates all 4 Notion databases with exact schema.
Reads NOTION_PARENT_PAGE_ID from .env, writes DB IDs back into .env automatically.
"""

import os
import re
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from notion_helper import NotionHelper

load_dotenv()
console = Console()

# ── Schema definitions ────────────────────────────────────────────────────────

COMPANIES_SCHEMA = {
    "Name": {"title": {}},
    "Website": {"url": {}},
    "Sector": {
        "multi_select": {
            "options": [
                {"name": "Mobility", "color": "blue"},
                {"name": "Marketplace", "color": "green"},
                {"name": "Vertical SaaS", "color": "purple"},
                {"name": "CleanTech", "color": "default"},
                {"name": "DataCenters", "color": "gray"},
                {"name": "AI", "color": "orange"},
                {"name": "FinTech", "color": "yellow"},
                {"name": "Other", "color": "default"},
            ]
        }
    },
    "HQ City": {"rich_text": {}},
    "Total Funding ($M)": {"number": {"format": "number"}},
    "Stage Estimate": {
        "select": {
            "options": [
                {"name": "Seed", "color": "gray"},
                {"name": "Series A", "color": "green"},
                {"name": "Series B", "color": "blue"},
                {"name": "Series C+", "color": "purple"},
            ]
        }
    },
    "Year Founded": {"number": {"format": "number"}},
    "Description": {"rich_text": {}},
    "Source": {
        "select": {
            "options": [
                {"name": "Bussgang USA", "color": "blue"},
                {"name": "Bussgang Europe", "color": "green"},
                {"name": "Bussgang Canada", "color": "red"},
                {"name": "Bussgang MENA", "color": "orange"},
                {"name": "Existing Research", "color": "purple"},
            ]
        }
    },
    "Fit Score": {"number": {"format": "number"}},
    "Outreach Tier": {
        "select": {
            "options": [
                {"name": "Tier 1 (HBS/Warm)", "color": "green"},
                {"name": "Tier 2 (Founder Direct)", "color": "yellow"},
                {"name": "Tier 3 (Cold)", "color": "gray"},
            ]
        }
    },
    "HBS Alumni at Company": {"checkbox": {}},
    "2nd Time Founder": {"checkbox": {}},
    "VC Connection": {"checkbox": {}},
    "Status": {
        "select": {
            "options": [
                {"name": "Not Started", "color": "gray"},
                {"name": "Researching", "color": "yellow"},
                {"name": "Outreach Sent", "color": "blue"},
                {"name": "Responded", "color": "green"},
                {"name": "Coffee Chat Scheduled", "color": "default"},
                {"name": "Interviewed", "color": "purple"},
                {"name": "Offer", "color": "pink"},
                {"name": "Rejected", "color": "red"},
                {"name": "Paused", "color": "brown"},
            ]
        }
    },
    "Priority": {
        "select": {
            "options": [
                {"name": "High", "color": "red"},
                {"name": "Medium", "color": "yellow"},
                {"name": "Low", "color": "gray"},
            ]
        }
    },
    "Gift Prepared": {"checkbox": {}},
    "Last Action Date": {"date": {}},
    "Next Action Date": {"date": {}},
    "Next Action": {"rich_text": {}},
    "LinkedIn URL": {"url": {}},
    "Notes": {"rich_text": {}},
}

CONTACTS_SCHEMA = {
    "Name": {"title": {}},
    "Role / Title": {"rich_text": {}},
    # Company relation added after Companies DB is created
    "LinkedIn URL": {"url": {}},
    "Email": {"email": {}},
    "HBS Alumni": {"checkbox": {}},
    "HBS Grad Year": {"number": {"format": "number"}},
    "Outreach Channel": {
        "select": {
            "options": [
                {"name": "HBS Email System", "color": "blue"},
                {"name": "LinkedIn DM", "color": "default"},
                {"name": "Direct Email", "color": "green"},
            ]
        }
    },
    "Outreach Tier": {
        "select": {
            "options": [
                {"name": "Tier 1", "color": "green"},
                {"name": "Tier 2", "color": "yellow"},
                {"name": "Tier 3", "color": "gray"},
            ]
        }
    },
    "Status": {
        "select": {
            "options": [
                {"name": "Not Contacted", "color": "gray"},
                {"name": "Draft Ready", "color": "yellow"},
                {"name": "Sent", "color": "blue"},
                {"name": "Responded", "color": "green"},
                {"name": "Meeting Scheduled", "color": "default"},
            ]
        }
    },
    "Last Contact Date": {"date": {}},
    "Notes": {"rich_text": {}},
}

INTERACTIONS_SCHEMA = {
    "Title": {"title": {}},
    "Type": {
        "select": {
            "options": [
                {"name": "LinkedIn Message", "color": "blue"},
                {"name": "HBS Email", "color": "default"},
                {"name": "Coffee Chat", "color": "green"},
                {"name": "Interview", "color": "purple"},
                {"name": "Follow-up", "color": "yellow"},
                {"name": "VC Intro", "color": "orange"},
                {"name": "Application", "color": "gray"},
            ]
        }
    },
    # Company + Contact relations added after those DBs exist
    "Date": {"date": {}},
    "Message Sent": {"rich_text": {}},
    "Response Received": {"rich_text": {}},
    "Gift Prepared": {"checkbox": {}},
    "Gift Notes": {"rich_text": {}},
    "Next Step": {"rich_text": {}},
    "Notes": {"rich_text": {}},
}

APPLICATIONS_SCHEMA = {
    "Title": {"title": {}},
    # Company relation added after Companies DB exists
    "Role": {"rich_text": {}},
    "Platform": {
        "select": {
            "options": [
                {"name": "Company Website", "color": "blue"},
                {"name": "LinkedIn", "color": "default"},
                {"name": "HBS Job Board", "color": "green"},
                {"name": "AngelList", "color": "orange"},
                {"name": "Referral", "color": "purple"},
                {"name": "Email", "color": "gray"},
            ]
        }
    },
    "Applied Date": {"date": {}},
    "Status": {
        "select": {
            "options": [
                {"name": "Applied", "color": "blue"},
                {"name": "Screening", "color": "yellow"},
                {"name": "Phone Screen", "color": "orange"},
                {"name": "Interview", "color": "purple"},
                {"name": "Final Round", "color": "default"},
                {"name": "Offer", "color": "green"},
                {"name": "Rejected", "color": "red"},
                {"name": "Withdrawn", "color": "gray"},
            ]
        }
    },
    # Contact relation added after Contacts DB exists
    "Notes": {"rich_text": {}},
    "Follow-up Due": {"date": {}},
}


# ── .env writer ───────────────────────────────────────────────────────────────

def update_env(key: str, value: str, env_path: str = ".env") -> None:
    """Update or append a key=value line in .env without touching other lines."""
    with open(env_path, "r") as f:
        content = f.read()

    pattern = rf"^({re.escape(key)}\s*=).*$"
    replacement = rf"\g<1>{value}"

    if re.search(pattern, content, flags=re.MULTILINE):
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip() + f"\n{key}={value}\n"

    with open(env_path, "w") as f:
        f.write(new_content)


# ── Relation adder (post-creation) ────────────────────────────────────────────

def add_relation(notion: NotionHelper, db_id: str, prop_name: str, target_db_id: str) -> None:
    """Add a relation property to an existing database."""
    notion._call(
        notion.client.databases.update,
        database_id=db_id,
        properties={
            prop_name: {
                "relation": {
                    "database_id": target_db_id,
                    "single_property": {},
                }
            }
        },
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    console.print(Panel.fit(
        "[bold blue]Notion Database Setup[/bold blue]\n"
        "Creating all 4 databases and wiring relations",
        border_style="blue",
    ))

    parent_id = os.getenv("NOTION_PARENT_PAGE_ID", "")
    # Strip any "CRM-" prefix — Notion expects a bare UUID or dashed UUID
    parent_id = parent_id.split("-", 1)[-1] if parent_id.startswith("CRM-") else parent_id
    if not parent_id:
        console.print("[red]NOTION_PARENT_PAGE_ID is not set in .env[/red]")
        raise SystemExit(1)

    notion = NotionHelper()
    db_ids: dict[str, str] = {}

    databases = [
        ("Companies", COMPANIES_SCHEMA, "NOTION_COMPANIES_DB_ID"),
        ("Contacts", CONTACTS_SCHEMA, "NOTION_CONTACTS_DB_ID"),
        ("Interactions", INTERACTIONS_SCHEMA, "NOTION_INTERACTIONS_DB_ID"),
        ("Applications", APPLICATIONS_SCHEMA, "NOTION_APPLICATIONS_DB_ID"),
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for db_name, schema, env_key in databases:
            existing_id = os.getenv(env_key, "").strip()
            if existing_id:
                db_ids[db_name] = existing_id
                console.print(f"  [dim]↩ {db_name} already exists → {existing_id}[/dim]")
                continue

            task = progress.add_task(f"Creating [cyan]{db_name}[/cyan] database…", total=None)
            try:
                result = notion.create_database(parent_id, db_name, schema)
                db_id = result["id"]
                db_ids[db_name] = db_id
                update_env(env_key, db_id)
                progress.update(task, description=f"[green]✓[/green] {db_name} → [dim]{db_id}[/dim]")
                progress.stop_task(task)
            except Exception as e:
                progress.update(task, description=f"[red]✗ {db_name}: {e}[/red]")
                progress.stop_task(task)
                raise

    # ── Wire cross-database relations ─────────────────────────────────────────
    console.print("\n[bold]Wiring relations…[/bold]")

    relations = [
        # (source_db, prop_name, target_db)
        ("Contacts",     "Company",  "Companies"),
        ("Interactions", "Company",  "Companies"),
        ("Interactions", "Contact",  "Contacts"),
        ("Applications", "Company",  "Companies"),
        ("Applications", "Contact",  "Contacts"),
    ]

    for src, prop, tgt in relations:
        src_id = db_ids[src]
        tgt_id = db_ids[tgt]
        try:
            add_relation(notion, src_id, prop, tgt_id)
            console.print(f"  [green]✓[/green] {src}.{prop} → {tgt}")
        except Exception as e:
            console.print(f"  [yellow]⚠ {src}.{prop}: {e}[/yellow]")

    # ── Summary ───────────────────────────────────────────────────────────────
    lines = []
    for name in ["Companies", "Contacts", "Interactions", "Applications"]:
        lines.append(f"[bold]{name}[/bold]: [dim]{db_ids[name]}[/dim]")
    console.print(Panel.fit(
        "\n".join(lines),
        title="[green]All databases created[/green]",
        border_style="green",
    ))
    console.print("[dim]Database IDs written to .env[/dim]\n")
    console.print(
        "[yellow]NOTE:[/yellow] Share the CRM page with your Notion integration so "
        "agents can read/write data.\n"
        "  CRM page → ··· → Connections → [your integration name]"
    )


if __name__ == "__main__":
    main()
