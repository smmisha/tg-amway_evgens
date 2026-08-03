"""Probe: check DataDome behavior from a GitHub Actions runner IP.

The site (amway.ua) is protected by DataDome. On a home IP the only working
approach is a REAL browser in headful mode with a valid datadome cookie.
This probe answers one question: how does DataDome treat a datacenter IP
(GitHub Actions runner) with a fresh profile and no cookies?

Verdicts (printed as VERDICT: ...):
  NO-CAPTCHA                 content loads without any challenge
  JS-CHALLENGE-AUTOSOLVED    challenge passes itself, no interaction needed
  INTERACTIVE-CAPTCHA        human must solve a captcha -> not viable
  BLOCKED                    challenge page persists, no content
Run headful under xvfb:  xvfb-run -a python scripts/probe_datadome.py
"""

import asyncio
import sys
import time

import httpx
from playwright.async_api import async_playwright

BASE_URL = "https://www.amway.ua/uk/"
SCAN_SECONDS = 120
CHECK_INTERVAL = 5

LINK_SELECTOR = "a[href*='/p/'], a[href*='/c/'], a[href*='/article']"


async def get_ip() -> str:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            return (await client.get("https://api.ipify.org")).text
    except Exception as e:
        return f"ipify failed: {e}"


async def main() -> None:
    print(f"[probe] start, runner IP: {await get_ip()}", flush=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            "/tmp/probe_profile",
            headless=False,
            viewport={"width": 1366, "height": 900},
            locale="uk-UA",
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)

        verdict = "UNKNOWN"
        deadline = time.monotonic() + SCAN_SECONDS
        i = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(CHECK_INTERVAL)
            i += 1
            captcha = await page.eval_on_selector_all(
                "iframe[src*='captcha'], #datadome", "els => els.length"
            )
            links = await page.eval_on_selector_all(LINK_SELECTOR, "els => els.length")
            url = page.url
            title = (await page.title() or "").strip()
            print(
                f"[{i * CHECK_INTERVAL}s] url={url[:70]} title={title[:50]!r} "
                f"captcha={captcha} links={links}",
                flush=True,
            )

            if links >= 5:
                verdict = f"NO-CAPTCHA: content loads, links={links}"
                break

            if captcha == 0 and links == 0 and "captcha" not in url.lower():
                # No captcha element, no content: maybe content needs scroll,
                # or a JS challenge is silently in progress.
                if i >= 2:
                    for _ in range(15):
                        await page.mouse.wheel(0, 600)
                        await asyncio.sleep(0.5)
                    links = await page.eval_on_selector_all(LINK_SELECTOR, "els => els.length")
                    if links >= 5:
                        verdict = f"JS-CHALLENGE-AUTOSOLVED: links after scroll={links}"
                    else:
                        verdict = f"BLOCKED: no captcha element but no content (links={links})"
                    break

        if verdict == "UNKNOWN":
            captcha = await page.eval_on_selector_all(
                "iframe[src*='captcha'], #datadome", "els => els.length"
            )
            verdict = (
                f"INTERACTIVE-CAPTCHA: still showing after {SCAN_SECONDS}s"
                if captcha
                else "UNKNOWN: neither captcha nor content"
            )

        print(f"VERDICT: {verdict}", flush=True)
        await context.close()
        sys.exit(0 if verdict.startswith(("NO-CAPTCHA", "JS-CHALLENGE")) else 1)


asyncio.run(main())
