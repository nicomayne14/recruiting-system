"""
save_hbs_session.py — One-time manual login to save HBS session cookies.

Run this whenever your session expires (typically every 30-90 days).
It opens a real browser window, you log in + complete MFA normally,
then it saves your session so all agents can reuse it without logging in again.

Usage:
    python save_hbs_session.py
"""

import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()

SESSION_FILE = Path(__file__).parent / "hbs_session.json"
HBS_URL      = "https://www.alumni.hbs.edu"


def main():
    console.print(Panel.fit(
        "[bold blue]HBS Session Saver[/bold blue]\n"
        "A browser window will open. Log in with your HBS credentials\n"
        "and complete MFA as normal. Come back here when you're done.",
        border_style="blue",
    ))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,    # must be visible so you can log in + do MFA
            args=["--no-sandbox"],
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

        console.print("\n[bold]Opening HBS alumni portal…[/bold]")
        page.goto(HBS_URL, wait_until="domcontentloaded", timeout=30000)

        console.print(
            "\n[bold yellow]→ In the browser window:[/bold yellow]\n"
            "  1. Click [bold]Sign In[/bold] (top right of the page)\n"
            "  2. Enter your HBS email and password\n"
            "  3. Complete MFA (phone/Duo)\n"
            "  4. Wait until you can see the [bold]Alumni Directory[/bold] page\n"
        )

        input("  Once you can see the Alumni Directory, press [Enter] here to save your session...")
        print()

        # Save the full browser storage state (cookies + localStorage)
        ctx.storage_state(path=str(SESSION_FILE))
        console.print(
            f"\n[green]✓ Session saved to {SESSION_FILE.name}[/green]\n"
            f"[dim]All agents will now load this session automatically.\n"
            f"Re-run this script when your session expires (usually every 30-90 days).[/dim]"
        )
        browser.close()


if __name__ == "__main__":
    main()
