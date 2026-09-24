"""Polling loop: run each target's check, compare with last result, alert on changes."""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from checkup import notify
from checkup.fetch import make_fetcher
from checkup.sites import CHECKS

log = logging.getLogger(__name__)

BLIND_AFTER = 5  # consecutive BLOCKED/errored checks before we warn that the monitor can't see


class RecordingFetcher:
    """Wraps a fetcher and remembers the last page, so we can snapshot it."""

    def __init__(self, inner):
        self.inner = inner
        self.last_page = None

    def get(self, url):
        self.last_page = self.inner.get(url)
        return self.last_page

    def close(self):
        self.inner.close()


class Monitor:
    def __init__(self, config: dict, state_dir: str = "state", snapshot_dir: str = "snapshots"):
        self.config = config
        self.state_path = Path(state_dir) / "state.json"
        self.snapshot_dir = Path(snapshot_dir)
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.fetchers: dict[str, RecordingFetcher] = {}
        self.next_run: dict[str, float] = {}

    def _fetcher(self, kind: str) -> RecordingFetcher:
        if kind not in self.fetchers:
            self.fetchers[kind] = RecordingFetcher(make_fetcher(kind))
        return self.fetchers[kind]

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def _snapshot(self, name: str, fetcher: RecordingFetcher) -> Path | None:
        page = fetcher.last_page
        if page is None:
            return None
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safe = re.sub(r"[^\w.-]+", "_", name)
        path = self.snapshot_dir / f"{safe}-{stamp}.html"
        path.write_text(f"<!-- {page.url} -> {page.final_url} status={page.status} "
                        f"cookies={page.cookies} -->\n{page.html}")
        return path

    def check(self, target: dict) -> None:
        name = target["name"]
        fetcher = self._fetcher(target.get("fetcher", "http"))
        prev = self.state.get(name, {})
        try:
            signals = CHECKS[target["type"]](fetcher, target)
        except Exception as e:  # network errors etc. shouldn't kill the loop
            log.warning("%s: check failed: %s", name, e)
            signals = {"state": "ERROR", "error": str(e)}

        prev_signals = prev.get("signals", {})
        changed = {k: (prev_signals.get(k), v) for k, v in signals.items()
                   if k != "error" and prev_signals.get(k) != v}
        log.info("%s: %s%s", name, signals["state"], f" changed={list(changed)}" if changed else "")

        # Track blindness separately so a flaky/blocked check doesn't look like a state change.
        blind = signals["state"] in ("BLOCKED", "ERROR")
        streak = prev.get("blind_streak", 0) + 1 if blind else 0
        if streak == BLIND_AFTER:
            notify.send(f"checkup can't see {name}",
                        f"{BLIND_AFTER} checks in a row returned {signals['state']}. "
                        "Try fetcher: browser, or slow the interval down.", target.get("url"))
        if blind and prev_signals:
            # Keep the last good reading so we alert on real transitions once we can see again.
            self.state[name] = {**prev, "blind_streak": streak}
            self._save_state()
            return

        if changed and prev_signals:
            snap = self._snapshot(name, fetcher)
            alert_states = target.get("alert_on", [])
            if "state" in changed and signals["state"] in alert_states:
                notify.send(f"{name}: {signals['state']}",
                            f"was {changed['state'][0]}", signals.get("final_url") or target.get("url"))
                # The main alert already fired; a heads-up about side details is just noise.
                changed = {}
            watched = [k for k in target.get("heads_up_on", []) if k in changed]
            if watched:
                lines = [f"{k}: {changed[k][0]} -> {changed[k][1]}" for k in watched]
                notify.send(f"{name}: something changed", "\n".join(lines) + f"\nsnapshot: {snap}",
                            target.get("url"))

        self.state[name] = {
            "signals": signals,
            "blind_streak": streak,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()

    def run_forever(self) -> None:
        default_interval = self.config.get("interval_seconds", 60)
        try:
            while True:
                now = time.monotonic()
                for target in self.config["targets"]:
                    if now < self.next_run.get(target["name"], 0):
                        continue
                    self.check(target)
                    interval = target.get("interval_seconds", default_interval)
                    # Jitter so requests don't land on an exact, bot-looking cadence.
                    self.next_run[target["name"]] = time.monotonic() + interval * random.uniform(0.85, 1.15)
                time.sleep(1)
        finally:
            for f in self.fetchers.values():
                f.close()
