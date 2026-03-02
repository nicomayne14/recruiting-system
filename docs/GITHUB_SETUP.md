# GitHub Setup Guide

## Step 1 — Create the repo on GitHub

1. Go to github.com → New repository
2. Name: `recruiting-system`
3. Set to **Public** (this is a portfolio piece)
4. Do NOT initialize with README (you already have one)
5. Click Create repository

## Step 2 — Initialize git locally

Open your terminal, navigate to this folder, and run:

```bash
cd path/to/recruiting-system

git init
git add .
git commit -m "feat: initial system architecture and project scaffold

- Full agent architecture for AI-powered recruiting pipeline
- Notion CRM schema (Companies, Contacts, Interactions, Applications)
- Streamlit KPI dashboard spec
- 6 agents: filter, research_contacts, research_company, draft_outreach,
  parse_applications, check_followups
- Demo mode with sample data
- .gitignore protecting all credentials and personal data"

git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/recruiting-system.git
git push -u origin main
```

## Step 3 — Pin it on your GitHub profile

1. Go to your GitHub profile page
2. Click "Customize your pins"
3. Pin `recruiting-system`

This makes it the first repo recruiters see.

## Step 4 — Add the GitHub link to your LinkedIn

In LinkedIn → Featured section → Add link → paste the GitHub repo URL.
Title it: "Built an AI recruiting system to run systematic startup outreach"

## What NOT to commit (already in .gitignore)

- `.env` — your API keys
- `token.json` — Gmail OAuth token
- `data/bussgang_*.csv` — the raw startup lists (Bussgang's proprietary data)
- `data/existing_targets/` — your personal research files
- `templates/pitches/` — your personal pitch copy

The sample data in `data/sample/` IS committed and gives recruiters something to run.

## Keeping the repo clean as you build

- Commit often with descriptive messages (they show up in the activity graph)
- Use branches for each agent: `git checkout -b agent/research-contacts`
- Merge to main when the agent works end-to-end
- The commit history itself is part of the portfolio signal

## Suggested commit message format

```
feat: implement research_contacts agent with Playwright

- HBS alumni directory search with Playwright + async
- LinkedIn search fallback with anti-detection delays
- Pushes contacts to Notion with tier classification
- 2nd-time founder detection via profile history scan
```
