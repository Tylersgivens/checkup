"""CLI.

  python -m checkup run [-c config.yaml]          start monitoring
  python -m checkup browser                        open the saved browser profile to pass a human check
  python -m checkup inspect URL [--type T] [--browser] [--save FILE]
                                                   fetch once and print every signal
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import yaml

from checkup.fetch import make_fetcher
from checkup.monitor import Monitor, RecordingFetcher
from checkup.sites import CHECKS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="checkup")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="monitor the targets in a config file")
    run.add_argument("-c", "--config", default="config.yaml")

    ins = sub.add_parser("inspect", help="fetch one URL and print what the detectors see")
    ins.add_argument("url")
    ins.add_argument("--type", default="pokemoncenter.queue", choices=sorted(CHECKS))
    ins.add_argument("--browser", action="store_true", help="use a real browser (Playwright)")
    ins.add_argument("--save", help="also write the raw HTML to this file")

    sub.add_parser("browser", help="open the monitor's browser so you can pass a human check")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "run":
        with open(args.config) as f:
            Monitor(yaml.safe_load(f)).run_forever()
        return 0

    if args.cmd == "browser":
        fetcher = make_fetcher("browser")
        try:
            fetcher.open_for_user("https://www.pokemoncenter.com/")
        finally:
            fetcher.close()
        return 0

    fetcher = RecordingFetcher(make_fetcher("browser" if args.browser else "http"))
    try:
        signals = CHECKS[args.type](fetcher, {"url": args.url})
        page = fetcher.last_page
        print(json.dumps({
            "status": page.status,
            "final_url": page.final_url,
            "redirect_chain": page.redirect_chain,
            "cookies": page.cookies,
            "signals": signals,
        }, indent=2))
        if args.save:
            with open(args.save, "w") as f:
                f.write(page.html)
    finally:
        fetcher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
