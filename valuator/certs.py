"""Slab cert lookup: PSA (official public API, free token) and CGC (public cert page).

PSA returns card details + population at grade and higher. CGC's page gives card details;
its population loads via JavaScript so it isn't available here (enter it manually).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from .net import TIMEOUT, make_session

PSA_URL = "https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}"
CGC_URL = "https://www.cgccards.com/certlookup/{cert}/"

GAME_HINTS = [("pokemon", "Pokemon"), ("pokémon", "Pokemon"), ("magic", "Magic: The Gathering"),
              ("one piece", "One Piece"), ("yu-gi-oh", "Yu-Gi-Oh!"), ("yugioh", "Yu-Gi-Oh!"),
              ("lorcana", "Lorcana"), ("dragon ball", "Dragon Ball Super"), ("digimon", "Digimon"),
              ("flesh and blood", "Flesh and Blood"), ("star wars", "Star Wars Unlimited")]
LANG_HINTS = ["Japanese", "Korean", "Chinese", "German", "French", "Italian", "Spanish"]


@dataclass
class CertInfo:
    grader: str
    cert: str
    ok: bool = True
    message: str = ""
    name: str = ""
    set_name: str = ""
    number: str = ""
    year: str = ""
    variant: str = ""
    language: str = ""
    game: str = ""
    grade: str = ""
    grade_desc: str = ""
    pop_total: Optional[int] = None
    pop_higher: Optional[int] = None
    url: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def pop_source(self) -> str:
        return f"{self.grader} pop report as of {date.today():%m/%d/%Y}" if self.pop_total is not None else ""


def grade_number(text: str) -> str:
    """'GEM MT 10' -> '10', 'NM-MT 8.5' -> '8.5', 'MINT 9' -> '9'."""
    m = re.findall(r"(\d+(?:\.\d)?)", text or "")
    if not m:
        return ""
    g = m[-1]
    return g[:-2] if g.endswith(".0") else g


def _int(v) -> Optional[int]:
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _guess_game(*texts: str) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for hint, game in GAME_HINTS:
        if hint in blob:
            return game
    return ""


def _guess_lang(*texts: str) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for lang in LANG_HINTS:
        if lang.lower() in blob:
            return lang
    return "English"


def _clean_set(brand: str) -> str:
    """'POKEMON JAPANESE SV4a-SHINY TREASURE EX' -> 'SV4a-Shiny Treasure Ex'"""
    s = brand or ""
    for word in ["POKEMON", "POKÉMON", "MAGIC THE GATHERING", "MAGIC", "ONE PIECE", "YU-GI-OH!", "YU-GI-OH",
                 "DISNEY LORCANA", "LORCANA"] + [lang.upper() for lang in LANG_HINTS]:
        s = re.sub(rf"\b{re.escape(word)}\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s.title() if s.isupper() else s


def parse_psa(data: dict, cert: str) -> CertInfo:
    c = (data or {}).get("PSACert") or {}
    if not c:
        return CertInfo("PSA", cert, ok=False, message="Cert not found")
    brand = c.get("Brand", "") or ""
    subject = (c.get("Subject", "") or "").title()
    info = CertInfo(
        grader="PSA", cert=str(c.get("CertNumber") or cert), name=subject,
        set_name=_clean_set(brand), number=(c.get("CardNumber") or "").strip(),
        year=str(c.get("Year") or ""), variant=(c.get("Variety") or "").title(),
        language=_guess_lang(brand, c.get("Category", "")),
        game=_guess_game(brand, c.get("Category", ""), subject),
        grade=grade_number(c.get("CardGrade", "")), grade_desc=c.get("CardGrade", "") or "",
        pop_total=_int(c.get("TotalPopulation")), pop_higher=_int(c.get("PopulationHigher")),
        url=f"https://www.psacard.com/cert/{cert}", raw=c)
    if c.get("GradeDescription"):
        info.grade_desc = c["GradeDescription"]
    info.message = f"PSA {info.grade} · {info.year} {brand} {subject}".strip()
    return info


def lookup_psa(cert: str, token: str, session=None) -> CertInfo:
    if not token:
        return CertInfo("PSA", cert, ok=False,
                        message="Add your free PSA API token in Settings → Data sources (psacard.com/publicapi)")
    s = session or make_session()
    r = s.get(PSA_URL.format(cert=cert), headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    if r.status_code in (401, 403):
        return CertInfo("PSA", cert, ok=False, message="PSA rejected the API token")
    if r.status_code == 429:
        return CertInfo("PSA", cert, ok=False, message="PSA daily API limit reached – try again tomorrow")
    r.raise_for_status()
    return parse_psa(r.json(), cert)


CGC_LABELS = {"card name": "name", "game": "game", "year": "year", "language": "language",
              "card set": "set_name", "card number": "number", "variant 1": "variant", "grade": "grade_desc"}


def parse_cgc(html: str, cert: str) -> CertInfo:
    soup = BeautifulSoup(html, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
    found: dict[str, str] = {}
    for i, ln in enumerate(lines[:-1]):
        key = CGC_LABELS.get(ln.rstrip(":").lower())
        if key and key not in found:
            found[key] = lines[i + 1]
    if "name" not in found:
        return CertInfo("CGC", cert, ok=False, message="Cert not found on CGC")
    info = CertInfo("CGC", cert, url=CGC_URL.format(cert=cert), **{k: v for k, v in found.items()})
    info.game = _guess_game(found.get("game", "")) or found.get("game", "")
    info.language = found.get("language") or "English"
    info.grade = grade_number(found.get("grade_desc", ""))
    info.message = f"CGC {info.grade} · {info.year} {info.set_name} {info.name} (population not available – enter manually)"
    return info


def lookup_cgc(cert: str, session=None) -> CertInfo:
    s = session or make_session()
    r = s.get(CGC_URL.format(cert=cert), timeout=TIMEOUT)
    if r.status_code == 404:
        return CertInfo("CGC", cert, ok=False, message="Cert not found on CGC")
    r.raise_for_status()
    return parse_cgc(r.text, cert)


def lookup(grader: str, cert: str, settings: dict) -> CertInfo:
    cert = re.sub(r"\D", "", cert or "")
    if not cert:
        return CertInfo(grader, cert, ok=False, message="Enter a cert number")
    try:
        if grader == "PSA":
            return lookup_psa(cert, settings.get("psa_token", ""))
        if grader == "CGC":
            return lookup_cgc(cert)
    except Exception as e:
        return CertInfo(grader, cert, ok=False, message=f"{type(e).__name__}: {e}")
    return CertInfo(grader, cert, ok=False,
                    message=f"{grader} has no public cert lookup – enter details and population manually")
