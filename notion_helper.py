"""
notion_helper.py — Shared Notion API wrapper (notion-client v3)
Used by all agents. Handles create, update, query with rate limiting.

In notion-client v3:
  - Querying rows  → client.data_sources.query(data_source_id)
  - Creating pages → client.pages.create(parent={"data_source_id": ...})
  - Creating DBs   → client.databases.create(...)
"""

import os
import time
from typing import Any, Optional
from dotenv import load_dotenv
from notion_client import Client
from notion_client.errors import APIResponseError
from rich.console import Console

load_dotenv()
console = Console()

# Notion enforces 3 req/sec; stay well under that
RATE_LIMIT_DELAY = 0.4  # seconds between requests


class NotionHelper:
    def __init__(self):
        api_key = os.getenv("NOTION_API_KEY")
        if not api_key:
            raise ValueError("NOTION_API_KEY not set in .env")
        self.client = Client(auth=api_key)
        self._last_request_time = 0.0

    # ── Rate limiter ──────────────────────────────────────────────────────────

    def _wait(self):
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.monotonic()

    def _call(self, fn, *args, retries: int = 3, **kwargs) -> Any:
        """Call a Notion API function with exponential-backoff retry."""
        for attempt in range(retries):
            self._wait()
            try:
                return fn(*args, **kwargs)
            except APIResponseError as e:
                if e.status in (429, 503) or e.status >= 500:
                    wait = 2 ** attempt
                    console.print(f"[yellow]Notion {e.status} — retrying in {wait}s[/yellow]")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError(f"Notion API call failed after {retries} retries")

    # ── Database creation (v3: databases.create) ──────────────────────────────

    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: dict,
    ) -> dict:
        """Create a Notion database under a page. Returns the raw API result."""
        result = self._call(
            self.client.databases.create,
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": title}}],
            initial_data_source={"properties": properties},
        )
        return result

    # ── Database query (databases.query) ──────────────────────────────────────

    def query_database(
        self,
        data_source_id: str,
        filter_: Optional[dict] = None,
        sorts: Optional[list] = None,
        page_size: int = 100,
    ) -> list[dict]:
        """Return ALL pages from a database, handling pagination."""
        pages: list[dict] = []
        cursor: Optional[str] = None

        while True:
            kwargs: dict = {
                "database_id": data_source_id,
                "page_size": page_size,
            }
            if filter_:
                kwargs["filter"] = filter_
            if sorts:
                kwargs["sorts"] = sorts
            if cursor:
                kwargs["start_cursor"] = cursor

            result = self._call(
                self.client.databases.query,
                **kwargs,
            )
            pages.extend(result.get("results", []))

            if not result.get("has_more"):
                break
            cursor = result.get("next_cursor")

        return pages

    # ── Page CRUD ─────────────────────────────────────────────────────────────

    def create_page(self, data_source_id: str, properties: dict) -> dict:
        """Create a new page (row) in a database."""
        result = self._call(
            self.client.pages.create,
            parent={"database_id": data_source_id},
            properties=properties,
        )
        return result

    def update_page(self, page_id: str, properties: dict) -> dict:
        """Update properties on an existing page."""
        result = self._call(
            self.client.pages.update,
            page_id=page_id,
            properties=properties,
        )
        return result

    def get_page(self, page_id: str) -> dict:
        """Retrieve a single page by ID."""
        return self._call(self.client.pages.retrieve, page_id=page_id)

    # ── Convenience helpers ───────────────────────────────────────────────────

    def get_all_titles(self, data_source_id: str) -> dict[str, str]:
        """Return {lowercase_name: page_id} for all pages in a data source."""
        pages = self.query_database(data_source_id)
        result = {}
        for page in pages:
            props = page.get("properties", {})
            title_prop = props.get("Name") or props.get("Title")
            if not title_prop:
                continue
            rich = title_prop.get("title", [])
            if rich:
                name = rich[0].get("plain_text", "")
                result[name.lower()] = page["id"]
        return result

    # ── Property builders ─────────────────────────────────────────────────────

    @staticmethod
    def title(text: str) -> dict:
        return {"title": [{"text": {"content": str(text)[:2000]}}]}

    @staticmethod
    def rich_text(text: str) -> dict:
        return {"rich_text": [{"text": {"content": str(text)[:2000]}}]}

    @staticmethod
    def number(value) -> dict:
        import math
        try:
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return {"number": None}
            return {"number": f}
        except (TypeError, ValueError):
            return {"number": None}

    @staticmethod
    def select(option: str) -> dict:
        return {"select": {"name": str(option)}}

    @staticmethod
    def multi_select(options: list[str]) -> dict:
        return {"multi_select": [{"name": o} for o in options]}

    @staticmethod
    def url(link: str) -> dict:
        if not link or not str(link).strip():
            return {"url": None}
        link = str(link).strip()
        if not link.startswith(("http://", "https://")):
            link = "https://" + link
        return {"url": link}

    @staticmethod
    def checkbox(value: bool) -> dict:
        return {"checkbox": bool(value)}

    @staticmethod
    def date(iso_string: Optional[str]) -> dict:
        if not iso_string:
            return {"date": None}
        return {"date": {"start": iso_string}}

    @staticmethod
    def email_prop(address: str) -> dict:
        return {"email": str(address) if address else None}

    @staticmethod
    def relation(page_ids: list[str]) -> dict:
        return {"relation": [{"id": pid} for pid in page_ids]}
