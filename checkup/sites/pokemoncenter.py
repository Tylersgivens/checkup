"""Pokémon Center detectors.

Pokémon Center puts a Queue-it virtual waiting room in front of the store just
before a big drop (it began in early 2025). When the queue is on, a normal
visit gets redirected to a *.queue-it.net URL instead of loading the store.
That redirect is the earliest reliable public signal, so check_queue watches
for it.

Other signals we record, because any change in them is worth looking at:
  * queue_connector   – Queue-it's JS connector showing up in the page. It can
                        be loaded before the waiting room is switched on.
  * queue_cookie      – Queue-it cookies (QueueITAccepted-*) set on the visit.
  * blocked           – Imperva/Incapsula or DataDome served a bot challenge instead of the
                        page. This is NOT a drop signal; it means we can't see
                        the page, and it's reported so it isn't mistaken for one.

check_product reads a single product page's availability.
"""

from __future__ import annotations

import json
import re

from checkup.fetch import Page

QUEUE_HOST_SUFFIX = "queue-it.net"

# Text found on queue / waiting-room pages (Queue-it and Imperva's waiting room).
WAITING_ROOM_TEXT = re.compile(
    r"you are (now )?in line|waiting room|your (estimated )?wait time|"
    r"number of users in line ahead of you|queue ?id",
    re.I,
)
# Imperva bot-challenge / block pages.
BLOCK_TEXT = re.compile(
    r"Incapsula incident ID|Request unsuccessful|_Incapsula_Resource|"
    r"Pardon Our Interruption|verify you are (a )?human|captcha-delivery\.com",
    re.I,
)
QUEUE_CONNECTOR = re.compile(r"queue-it\.net|queueclient(\.min)?\.js|queueconfigloader", re.I)
SCRIPT_SRC = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)


def _script_hosts(html: str) -> list[str]:
    hosts = set()
    for src in SCRIPT_SRC.findall(html):
        m = re.match(r"(?:https?:)?//([^/]+)", src)
        if m:
            hosts.add(m.group(1).lower())
    return sorted(hosts)


def classify_queue(page: Page) -> dict:
    on_queue_host = any(h.endswith(QUEUE_HOST_SUFFIX) for h in page.hosts_visited)
    waiting_text = bool(WAITING_ROOM_TEXT.search(page.html))
    blocked = bool(BLOCK_TEXT.search(page.html)) or page.status in (403, 429)
    queue_cookie = any(c.lower().startswith("queueit") for c in page.cookies)

    if on_queue_host or (waiting_text and not blocked):
        state = "QUEUE_LIVE"
    elif blocked:
        state = "BLOCKED"
    elif 200 <= page.status < 400:
        state = "NORMAL"
    else:
        state = f"HTTP_{page.status}"

    return {
        "state": state,
        "final_url": page.final_url,
        "queue_connector": bool(QUEUE_CONNECTOR.search(page.html)),
        "queue_cookie": queue_cookie,
        "script_hosts": _script_hosts(page.html),
    }


def check_queue(fetcher, target: dict) -> dict:
    return classify_queue(fetcher.get(target.get("url", "https://www.pokemoncenter.com/")))


# --- product pages ---------------------------------------------------------

SCHEMA_AVAILABILITY = re.compile(r'"availability"\s*:\s*"(?:https?://schema\.org/)?(\w+)"', re.I)
LD_JSON = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)

# Visible button / label text, most specific first.
BUTTON_STATES = [
    ("IN_STOCK", re.compile(r">\s*add to (cart|bag)\s*<", re.I)),
    ("SOLD_OUT", re.compile(r">\s*(sold out|out of stock|currently unavailable)\s*<", re.I)),
    ("COMING_SOON", re.compile(r">\s*(coming soon|notify me|available soon)\s*<", re.I)),
]

SCHEMA_TO_STATE = {
    "instock": "IN_STOCK",
    "limitedavailability": "IN_STOCK",
    "onlineonly": "IN_STOCK",
    "preorder": "PREORDER",
    "presale": "PREORDER",
    "outofstock": "SOLD_OUT",
    "soldout": "SOLD_OUT",
    "discontinued": "SOLD_OUT",
}


def _schema_availability(html: str) -> str | None:
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        m = SCHEMA_AVAILABILITY.search(json.dumps(data))
        if m:
            return m.group(1)
    m = SCHEMA_AVAILABILITY.search(html)
    return m.group(1) if m else None


def classify_product(page: Page) -> dict:
    queue = classify_queue(page)
    if queue["state"] in ("QUEUE_LIVE", "BLOCKED"):
        return {"state": queue["state"], "schema": None, "button": None}

    schema = _schema_availability(page.html)
    button = next((name for name, rx in BUTTON_STATES if rx.search(page.html)), None)
    # The visible button is what a shopper can act on, so it wins over schema data.
    state = button or SCHEMA_TO_STATE.get((schema or "").lower()) or "UNKNOWN"
    if page.status == 404:
        state = "NOT_FOUND"
    return {"state": state, "schema": schema, "button": button}


def check_product(fetcher, target: dict) -> dict:
    return classify_product(fetcher.get(target["url"]))
