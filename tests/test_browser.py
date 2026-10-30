"""Real-browser tests against a local server. Skipped when no Chromium/Chrome is available."""
import http.server
import json
import os
import sys
import threading
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from valuator.browser import BrowserService  # noqa: E402
from valuator.capture import capture  # noqa: E402
from valuator.models import Item  # noqa: E402
from valuator.sources import pricecharting  # noqa: E402

PAGES = {
    "/js": "<html><head><title>JS</title></head><body><div id=x>loading</div>"
           "<script>setTimeout(()=>{document.getElementById('x').innerHTML='<span id=done>Pop 512</span>'},300)"
           "</script></body></html>",
    "/challenge": "<html><head><title>Just a moment...</title></head><body>Checking your browser"
                  "<script>setTimeout(()=>{document.title='Sales';document.body.innerHTML="
                  "'<table id=t><tr><td>ok</td></tr></table>'},1500)</script></body></html>",
    "/origin": "<html><body>origin</body></html>",
}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], "<html>404</html>").encode()
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n).decode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        if self.path == "/popapi":
            self.wfile.write(json.dumps({"CertNumber": "81234567", "TotalPopulation": 1287,
                                         "PopulationHigher": 121}).encode())
            return
        self.wfile.write(json.dumps({"echo": data, "ctype": self.headers.get("Content-Type")}).encode())


def _have_browser():
    return bool(os.environ.get("PLAYWRIGHT_BROWSERS_PATH")) or os.environ.get("LSV_BROWSER")


pytestmark = pytest.mark.skipif(not _have_browser(), reason="no browser available")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ.setdefault("LSV_BROWSER", "chromium")
    svc = BrowserService(tmp_path_factory.mktemp("prof"), headless=True)
    svc.ensure_started()
    yield svc, f"http://127.0.0.1:{srv.server_address[1]}"
    svc.close()
    srv.shutdown()


def test_renders_javascript(env):
    svc, base = env
    html = svc.get_html(base + "/js", wait_selector="#done")
    assert "Pop 512" in html


def test_waits_out_bot_check(env):
    svc, base = env
    seen = []
    svc.on_attention = seen.append
    html = svc.get_html(base + "/challenge", wait_selector="#t")
    assert "<table" in html and seen and "human check" in seen[0]


def test_fetch_from_page_origin(env):
    svc, base = env
    out = svc.fetch(base + "/origin", base + "/api", "POST", {"a": 1})
    assert json.loads(out["echo"]) == {"a": 1} and out["ctype"] == "application/json"
    txt = svc.fetch(base + "/origin", base + "/api", "POST", "query=x", {"Content-Type":
                    "application/x-www-form-urlencoded"}, as_json=False)
    assert "query=x" in txt


PC_PAGE = """<html><head><link rel="canonical" href="https://www.pricecharting.com/game/pokemon-base-set/charizard-4"></head>
<body><h1 id="product_name">Charizard #4 Pokemon Base Set</h1>
<table id="price_data"><tr><th>Ungraded</th><th>Grade 7</th><th>Grade 8</th><th>Grade 9</th><th>Grade 9.5</th><th>PSA 10</th></tr>
<tr><td>$1,054.05 +$26.30</td><td>$3,256.01</td><td>$6,237.50</td><td>$11,680.89</td><td>$12,849.00</td><td>$24,808.28</td></tr></table>
<table id="full-prices"><tr><td>CGC 10</td><td>$19,000.00</td></tr><tr><td>BGS 10</td><td>$30,000.00</td></tr></table>
<h3>Grade 9 Sold Listings (2)</h3>
<table class="hoverable-rows"><tr><th>Sale Date</th><th>TW</th><th>Title</th><th>Price</th></tr>
<tr><td>2026-10-20</td><td></td><td><a href="/offer/1">Pokemon Charizard 4/102 Base Set Holo PSA 9 MINT</a></td><td>$11,500.00</td></tr>
<tr><td>2026-10-11</td><td></td><td><a href="/offer/2">Charizard 4/102 Base Set CGC 9</a></td><td>$8,000.00</td></tr>
<tr><td>2026-10-02</td><td><img alt="Goldin"></td><td>Charizard Base Set 4/102 PSA 9</td><td>$11,900.00 Report It</td></tr>
</table></body></html>"""


def test_pricecharting_page_parse():
    psa9 = Item(name="Charizard", number="4/102", set_name="Base Set", graded=True, grader="PSA", grade="9")
    r = pricecharting.parse_page(PC_PAGE, psa9, "u")
    guide = [c for c in r.comps if c.kind == "guide"]
    sales = [c for c in r.comps if c.kind == "sale"]
    assert guide[0].price == 11680.89
    assert [s.price for s in sales] == [11500.0, 11900.0]        # CGC 9 filtered out
    assert sales[1].note == "Sold on Goldin" and sales[0].sale_date == date(2026, 10, 20)
    cgc10 = Item(name="Charizard", number="4/102", graded=True, grader="CGC", grade="10")
    assert [c.price for c in pricecharting.parse_page(PC_PAGE, cgc10).comps if c.kind == "guide"] == [19000.0]
    raw = Item(name="Charizard", number="4/102")
    assert [c.price for c in pricecharting.parse_page(PC_PAGE, raw).comps if c.kind == "guide"] == [1054.05]


SEARCH = """<table id="games_table">
<tr><td class="title"><a href="/game/pokemon-base-set-2/charizard-4">Charizard #4</a></td><td>Pokemon Base Set 2</td></tr>
<tr><td class="title"><a href="/game/pokemon-base-set/charizard-1st-edition-4">Charizard [1st Edition] #4</a></td><td>Pokemon Base Set</td></tr>
<tr><td class="title"><a href="/game/pokemon-base-set/charizard-4">Charizard #4</a></td><td>Pokemon Base Set</td></tr>
</table>"""


def test_pricecharting_search_pick():
    it = Item(name="Charizard", number="4/102", set_name="Base Set")
    assert pricecharting.best_search_result(SEARCH, it).endswith("/game/pokemon-base-set/charizard-4")
    it.variant = "1st Edition"
    assert pricecharting.best_search_result(SEARCH, it).endswith("charizard-1st-edition-4")


CL_PAGE = """<html><body><nav>Card Ladder $99/mo</nav><div class="sales">
<div class="sale-row"><a href="/sale/1">2023 Pokemon Charizard ex 199/165 PSA 10</a><span>Oct 21, 2026</span><span>$1,250.00</span><span>eBay</span></div>
<div class="sale-row"><a href="/sale/2">2023 Pokemon Charizard ex 199/165 PSA 10 GEM MINT</a><span>10/03/2026</span><span>$1,190.50</span></div>
<div class="sale-row"><a href="/sale/3">2023 Pokemon Charizard ex 199/165 PSA 9</a><span>Oct 1, 2026</span><span>$600.00</span></div>
<div class="sale-row">Summary: average $1,200.00 and median $1,210.00 Oct 2026</div>
</div></body></html>"""


def test_capture_generic():
    it = Item(name="Charizard ex", number="199/165", graded=True, grader="PSA", grade="10")
    comps, skipped = capture(CL_PAGE, "https://app.cardladder.com/sales-history", it)
    assert [c.price for c in comps] == [1250.0, 1190.5]
    assert comps[0].source == "Card Ladder" and comps[0].manual and comps[0].url.endswith("/sale/1")
    assert skipped == 1
    assert comps[1].sale_date == date(2026, 10, 3)


PSA_RENDER = """<html><body><div>Cert Number</div><div>81234567</div><div>Item Grade</div><div>MINT 9</div>
<div>Year</div><div>1999</div><div>Brand/Title</div><div>POKEMON GAME</div><div>Subject</div><div>CHARIZARD-HOLO</div>
<div>Card Number</div><div>4</div><div>Variety/Pedigree</div><div>1ST EDITION</div>
<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"cert":{"CertNumber":"81234567",
"SpecID":554320,"Subject":"CHARIZARD-HOLO","TotalPopulation":1287,"PopulationHigher":121}}}}</script></body></html>"""


def test_psa_render_reads_embedded_pop():
    from valuator import certs
    info = certs.parse_psa_render({"html": PSA_RENDER, "text": "", "json": []}, "81234567")
    assert info.ok and info.name == "Charizard-Holo" and info.grade == "9" and info.variant == "1St Edition" or info.variant
    assert info.pop_total == 1287 and info.pop_higher == 121


def test_psa_render_reads_api_json_and_text():
    from valuator import certs
    html = PSA_RENDER.split("<script")[0] + "</body></html>"
    api = '{"PSACert":{"CertNumber":"81234567","TotalPopulation":"2,045","PopulationHigher":7}}'
    info = certs.parse_psa_render({"html": html, "text": "", "json": [api, '{"other":{"Population":5}}']}, "81234567")
    assert info.pop_total == 2045 and info.pop_higher == 7
    info = certs.parse_psa_render({"html": html, "text": "PSA Population 310\nPop Higher 4", "json": []}, "81234567")
    assert info.pop_total == 310 and info.pop_higher == 4


def test_open_and_read_collects_background_json(env):
    svc, base = env
    PAGES["/cert/81234567"] = (PSA_RENDER.split("<script")[0] +
        "<div id=pop>loading</div><script>fetch('/popapi',{method:'POST',body:'{}'}).then(r=>r.json())"
        ".then(j=>{document.getElementById('pop').textContent='Population '+j.TotalPopulation})</script></body></html>")
    data = svc.open_and_read(base + "/cert/81234567", r"Subject", wait_s=15, site="PSA")
    assert data["ready"] and data["json"], data
    from valuator import certs
    info = certs.parse_psa_render(data, "81234567")
    assert info.ok and info.name == "Charizard-Holo"
    assert info.pop_total == 1287 and info.pop_higher == 121 and "Population 1287" in data["text"]
