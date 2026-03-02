"""
agents/filter_companies.py — Agent 1
Loads all CSVs, applies stage heuristic + fit score, filters qualified companies,
and pushes them to the Notion Companies database.

Usage:
    python agents/filter_companies.py
    python agents/filter_companies.py --dry-run   # preview without writing to Notion
"""

import os
import sys
import glob
import argparse
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.table import Table

# Allow running from repo root or agents/ dir
sys.path.insert(0, str(Path(__file__).parent.parent))
from notion_helper import NotionHelper

load_dotenv()
console = Console()

# ── Constants from spec ───────────────────────────────────────────────────────

TARGET_SECTORS = ["Mobility", "Marketplace", "Vertical SaaS", "CleanTech",
                  "DataCenters", "Infrastructure"]
ADJACENT_SECTORS = ["AI", "SaaS", "Robotics", "HealthTech"]

# HQ string fragments that map to USA/Canada
USA_FRAGMENTS = ["usa", "united states", ", ca", ", ny", ", ma", ", tx", ", wa",
                 ", il", ", co", ", fl", ", ga", ", nc", ", oh", ", az", ", ut",
                 "san francisco", "new york", "boston", "seattle", "chicago",
                 "austin", "los angeles", "miami", "denver", "atlanta",
                 "cambridge", "palo alto", "menlo park", "mountain view",
                 "redwood city", "santa clara", "sunnyvale", "cupertino",
                 "minneapolis", "portland", "philadelphia", "detroit"]
CANADA_FRAGMENTS = ["canada", "toronto", "vancouver", "montreal", "calgary",
                    "ottawa", "ontario", "british columbia", "alberta", "quebec"]

FUZZY_THRESHOLD = 85   # minimum token_sort_ratio to flag as duplicate


# ── Scoring helpers ───────────────────────────────────────────────────────────

def estimate_stage(total_funding_m) -> str:
    try:
        f = float(total_funding_m)
    except (TypeError, ValueError):
        return "Unknown"
    if f < 10:
        return "Seed"
    if f < 50:
        return "Series A"
    if f < 150:
        return "Series B"
    return "Series C+"


def detect_region(hq_city: str) -> str:
    """Return 'USA', 'Canada', or 'Other' from a free-text HQ string."""
    hq = str(hq_city).lower()
    if any(frag in hq for frag in CANADA_FRAGMENTS):
        return "Canada"
    if any(frag in hq for frag in USA_FRAGMENTS):
        return "USA"
    return "Other"


def calculate_fit_score(sector: str, stage_estimate: str, hq_region: str) -> int:
    score = 0
    s = str(sector)
    if any(t in s for t in TARGET_SECTORS):
        score += 5
    elif any(a in s for a in ADJACENT_SECTORS):
        score += 3
    if stage_estimate in ("Series A", "Series B"):
        score += 3
    if hq_region in ("USA", "Canada"):
        score += 2
    return min(score, 10)


def map_sector_to_notion(sector: str) -> list[str]:
    """Map raw CSV sector string to valid Notion multi-select options."""
    notion_options = ["Mobility", "Marketplace", "Vertical SaaS", "CleanTech",
                      "DataCenters", "AI", "FinTech", "Other"]
    sector_map = {
        "saas": "Vertical SaaS",
        "vertical saas": "Vertical SaaS",
        "marketplace": "Marketplace",
        "mobility": "Mobility",
        "cleantech": "CleanTech",
        "clean tech": "CleanTech",
        "climate": "CleanTech",
        "energy": "CleanTech",
        "data center": "DataCenters",
        "datacenter": "DataCenters",
        "infrastructure": "DataCenters",
        "ai": "AI",
        "artificial intelligence": "AI",
        "fintech": "FinTech",
        "financial": "FinTech",
        "b2b marketplace": "Marketplace",
        "b2b_marketplace": "Marketplace",
        "ecommerce": "Marketplace",
        "manufacturing saas": "Vertical SaaS",
        "manufacturing": "Vertical SaaS",
        "vertical_saas": "Vertical SaaS",
        "agtech": "Vertical SaaS",
        "healthtech": "Other",
        "health tech": "Other",
        "spacetech": "Other",
        "robotics": "Other",
    }
    s_lower = str(sector).lower().strip()
    # Try direct map first
    if s_lower in sector_map:
        mapped = sector_map[s_lower]
        return [mapped]
    # Try partial match
    for key, val in sector_map.items():
        if key in s_lower:
            return [val]
    # Fall back to "Other" if nothing matches
    return ["Other"]


# ── CSV loaders ───────────────────────────────────────────────────────────────

def load_bussgang_csv(path: str, source_label: str, region_default: str) -> pd.DataFrame:
    """Load a Bussgang CSV (USA has 'Name', others have 'Company Name')."""
    df = pd.read_csv(path, encoding="utf-8-sig")

    # Normalize column name differences
    col_map = {}
    cols_lower = {c.lower(): c for c in df.columns}
    if "name" in cols_lower and "company name" not in cols_lower:
        col_map[cols_lower["name"]] = "Company"
    if "company name" in cols_lower:
        col_map[cols_lower["company name"]] = "Company"
    if "website url" in cols_lower:
        col_map[cols_lower["website url"]] = "Website"
    if "year founded" in cols_lower:
        col_map[cols_lower["year founded"]] = "Year Founded"
    if "funding" in cols_lower:
        col_map[cols_lower["funding"]] = "Total Funding ($M)"
    if "hq city" in cols_lower:
        col_map[cols_lower["hq city"]] = "HQ City"
    df = df.rename(columns=col_map)

    df["Source"] = source_label
    df["_region_hint"] = region_default
    df["_from_existing"] = False
    return df[["Company", "Website", "Sector", "Description", "Year Founded",
               "Total Funding ($M)", "HQ City", "Source", "_region_hint", "_from_existing"]]


def load_existing_targets_csv(path: str) -> pd.DataFrame:
    """Load a targets CSV (datacenter format with Stage/Fit_Score already set)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    cols_lower = {c.lower(): c for c in df.columns}

    col_map = {}
    # Company name
    for cname in ["company", "name", "company name"]:
        if cname in cols_lower:
            col_map[cols_lower[cname]] = "Company"
            break
    # Website
    for cname in ["website", "website url"]:
        if cname in cols_lower:
            col_map[cols_lower[cname]] = "Website"
            break
    # Sector / Vertical
    for cname in ["sector", "vertical", "business_model"]:
        if cname in cols_lower:
            col_map[cols_lower[cname]] = "Sector"
            break
    # Description
    for cname in ["description", "why_relevant", "notes"]:
        if cname in cols_lower:
            col_map[cols_lower[cname]] = "Description"
            break
    # Funding
    for cname in ["total_funding", "funding", "total funding ($m)"]:
        if cname in cols_lower:
            col_map[cols_lower[cname]] = "Total Funding ($M)"
            break
    # HQ
    for cname in ["hq", "hq city", "location"]:
        if cname in cols_lower:
            col_map[cols_lower[cname]] = "HQ City"
            break
    # Pre-computed fit score
    pre_score = None
    for cname in ["fit_score", "fit score"]:
        if cname in cols_lower:
            pre_score = cols_lower[cname]
            break

    df = df.rename(columns=col_map)
    df["Source"] = "Existing Research"
    df["_region_hint"] = "detect"
    df["_from_existing"] = True

    required = ["Company", "Website", "Sector", "Description", "Total Funding ($M)", "HQ City"]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    if "Year Founded" not in df.columns:
        df["Year Founded"] = None
    if pre_score and pre_score in df.columns:
        df["_pre_fit_score"] = df[pre_score]
    else:
        df["_pre_fit_score"] = None

    return df[["Company", "Website", "Sector", "Description", "Year Founded",
               "Total Funding ($M)", "HQ City", "Source", "_region_hint",
               "_from_existing", "_pre_fit_score"]]


def load_all_csvs(data_dir: str) -> pd.DataFrame:
    """Load and unify all source CSVs."""
    frames = []

    bussgang_files = {
        "bussgang_usa.csv":    ("Bussgang USA",    "USA"),
        "bussgang_europe.csv": ("Bussgang Europe", "Other"),
        "bussgang_canada.csv": ("Bussgang Canada", "Canada"),
        "bussgang_mena.csv":   ("Bussgang MENA",   "Other"),
    }
    for filename, (label, region) in bussgang_files.items():
        path = os.path.join(data_dir, filename)
        if os.path.exists(path):
            df = load_bussgang_csv(path, label, region)
            df["_pre_fit_score"] = None
            frames.append(df)
            console.print(f"  [dim]Loaded {len(df)} rows from {filename}[/dim]")
        else:
            console.print(f"  [yellow]⚠ {filename} not found — skipping[/yellow]")

    existing_dir = os.path.join(data_dir, "existing_targets")
    if os.path.isdir(existing_dir):
        for csv_path in glob.glob(os.path.join(existing_dir, "*.csv")):
            df = load_existing_targets_csv(csv_path)
            frames.append(df)
            console.print(f"  [dim]Loaded {len(df)} rows from {os.path.basename(csv_path)}[/dim]")

    if not frames:
        raise RuntimeError(f"No CSVs found in {data_dir}")

    combined = pd.concat(frames, ignore_index=True)
    combined["Company"] = combined["Company"].fillna("").astype(str).str.strip()
    combined = combined[combined["Company"] != ""]
    return combined


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove fuzzy duplicates, keeping existing_research over Bussgang."""
    df = df.sort_values("_from_existing", ascending=False).reset_index(drop=True)
    seen_names: list[str] = []
    keep_mask = []
    dup_count = 0

    for _, row in df.iterrows():
        name = row["Company"].lower()
        is_dup = any(
            fuzz.token_sort_ratio(name, seen) >= FUZZY_THRESHOLD
            for seen in seen_names
        )
        if is_dup:
            dup_count += 1
            keep_mask.append(False)
        else:
            seen_names.append(name)
            keep_mask.append(True)

    return df[keep_mask].reset_index(drop=True), dup_count


# ── Filtering ─────────────────────────────────────────────────────────────────

def apply_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (qualifying_df, skipped_df) after applying spec filter logic."""
    results = []
    for _, row in df.iterrows():
        region = (row["_region_hint"] if row["_region_hint"] != "detect"
                  else detect_region(str(row["HQ City"])))
        stage = estimate_stage(row["Total Funding ($M)"])
        fit = (int(row["_pre_fit_score"])
               if pd.notna(row.get("_pre_fit_score")) and row["_pre_fit_score"] is not None
               and str(row["_pre_fit_score"]) not in ("", "nan")
               else calculate_fit_score(str(row["Sector"]), stage, region))

        qualifies = (
            row["_from_existing"]  # always include existing research
            or (
                stage in ("Series A", "Series B")
                and fit >= 5
                and region in ("USA", "Canada")
            )
        )
        results.append({**row.to_dict(),
                        "_stage": stage,
                        "_fit": fit,
                        "_region": region,
                        "_qualifies": qualifies})

    result_df = pd.DataFrame(results)
    qualifying = result_df[result_df["_qualifies"]].reset_index(drop=True)
    skipped = result_df[~result_df["_qualifies"]].reset_index(drop=True)
    return qualifying, skipped


# ── Notion push ───────────────────────────────────────────────────────────────

def push_to_notion(
    df: pd.DataFrame,
    notion: NotionHelper,
    data_source_id: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Push qualifying companies to Notion. Returns (added, already_existed)."""
    if dry_run:
        console.print(f"  [dim][DRY RUN] Would push {len(df)} companies — skipping Notion API[/dim]")
        return len(df), 0

    console.print("[bold]Checking existing entries in Notion…[/bold]")
    existing_titles = notion.get_all_titles(data_source_id)
    console.print(f"  Found {len(existing_titles)} existing companies in Notion")

    added = 0
    already_existed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Pushing to Notion…", total=len(df))

        for _, row in df.iterrows():
            name = str(row["Company"]).strip()
            name_lower = name.lower()

            # Check for duplicate in Notion (exact or fuzzy)
            is_existing = any(
                fuzz.token_sort_ratio(name_lower, existing_name) >= FUZZY_THRESHOLD
                for existing_name in existing_titles.keys()
            )
            if is_existing:
                already_existed += 1
                progress.advance(task)
                continue

            notion_sectors = map_sector_to_notion(str(row["Sector"]))
            region = row.get("_region", detect_region(str(row["HQ City"])))
            stage = row.get("_stage", estimate_stage(row["Total Funding ($M)"]))
            fit = int(row.get("_fit", 0))

            properties = {
                "Name":               notion.title(name),
                "Website":            notion.url(str(row.get("Website", ""))),
                "Sector":             notion.multi_select(notion_sectors),
                "HQ City":            notion.rich_text(str(row.get("HQ City", ""))),
                "Total Funding ($M)": notion.number(row.get("Total Funding ($M)")),
                "Stage Estimate":     notion.select(stage),
                "Description":        notion.rich_text(str(row.get("Description", ""))[:2000]),
                "Source":             notion.select(str(row.get("Source", "Bussgang USA"))),
                "Fit Score":          notion.number(fit),
                "Status":             notion.select("Not Started"),
                "HBS Alumni at Company": notion.checkbox(False),
                "2nd Time Founder":   notion.checkbox(False),
                "VC Connection":      notion.checkbox(False),
                "Gift Prepared":      notion.checkbox(False),
            }
            if pd.notna(row.get("Year Founded")) and str(row.get("Year Founded", "")) not in ("", "nan"):
                properties["Year Founded"] = notion.number(row["Year Founded"])

            try:
                notion.create_page(data_source_id, properties)
                added += 1
                progress.update(task, description=f"[green]✓[/green] {name[:40]}")
            except Exception as e:
                console.print(f"\n  [red]✗ Failed to add {name}: {e}[/red]")

            progress.advance(task)

    return added, already_existed


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Filter companies and push to Notion")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview results without writing to Notion")
    parser.add_argument("--data-dir", default=None,
                        help="Path to data/ directory (default: auto-detect)")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold blue]Company Filter Agent[/bold blue]\n"
        "Loading CSVs → Scoring → Filtering → Notion",
        border_style="blue",
    ))
    if args.dry_run:
        console.print("[yellow]DRY RUN mode — no data will be written to Notion[/yellow]\n")

    # Auto-detect data dir: check inside repo, then one level up (sibling of repo)
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    candidates = [
        args.data_dir,
        str(repo_root / "data"),
        str(repo_root.parent / "data"),
    ]
    data_dir = next((p for p in candidates if p and os.path.isdir(p)), None)
    if not data_dir:
        console.print(
            f"[red]data/ directory not found. Pass --data-dir <path>[/red]"
        )
        raise SystemExit(1)

    # Use data source ID (collection ID) — needed for notion-client v3 API
    ds_id = os.getenv("NOTION_COMPANIES_DS_ID", "").strip()
    if not ds_id and not args.dry_run:
        console.print("[red]NOTION_COMPANIES_DS_ID not set in .env — run setup_notion.py first[/red]")
        raise SystemExit(1)

    # ── Step 1: Load ──────────────────────────────────────────────────────────
    console.print("\n[bold]Step 1 — Loading CSVs[/bold]")
    df = load_all_csvs(data_dir)
    console.print(f"  Total rows loaded: [cyan]{len(df)}[/cyan]")

    # ── Step 2: Deduplicate ───────────────────────────────────────────────────
    console.print("\n[bold]Step 2 — Deduplicating[/bold]")
    df, dup_count = deduplicate(df)
    console.print(f"  Duplicates removed: [yellow]{dup_count}[/yellow]")
    console.print(f"  Unique companies:   [cyan]{len(df)}[/cyan]")

    # ── Step 3: Score + filter ────────────────────────────────────────────────
    console.print("\n[bold]Step 3 — Scoring & filtering[/bold]")
    qualifying, skipped = apply_filters(df)
    console.print(f"  Qualifying (Series A/B, fit ≥ 5, USA/Canada + existing): [green]{len(qualifying)}[/green]")
    console.print(f"  Skipped (out of filter):                                   [dim]{len(skipped)}[/dim]")

    # Preview table
    if len(qualifying) > 0:
        table = Table(title="Top qualifying companies (first 10)", show_lines=False)
        table.add_column("Company", style="bold")
        table.add_column("Sector")
        table.add_column("Stage")
        table.add_column("Fit", justify="right")
        table.add_column("Region")
        table.add_column("Source")
        for _, row in qualifying.head(10).iterrows():
            table.add_row(
                str(row["Company"])[:30],
                str(row["Sector"])[:20],
                str(row["_stage"]),
                str(int(row["_fit"])),
                str(row["_region"]),
                str(row["Source"])[:18],
            )
        console.print(table)

    # ── Step 4: Push to Notion ────────────────────────────────────────────────
    console.print("\n[bold]Step 4 — Pushing to Notion[/bold]")
    notion = NotionHelper()
    added, already_existed = push_to_notion(qualifying, notion, ds_id, dry_run=args.dry_run)

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print(Panel.fit(
        f"[green]✓ Added to Notion:[/green]    {added}\n"
        f"[yellow]↩ Already existed:[/yellow]  {already_existed}\n"
        f"[dim]✗ Skipped (filtered):[/dim] {len(skipped)}\n"
        f"[dim]~ Duplicates merged:[/dim]  {dup_count}",
        title="[bold]Summary[/bold]",
        border_style="green" if added > 0 else "yellow",
    ))


if __name__ == "__main__":
    main()
