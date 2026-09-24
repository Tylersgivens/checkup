# checkup

Watches retail sites for signals that come right before a restock, and alerts you.

## Pokémon Center: what we watch

| Signal | What it means | Alert |
|---|---|---|
| **Queue-it waiting room** (`state: QUEUE_LIVE`) | Pokémon Center has used a Queue-it virtual queue since early 2025. It switches on just before a big drop, and visitors get redirected to `*.queue-it.net`. This is the earliest reliable public signal. | Urgent |
| `queue_connector` | Queue-it's JavaScript shows up in the store's page. It may be loaded before the queue opens. | Heads-up |
| `queue_cookie` | Queue-it cookies (`QueueITAccepted-*`) set on a normal visit | Heads-up |
| `script_hosts` | The set of third-party script hosts changed (a new vendor was loaded) | Heads-up |
| Product `state` | `IN_STOCK` / `PREORDER` / `SOLD_OUT` / `COMING_SOON`, read from the page's Add-to-Cart button and its schema.org data | Urgent |
| `BLOCKED` | Imperva or DataDome (the site's bot protection) served a challenge page. This is **not** a drop, only a sign that we can't see the page. | Only if it lasts 5 checks |

Every time a signal changes, the raw HTML is saved to `snapshots/`, so you can
diff before and after a real drop and find new tells to add.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml

# optional alert channels
export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
export NTFY_TOPIC=some-long-random-topic-name   # then subscribe to it in the ntfy phone app
```

Pokémon Center blocks plain scripted requests (DataDome returns a 403), so the
monitor drives a real, visible Chrome window with its own saved profile:

```bash
playwright install chromium     # only used if Google Chrome isn't installed
python -m checkup browser       # pass any "prove you're human" check once, then press Enter
python -m checkup inspect https://www.pokemoncenter.com/ --browser --save home.html
python -m checkup run           # leave the Chrome window it opens alone
```

## Notes

- Keep the polling polite (30–90s). Hammering the site gets your IP blocked,
  and then you see nothing at all.
- This tool only **alerts** you. It doesn't join the queue or check out for you;
  you still buy in your own browser.
- Tests: `pip install pytest && python -m pytest`

## Adding another site

Add `checkup/sites/<site>.py` with functions that take `(fetcher, target)` and return a dict
that includes `state`, then register them in `checkup/sites/__init__.py`.
