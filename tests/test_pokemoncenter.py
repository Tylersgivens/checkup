from checkup.fetch import Page
from checkup.monitor import Monitor
from checkup.sites import pokemoncenter as pc
from checkup import notify

HOME = "https://www.pokemoncenter.com/"

NORMAL_HOME = """<html><head><title>Pokémon Center</title>
<script src="https://www.pokemoncenter.com/static/app.js"></script></head>
<body><h1>Shop</h1></body></html>"""

HOME_WITH_CONNECTOR = NORMAL_HOME.replace(
    "</head>", '<script src="//static.queue-it.net/script/queueclient.min.js"></script></head>')

QUEUE_PAGE = """<html><head><title>Queue-it</title></head><body>
<h1>You are now in line.</h1><p>Number of users in line ahead of you: 48213</p></body></html>"""

IMPERVA_BLOCK = """<html><head><META NAME="robots" CONTENT="noindex,nofollow">
<script src="/_Incapsula_Resource?SWJIYLWA=5074a744e2e3d891814e9a2dace20bd4"></script></head>
<body>Request unsuccessful. Incapsula incident ID: 123-456</body></html>"""


def page(html, final_url=HOME, status=200, chain=(), cookies=()):
    return Page(url=HOME, final_url=final_url, status=status, html=html,
                redirect_chain=list(chain), cookies=list(cookies))


def product_page(button=None, availability=None):
    ld = ("" if availability is None else
          '<script type="application/ld+json">{"@type":"Product","offers":'
          f'{{"availability":"https://schema.org/{availability}"}}}}</script>')
    btn = "" if button is None else f"<button>{button}</button>"
    return page(f"<html><head>{ld}</head><body>{btn}</body></html>")


def test_normal_homepage():
    s = pc.classify_queue(page(NORMAL_HOME))
    assert s["state"] == "NORMAL"
    assert s["queue_connector"] is False


def test_connector_present_but_queue_not_live():
    s = pc.classify_queue(page(HOME_WITH_CONNECTOR))
    assert s["state"] == "NORMAL"
    assert s["queue_connector"] is True
    assert "static.queue-it.net" in s["script_hosts"]


def test_redirect_to_queue_it_is_live():
    url = "https://pokemon.queue-it.net/?c=pokemon&e=drop123&t=https%3A%2F%2Fwww.pokemoncenter.com%2F"
    s = pc.classify_queue(page(QUEUE_PAGE, final_url=url, chain=[HOME]))
    assert s["state"] == "QUEUE_LIVE"


def test_waiting_room_text_without_redirect_is_live():
    assert pc.classify_queue(page(QUEUE_PAGE))["state"] == "QUEUE_LIVE"


def test_queue_cookie_detected():
    s = pc.classify_queue(page(NORMAL_HOME, cookies=["QueueITAccepted-SDFrts345E-V3_drop123"]))
    assert s["queue_cookie"] is True


def test_imperva_block_is_not_a_drop():
    assert pc.classify_queue(page(IMPERVA_BLOCK))["state"] == "BLOCKED"
    assert pc.classify_queue(page("", status=403))["state"] == "BLOCKED"


def test_product_states():
    assert pc.classify_product(product_page("Add to Cart", "InStock"))["state"] == "IN_STOCK"
    assert pc.classify_product(product_page("Sold Out", "OutOfStock"))["state"] == "SOLD_OUT"
    assert pc.classify_product(product_page("Coming Soon"))["state"] == "COMING_SOON"
    assert pc.classify_product(product_page(availability="PreOrder"))["state"] == "PREORDER"
    assert pc.classify_product(product_page())["state"] == "UNKNOWN"


def test_button_beats_stale_schema():
    s = pc.classify_product(product_page("Add to Cart", "OutOfStock"))
    assert s["state"] == "IN_STOCK"
    assert s["schema"] == "OutOfStock"


def test_product_behind_queue():
    assert pc.classify_product(page(QUEUE_PAGE))["state"] == "QUEUE_LIVE"


class FakeFetcher:
    def __init__(self, pages):
        self.pages = list(pages)
        self.last_page = None

    def get(self, url):
        self.last_page = self.pages.pop(0)
        return self.last_page

    def close(self):
        pass


def test_monitor_alerts_on_transitions(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "CHANNELS", [lambda t, b, u: sent.append(t)])
    target = {"name": "pc", "type": "pokemoncenter.queue", "url": HOME,
              "alert_on": ["QUEUE_LIVE"], "heads_up_on": ["queue_connector"]}
    m = Monitor({"targets": [target]}, state_dir=tmp_path / "s", snapshot_dir=tmp_path / "snap")
    m.fetchers["http"] = FakeFetcher([
        page(NORMAL_HOME),            # baseline: no alert
        page(NORMAL_HOME),            # unchanged: no alert
        page(HOME_WITH_CONNECTOR),    # connector appears: heads-up
        page(IMPERVA_BLOCK),          # blocked: ignored, no false alarm
        page(QUEUE_PAGE),             # queue live: alert
    ])
    for _ in range(5):
        m.check(target)

    assert sent == ["pc: something changed", "pc: QUEUE_LIVE"]
    assert len(list((tmp_path / "snap").iterdir())) == 2
