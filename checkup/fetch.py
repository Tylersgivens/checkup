"""Fetchers return a Page: everything a detector might need from one request."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


@dataclass
class Page:
    url: str                      # URL we asked for
    final_url: str                # URL we ended up on after redirects
    status: int
    html: str
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[str] = field(default_factory=list)       # cookie names only
    redirect_chain: list[str] = field(default_factory=list)

    @property
    def hosts_visited(self) -> list[str]:
        return [urlparse(u).hostname or "" for u in self.redirect_chain + [self.final_url]]


class HttpFetcher:
    """Plain HTTP. Fast and cheap, but Imperva may serve a challenge page instead."""

    def __init__(self, timeout: float = 15):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.timeout = timeout

    def get(self, url: str) -> Page:
        r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        return Page(
            url=url,
            final_url=r.url,
            status=r.status_code,
            html=r.text,
            headers={k.lower(): v for k, v in r.headers.items()},
            cookies=sorted({c.name for c in self.session.cookies}),
            redirect_chain=[h.headers.get("location") or h.url for h in r.history],
        )

    def close(self) -> None:
        self.session.close()


class BrowserFetcher:
    """Real Chromium via Playwright. Slower, but renders what a shopper actually sees."""

    def __init__(self, headless: bool = True, timeout: float = 30):
        from playwright.sync_api import sync_playwright  # optional dependency

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._context = self._browser.new_context(user_agent=USER_AGENT, locale="en-US")
        self.timeout_ms = int(timeout * 1000)

    def get(self, url: str) -> Page:
        page = self._context.new_page()
        chain: list[str] = []
        page.on("framenavigated", lambda f: f == page.main_frame and chain.append(f.url))
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(2500)  # let client-side redirects (e.g. Queue-it) fire
            return Page(
                url=url,
                final_url=page.url,
                status=resp.status if resp else 0,
                html=page.content(),
                headers={k.lower(): v for k, v in (resp.headers if resp else {}).items()},
                cookies=sorted({c["name"] for c in self._context.cookies()}),
                redirect_chain=[u for u in chain[:-1] if u != "about:blank"],
            )
        finally:
            page.close()

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()


def make_fetcher(kind: str):
    if kind == "browser":
        return BrowserFetcher()
    return HttpFetcher()
