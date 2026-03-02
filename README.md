# Recruiting System
### An AI-powered, agent-based recruiting pipeline built for systematic startup job searching

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-green?logo=supabase)](https://supabase.com/)
[![Claude API](https://img.shields.io/badge/Anthropic-Claude-orange)](https://www.anthropic.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-dashboard-red?logo=streamlit)](https://streamlit.io/)
[![Playwright](https://img.shields.io/badge/Playwright-automation-green?logo=playwright)](https://playwright.dev/)

---

## Why I Built This

I'm an HBS MBA student targeting Series A startup internships in Mobility, Marketplace, Vertical SaaS, CleanTech, and DataCenters. The standard recruiting process — manually browsing job boards, copy-pasting messages, losing track of follow-ups — doesn't work for non-traditional startup recruiting where most roles aren't posted and most decisions happen through warm introductions.

So I built a system instead.

This project automates the research-heavy parts of startup recruiting: finding the right companies, surfacing HBS alumni connections, drafting personalized outreach at scale, and generating deep pre-meeting research briefs. It keeps everything organized in a Notion CRM and surfaces daily KPIs and action queues in a Streamlit dashboard.

It's also a deliberate demonstration of how I think about problems: identify the bottleneck, design a system, build and ship it.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
│  Bussgang Startup List (400+ companies)  +  Custom CSV Lists    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   AGENT 1: filter_companies                     │
│  Stage heuristics · Sector scoring · Geography filter           │
│  → Pushes qualified Series A/B companies into Notion            │
└────────────────────────┬────────────────────────────────────────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐
│   AGENT 2    │  │   AGENT 3    │  │        AGENT 5           │
│  research_   │  │  research_   │  │    parse_applications    │
│  contacts    │  │  company     │  │                          │
│              │  │              │  │  Gmail API → finds all   │
│  Playwright  │  │  Perplexity  │  │  past applications since │
│  → HBS dir   │  │  API →       │  │  Nov 2025 → populates    │
│  → LinkedIn  │  │  market      │  │  Applications DB         │
│  → surfaces  │  │  brief +     │  └──────────────────────────┘
│  warm paths  │  │  LATAM angle │
└──────┬───────┘  │  + "gift"    │
       │          │  insight     │
       │          └──────┬───────┘
       │                 │
       └────────┬────────┘
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   AGENT 4: draft_outreach                       │
│  Claude API · Tone-matched to real template · Channel-aware     │
│  LinkedIn DM / HBS Email / Direct Email                         │
│  → Saves draft to Notion Interactions DB                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NOTION CRM                                 │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Companies  │  │   Contacts   │  │    Interactions      │  │
│  │  DB         │◄─┤   DB         │◄─┤    DB                │  │
│  │  ~100 cos   │  │  HBS alumni  │  │  Messages, chats,    │  │
│  │  scored &   │  │  founders    │  │  follow-ups, notes   │  │
│  │  tiered     │  │  warm paths  │  │                      │  │
│  └─────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Applications DB · Past + ongoing apps tracked here      │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  STREAMLIT DASHBOARD (local)                    │
│                                                                 │
│  Tab 1: KPI Dashboard    Tab 2: Agent Runner  Tab 3: Queue      │
│  ─ Pipeline funnel       ─ Company select     ─ Follow-ups due  │
│  ─ Messages/week         ─ One-click agents   ─ Drafts ready    │
│  ─ Response rate         ─ Live agent log     ─ Stale contacts  │
│  ─ Coffee chats/week                                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agents

| Agent | Trigger | APIs Used | Output |
|-------|---------|-----------|--------|
| `filter_companies` | Manual / batch | pandas | Qualified companies in Notion |
| `research_contacts` | Per company | Playwright (HBS dir + LinkedIn) | HBS alumni + founder contacts |
| `research_company` | On coffee chat scheduled | Perplexity API | Market brief + LATAM angle + "gift" insight |
| `draft_outreach` | Per contact | Claude API | Personalized message draft in Notion |
| `parse_applications` | One-time init | Gmail API | Past applications in Notion |
| `check_followups` | Daily | Notion API | Follow-up digest + auto-drafted replies |

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| CRM & storage | [Supabase](https://supabase.com/) (PostgreSQL) | Reliable SQL backend, real-time, free tier, REST + Python client |
| Browser automation | [Playwright](https://playwright.dev/python/) | Reliable async browser control for HBS + LinkedIn |
| Research | [Perplexity API](https://docs.perplexity.ai/) | Real-time web search with source citations |
| Outreach drafting | [Anthropic Claude API](https://www.anthropic.com/) | Best-in-class instruction following for tone matching |
| Email parsing | [Gmail API](https://developers.google.com/gmail/api) | OAuth access to application history |
| Dashboard | [Streamlit](https://streamlit.io/) | Fast local dashboards with no infra overhead |
| Data processing | pandas + fuzzywuzzy | CSV normalization, deduplication |

---

## Company Filtering Logic

The Bussgang Startup List (~400 US companies) is filtered down to actionable targets using two heuristics:

**Stage estimate from total funding:**
```python
< $10M   → Seed
$10–50M  → Series A   ✓ target
$50–150M → Series B   ✓ target
> $150M  → Series C+  (excluded unless in existing research)
```

**Fit score (1–10) from sector:**
```python
Mobility / Marketplace / Vertical SaaS / CleanTech / DataCenters → +5
AI / SaaS / Robotics / HealthTech (adjacent)                     → +3
Series A or B stage                                               → +3
US / Canada geography                                             → +2
```

Companies scoring ≥ 5 in a Series A/B stage are included. Companies from manually curated sector research are always included regardless of score.

---

## Outreach Tier System

Every company in the CRM is assigned to one of three outreach tiers, which determines priority and message channel:

| Tier | Path | Expected Response Rate | Channel |
|------|------|----------------------|---------|
| **Tier 1** | HBS alumni at company | ~40–60% | HBS Email System |
| **Tier 2** | 2nd-time founder, direct approach | ~15–25% | LinkedIn DM |
| **Tier 3** | Cold outreach with personalized hook | ~5–10% | LinkedIn DM / Email |

---

## Setup

### Prerequisites
- Python 3.11+
- A [Supabase](https://supabase.com/) account (free tier is plenty)
- Anthropic API key
- Perplexity API key
- HBS alumni directory credentials
- LinkedIn account
- Gmail account (for application history parsing)

### Install

```bash
git clone https://github.com/YOUR_USERNAME/recruiting-system.git
cd recruiting-system

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium
```

### Configure

```bash
cp .env.example .env
# Edit .env with your API keys and credentials
```

### Initialize (Phase 1)

```bash
# 1. Create Supabase tables
#    → Copy the SQL printed by this command into Supabase → SQL Editor → Run
python setup_supabase.py

# 2. Test your connection
python setup_supabase.py   # (re-run; it tests tables after you create them)

# 3. Filter and import companies from CSV lists
# Add your CSVs to data/ following the format in data/sample/
python agents/filter_companies.py

# 4. Launch the dashboard
streamlit run app.py
```

### Run Agents

```bash
# Find contacts for a specific company
python agents/research_contacts.py --company "Revel"

# Generate research brief before a coffee chat
python agents/research_company.py --company "Revel"

# Draft an outreach message
python agents/draft_outreach.py --company "Revel" --contact "John Smith"

# Parse past applications from Gmail (run once)
python agents/parse_applications.py

# Check what needs follow-up today
python agents/check_followups.py
```

Or use the Streamlit **Agent Runner** tab for point-and-click control.

---

## Demo Mode

To explore the system without real credentials, set `DEMO_MODE=true` in your `.env`. This loads sample companies from `data/sample/` and returns mock agent responses. No real API calls are made.

```bash
DEMO_MODE=true streamlit run app.py
```

---

## Database Schema (Supabase / PostgreSQL)

Four linked tables:

```
companies ──< contacts ──< interactions
    │
    └──< applications
```

**companies:** name · website · sector (array) · hq_city · total_funding_m · stage_estimate · fit_score · outreach_tier · hbs_alumni_at_company · second_time_founder · status · next_action

**contacts:** name · role_title · company_id (FK) · linkedin_url · hbs_alumni · hbs_grad_year · outreach_tier · status · notes

**interactions:** type · company_id (FK) · contact_id (FK) · date · message_sent · response · gift_prepared · followup_due · followup_sent

**applications:** company_id (FK) · role · platform · applied_date · status · followup_due

---

## KPI Targets

| Metric | Weekly Goal |
|--------|------------|
| Outreach messages sent | 40–50 |
| New contacts researched | 20 |
| Coffee chats scheduled | 3–5 |
| Research briefs generated | 3–5 |
| Applications submitted | 5–10 |

---

## Project Status

- [x] Architecture + spec finalized
- [x] Backend migrated from Notion → Supabase (PostgreSQL)
- [x] Phase 1: Supabase schema + company filtering agent
- [x] Phase 2: Contact research agent (HBS alumni directory + 2nd-time founder detection)
- [ ] Phase 3: Outreach drafting agent (Claude API)
- [ ] Phase 4: Gmail parsing + follow-up automation
- [ ] Full Streamlit UI

---

## Context

Built as a personal tool during HBS MBA Year 1 recruiting (Spring 2026). Target: Series A startup internship in Mobility / Marketplace / Vertical SaaS / CleanTech / DataCenters, with the long-term goal of returning to LATAM as a founder with US operator experience.

The "come bearing gifts" principle from Jeff Bussgang's [*Are You Suited for a Start-Up?*](https://hbr.org/2017/11/are-you-suited-for-a-start-up) is baked into the research agent: every coffee chat comes with a personalized market insight prepared in advance.

---

## Author

**Nicolás Mayne-Nicholls** · HBS MBA 2027 · [LinkedIn](https://linkedin.com/in/YOUR_HANDLE)

*Previously: Founded Connect Car @ COPEC · PM @ Kavak · Industrial Engineer (PUC Chile)*
