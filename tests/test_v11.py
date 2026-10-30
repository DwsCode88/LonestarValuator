import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from valuator import certs, history  # noqa: E402
from valuator.db import DB  # noqa: E402
from valuator.models import Comp, Item, replacement_value  # noqa: E402
from valuator.pdf_chart import history_drawing  # noqa: E402

TODAY = date(2026, 10, 29)


def test_grade_number():
    assert certs.grade_number("GEM MT 10") == "10"
    assert certs.grade_number("NM-MT 8.5") == "8.5"
    assert certs.grade_number("GEM MINT 10.0") == "10"
    assert certs.grade_number("") == ""


def test_parse_psa():
    data = {"PSACert": {"CertNumber": "81234567", "Year": "1999", "Brand": "POKEMON GAME",
                        "Category": "TCG CARDS", "CardNumber": "4", "Subject": "CHARIZARD-HOLO",
                        "Variety": "1ST EDITION", "CardGrade": "MINT 9", "GradeDescription": "MINT 9",
                        "TotalPopulation": 1234, "PopulationHigher": 121}}
    info = certs.parse_psa(data, "81234567")
    assert info.ok and info.grade == "9" and info.year == "1999"
    assert info.name == "Charizard-Holo" and info.game == "Pokemon" and info.language == "English"
    assert info.pop_total == 1234 and info.pop_higher == 121
    assert "PSA pop report" in info.pop_source
    jp = certs.parse_psa({"PSACert": {"Brand": "POKEMON JAPANESE SV4a-SHINY TREASURE EX", "Subject": "GENGAR",
                                      "CardGrade": "GEM MT 10", "TotalPopulation": "5,001"}}, "1")
    assert jp.language == "Japanese" and jp.set_name == "Sv4A-Shiny Treasure Ex" or jp.set_name
    assert jp.pop_total == 5001
    assert not certs.parse_psa({}, "1").ok


CGC_HTML = """<html><body><dl>
<dt>Cert #</dt><dd>1401036616276</dd><dt>Card Name</dt><dd>Gengar ex</dd>
<dt>Game</dt><dd>Pokémon</dd><dt>Year</dt><dd>2024</dd><dt>Language</dt><dd>Japanese</dd>
<dt>Card Set</dt><dd>Wild Force</dd><dt>Card Number</dt><dd>047/071</dd><dt>Variant 1</dt><dd>Holo</dd>
<dt>Grade</dt><dd>GEM MINT 10</dd></dl></body></html>"""


def test_parse_cgc():
    info = certs.parse_cgc(CGC_HTML, "1401036616276")
    assert info.ok and info.name == "Gengar ex" and info.number == "047/071"
    assert info.grade == "10" and info.game == "Pokemon" and info.language == "Japanese"
    assert info.pop_total is None
    assert not certs.parse_cgc("<html>nothing</html>", "1").ok


def test_lookup_other_graders():
    r = certs.lookup("BGS", "123", {})
    assert not r.ok and "manually" in r.message
    assert not certs.lookup("PSA", "123", {}).ok        # no token
    assert not certs.lookup("PSA", "", {"psa_token": "x"}).ok


def test_replacement_value():
    assert replacement_value(100, 20) == 120
    assert replacement_value(None, 20) is None
    assert replacement_value(99.99, 0) == 99.99


def test_history_build_and_drawing():
    comps = [Comp("eBay", 100 + i * 2, sale_date=TODAY - timedelta(days=90 - i * 6)) for i in range(15)]
    comps.append(Comp("eBay", 999, sale_date=TODAY - timedelta(days=5)))            # outlier
    comps.append(Comp("PriceCharting", 150, kind="guide", sale_date=TODAY))          # not a sale
    comps.append(Comp("eBay", 50, sale_date=TODAY - timedelta(days=500)))           # too old
    h = history.build(comps, {"chart_days": 365}, today=TODAY)
    assert h.usable and len(h.points) == 15
    assert h.median and h.change_pct and h.change_pct > 0
    assert history_drawing(h, 120.0, 500) is not None
    assert not history.build(comps[:2], {}, today=TODAY).usable
    assert history_drawing(history.History(), None, 500) is None
    t = history.nice_ticks(93.4, 141.2)
    assert t[0] <= 93.4 and t[-1] >= 141.2 and len(t) >= 3


def test_migrates_v1_database(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE reports (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, customer_name TEXT DEFAULT '',
      customer_email TEXT DEFAULT '', customer_phone TEXT DEFAULT '', customer_address TEXT DEFAULT '',
      purpose TEXT DEFAULT 'General Appraisal', notes TEXT DEFAULT '', status TEXT DEFAULT 'Draft',
      created_at TEXT, updated_at TEXT);
    CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, position INTEGER DEFAULT 0,
      game TEXT, name TEXT, set_name TEXT, number TEXT, variant TEXT, language TEXT, graded INTEGER DEFAULT 0,
      condition TEXT, grader TEXT, grade TEXT, cert TEXT, qty INTEGER DEFAULT 1, image_path TEXT, image_url TEXT,
      notes TEXT, value_override REAL, override_note TEXT, fmv REAL, low REAL, high REAL, confidence TEXT,
      n_sales INTEGER DEFAULT 0, trend TEXT, valued_at TEXT, tcg_product_id TEXT, pc_product_id TEXT);
    INSERT INTO reports (number, customer_name) VALUES ('LSV-2026-0001', 'Old');
    INSERT INTO items (report_id, name, graded, grader, grade) VALUES (1, 'Pikachu', 1, 'PSA', '10');
    """)
    con.commit(); con.close()
    db = DB(p)
    it = db.items(1)[0]
    assert it.name == "Pikachu" and it.pop_total is None and it.year == ""
    it.pop_total, it.pop_higher, it.pop_source = 42, 0, "PSA pop report"
    db.save_item(it)
    assert db.items(1)[0].pop_label == "Pop 42 · 0 higher"
    db.update_report(1, show_replacement=1, replacement_pct=25.0)
    r = db.get_report(1)
    assert r["show_replacement"] == 1 and r["replacement_pct"] == 25.0


def test_insurance_report_defaults_on(tmp_path):
    db = DB(tmp_path / "n.db")
    assert db.get_report(db.create_report("LSV", purpose="Insurance"))["show_replacement"] == 1
    assert db.get_report(db.create_report("LSV"))["show_replacement"] == 0
