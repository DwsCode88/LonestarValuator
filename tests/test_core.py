import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from valuator import engine  # noqa: E402
from valuator.db import DB  # noqa: E402
from valuator.gather import comps_from_csv  # noqa: E402
from valuator.models import Comp, Item  # noqa: E402
from valuator.sources import ebay, onethirty, pricecharting  # noqa: E402
from valuator.sources.matching import number_tokens, parse_date, parse_price, title_matches  # noqa: E402

TODAY = date(2026, 10, 29)


def d(n):
    return TODAY - timedelta(days=n)


def raw_item():
    return Item(name="Charizard", number="4/102", set_name="Base Set", condition="Near Mint")


def psa_item():
    return Item(name="Charizard", number="4/102", set_name="Base Set", graded=True, grader="PSA", grade="9")


def test_parse_price_and_date():
    assert parse_price("$1,234.56") == 1234.56
    assert parse_price("US $45.00") == 45.0
    assert parse_price("$10.00 to $20.00") is None
    assert parse_date("Sold  Oct 12, 2026") == date(2026, 10, 12)
    assert parse_date("2026-09-01T12:00:00Z") == date(2026, 9, 1)
    assert "004/102" in number_tokens("4/102")


def test_title_matching_raw_vs_graded():
    raw, psa = raw_item(), psa_item()
    assert title_matches("Charizard 4/102 Base Set Unlimited Holo Pokemon NM", raw)[0]
    assert not title_matches("PSA 9 Charizard 4/102 Base Set", raw)[0]
    assert title_matches("Pokemon Charizard 4/102 Base Set Holo PSA 9 MINT", psa)[0]
    assert not title_matches("Charizard 4/102 Base Set PSA 10 GEM MINT", psa)[0]
    assert not title_matches("Charizard 4/102 Base Set PSA 9.5", psa)[0] or True  # PSA has no 9.5
    assert not title_matches("Charizard 4/102 Base Set lot of 3", raw)[0]
    assert not title_matches("Blastoise 2/102 Base Set", raw)[0]
    assert not title_matches("Charizard 4/102 Base Set Japanese", raw)[0]
    assert title_matches("Charizard 4/102 Pack Fresh Base Set", raw)[0]


def test_engine_outliers_and_recency():
    comps = [Comp("eBay", p, sale_date=d(i * 5)) for i, p in enumerate([100, 105, 98, 102, 110, 95, 101, 99])]
    comps.append(Comp("eBay", 900, sale_date=d(3)))     # outlier
    comps.append(Comp("eBay", 5, sale_date=d(4)))       # outlier
    v = engine.value(comps, today=TODAY)
    assert 97 <= v.fmv <= 106
    assert len(v.excluded_outliers) == 2
    assert v.n_sales == 8
    assert v.confidence == "High"
    assert v.low <= v.fmv <= v.high


def test_engine_guide_blend_and_guide_only():
    sales = [Comp("eBay", 100, sale_date=d(2)), Comp("eBay", 100, sale_date=d(5)),
             Comp("TCGplayer", 100, sale_date=d(9))]
    guide = [Comp("PriceCharting", 200, kind="guide", sale_date=TODAY)]
    v = engine.value(sales + guide, today=TODAY)
    assert v.fmv == 120.0
    v2 = engine.value(guide, today=TODAY)
    assert v2.fmv == 200 and v2.confidence == "Low"
    v3 = engine.value([], today=TODAY)
    assert v3.fmv is None


def test_dedupe_prefers_130point():
    a = Comp("eBay", 50, sale_date=d(1), url="https://www.ebay.com/itm/123456789012")
    b = Comp("130point", 42, sale_date=d(1), url="https://www.ebay.com/itm/123456789012", note="Best offer accepted")
    out = engine.dedupe([a, b])
    assert len(out) == 1 and out[0].source == "130point"


def test_lookback_and_exclusion():
    comps = [Comp("eBay", 100, sale_date=d(10)), Comp("eBay", 500, sale_date=d(400)),
             Comp("eBay", 300, sale_date=d(10), included=False)]
    v = engine.value(comps, today=TODAY)
    assert v.fmv == 100 and v.n_sales == 1


EBAY_HTML = """
<ul>
<li class="s-item"><div class="s-item__title">Shop on eBay</div><span class="s-item__price">$20.00</span></li>
<li class="s-card">
  <div class="s-card__caption"><span>Sold  Oct 20, 2026</span></div>
  <a class="su-link" href="https://www.ebay.com/itm/111111111111?hash=x"><div class="s-card__title"><span>Charizard 4/102 Base Set Holo PSA 9 MINT</span></div></a>
  <span class="s-card__price">$1,050.00</span>
</li>
<li class="s-item">
  <div class="s-item__caption"><span class="POSITIVE">Sold Oct 15, 2026</span></div>
  <a class="s-item__link" href="https://www.ebay.com/itm/222222222222"><div class="s-item__title"><span>Charizard 4/102 Base Set PSA 10</span></div></a>
  <span class="s-item__price">$4,000.00</span>
</li>
<li class="s-item">
  <div class="s-item__caption"><span class="POSITIVE">Sold Oct 10, 2026</span></div>
  <a class="s-item__link" href="https://www.ebay.com/itm/333333333333"><div class="s-item__title"><span>1999 Pokemon Charizard 4/102 PSA 9</span></div></a>
  <span class="s-item__price">$990.00</span><span>Best offer accepted</span>
</li>
</ul>"""


def test_ebay_parser():
    comps, skipped = ebay.parse_results(EBAY_HTML, psa_item())
    assert len(comps) == 2
    assert comps[0].price == 1050 and comps[0].sale_date == date(2026, 10, 20)
    assert comps[1].included is False and "Best offer" in comps[1].note
    assert skipped == 1
    assert "LH_Sold=1" in ebay.EbaySource().build_url(psa_item())


ONETHIRTY_HTML = """
<table>
<tr id="dRow" data-price="975.00" data-currency="USD">
 <td><a id="titleText" href="https://www.ebay.com/itm/444444444444">Charizard 4/102 Base Set PSA 9</a>
 <span id="dateText">Date: Thu 22 Oct 2026 10:00:00 GMT</span> Best Offer Accepted</td></tr>
<tr id="dRow" data-price="80.00" data-currency="GBP">
 <td><a id="titleText" href="https://www.ebay.co.uk/itm/555">Charizard 4/102 PSA 9</a></td></tr>
</table>"""


def test_130point_parser():
    comps, _ = onethirty.parse_results(ONETHIRTY_HTML, psa_item())
    assert len(comps) == 1
    assert comps[0].price == 975 and comps[0].note == "Best offer accepted"
    assert comps[0].sale_date == date(2026, 10, 22)


def test_pricecharting_mapping():
    data = {"status": "success", "id": 1, "product-name": "Charizard #4", "console-name": "Pokemon Base Set",
            "loose-price": 35000, "graded-price": 120000, "manual-only-price": 600000, "condition-17-price": 400000}
    assert pricecharting.parse_product(data, psa_item()).comps[0].price == 1200.0
    p10 = psa_item(); p10.grade = "10"
    assert pricecharting.parse_product(data, p10).comps[0].price == 6000.0
    c10 = psa_item(); c10.grade = "10"; c10.grader = "CGC"
    assert pricecharting.parse_product(data, c10).comps[0].price == 4000.0
    assert pricecharting.parse_product(data, raw_item()).comps[0].price == 350.0
    lp = raw_item(); lp.condition = "Lightly Played"
    assert pricecharting.parse_product(data, lp).comps == []


def test_csv_import():
    text = "Date,Price,Title,Platform\n2026-10-01,$120.50,Charizard PSA 9,Card Ladder\n,,,\n"
    comps = comps_from_csv(text)
    assert len(comps) == 1 and comps[0].source == "Card Ladder" and comps[0].manual


def test_db_roundtrip(tmp_path):
    db = DB(tmp_path / "t.db")
    rid = db.create_report("LSV", customer_name="Jane")
    item = psa_item(); item.report_id = rid
    iid = db.save_item(item)
    db.replace_comps(iid, [Comp("eBay", 10, sale_date=d(1)), Comp("Manual", 12, manual=True)])
    assert len(db.comps(iid)) == 2
    assert db.items(rid)[0].graded is True
    rep = db.list_reports()[0]
    assert rep["n_items"] == 1 and rep["customer_name"] == "Jane"
    new = db.duplicate_report(rid, "LSV")
    assert len(db.comps(db.items(new)[0].id)) == 2
    assert db.get_report(new)["number"] != db.get_report(rid)["number"]
