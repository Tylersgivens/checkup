"""Alert channels. Each takes (title, body, url) and should never raise."""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)


def console(title: str, body: str, url: str | None) -> None:
    print(f"\a\n*** {title} ***\n{body}\n{url or ''}\n", flush=True)


def discord(title: str, body: str, url: str | None) -> None:
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not hook:
        return
    payload = {"content": f"**{title}**\n{body}\n{url or ''}"}
    try:
        requests.post(hook, json=payload, timeout=10).raise_for_status()
    except requests.RequestException as e:
        log.warning("discord alert failed: %s", e)


def ntfy(title: str, body: str, url: str | None) -> None:
    """Phone push via ntfy.sh — install the ntfy app and subscribe to your topic."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    headers = {"Title": title.encode("utf-8"), "Priority": "urgent"}
    if url:
        headers["Click"] = url
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                      headers=headers, timeout=10).raise_for_status()
    except requests.RequestException as e:
        log.warning("ntfy alert failed: %s", e)


CHANNELS = [console, discord, ntfy]


def send(title: str, body: str, url: str | None = None) -> None:
    for channel in CHANNELS:
        channel(title, body, url)
