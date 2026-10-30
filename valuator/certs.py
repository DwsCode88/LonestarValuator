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
    pop_via: str = ""      # "" = grader's own data, or "GemRate"

    @property
    def pop_source(self) -> str:
        if self.pop_total is None:
            return ""
        via = f" via {self.pop_via}" if self.pop_via else ""
        return f"{self.grader} population{via} as of {date.today():%m/%d/%Y}"


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
    token = clean_token(token)
    s = session or make_session()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": "LonestarValuator/1.1 (+https://github.com/DwsCode88/LonestarValuator)"}
    r = s.get(PSA_URL.format(cert=cert), headers=headers, timeout=TIMEOUT)
    detail = _detail(r)
    if r.status_code == 401:
        return CertInfo("PSA", cert, ok=False,
                        message=f"PSA rejected the token (401). Copy it again from psacard.com/publicapi – "
                                f"tokens can expire.{detail}")
    if r.status_code == 403:
        return CertInfo("PSA", cert, ok=False, message=f"PSA refused the request (403).{detail}")
    if r.status_code == 429:
        return CertInfo("PSA", cert, ok=False, message="PSA daily API limit reached – try again tomorrow")
    if r.status_code == 404:
        return CertInfo("PSA", cert, ok=False, message=f"Cert {cert} not found at PSA")
    if r.status_code >= 400:
        return CertInfo("PSA", cert, ok=False, message=f"PSA error {r.status_code}.{detail}")
    try:
        data = r.json()
    except ValueError:
        return CertInfo("PSA", cert, ok=False, message=f"PSA sent a non-JSON reply.{detail}")
    if isinstance(data, dict) and data.get("IsValidRequest") is False:
        return CertInfo("PSA", cert, ok=False, message=f"PSA: {data.get('ServerMessage') or 'invalid request'}")
    if isinstance(data, dict) and not data.get("PSACert") and data.get("ServerMessage"):
        return CertInfo("PSA", cert, ok=False, message=f"PSA: {data['ServerMessage']}")
    return parse_psa(data, cert)


def clean_token(token: str) -> str:
    """Accept the token however it was pasted: with 'Bearer ', quotes, spaces or line breaks."""
    t = (token or "").strip().strip('"').strip("'").strip()
    t = re.sub(r"(?i)^(authorization:\s*)?bearer\s+", "", t)
    return re.sub(r"\s+", "", t)


def _detail(r) -> str:
    body = (r.text or "").strip().replace("\n", " ")
    if not body:
        return ""
    if body.startswith("<"):
        return " (blocked page returned – try again in a minute)"
    return f" Server said: {body[:160]}"


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
    info.message = f"CGC {info.grade} · {info.year} {info.set_name} {info.name}"
    return info


def lookup_cgc(cert: str, session=None) -> CertInfo:
    s = session or make_session()
    r = s.get(CGC_URL.format(cert=cert), timeout=TIMEOUT)
    if r.status_code == 404:
        return CertInfo("CGC", cert, ok=False, message="Cert not found on CGC")
    r.raise_for_status()
    return parse_cgc(r.text, cert)


# ---------- PSA public cert page (no API approval needed; card details only) ----------

PSA_PAGE_URL = "https://www.psacard.com/cert/{cert}"
PSA_LABELS = {"item grade": "grade_desc", "grade": "grade_desc", "year": "year", "brand/title": "brand",
              "brand": "brand", "subject": "name", "card number": "number", "category": "category",
              "variety/pedigree": "variant", "variety": "variant"}


def _label_pairs(html: str, labels: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
    found: dict[str, str] = {}
    for i, ln in enumerate(lines[:-1]):
        key = labels.get(ln.rstrip(":").strip().lower())
        if key and key not in found:
            val = lines[i + 1]
            if labels.get(val.rstrip(":").lower()):   # empty field: next line is another label
                continue
            found[key] = val
    return found


def parse_psa_page(html: str, cert: str) -> CertInfo:
    f = _label_pairs(html, PSA_LABELS)
    if "name" not in f:
        return CertInfo("PSA", cert, ok=False, message="Cert not found on psacard.com")
    brand = f.get("brand", "")
    info = CertInfo("PSA", cert, name=f["name"].title(), set_name=_clean_set(brand),
                    number=f.get("number", ""), year=f.get("year", ""),
                    variant=f.get("variant", "").title(), language=_guess_lang(brand),
                    game=_guess_game(brand, f.get("category", ""), f["name"]),
                    grade=grade_number(f.get("grade_desc", "")), grade_desc=f.get("grade_desc", ""),
                    url=PSA_PAGE_URL.format(cert=cert))
    info.message = f"PSA {info.grade} · {info.year} {brand} {f['name']}".strip()
    return info


def lookup_psa_page(cert: str, session=None) -> CertInfo:
    s = session or make_session()
    r = s.get(PSA_PAGE_URL.format(cert=cert), timeout=TIMEOUT)
    if r.status_code == 404:
        return CertInfo("PSA", cert, ok=False, message=f"Cert {cert} not found at PSA")
    if r.status_code in (403, 503):
        return CertInfo("PSA", cert, ok=False, url=PSA_PAGE_URL.format(cert=cert),
                        message="psacard.com blocked the automatic lookup – use Open cert page and type the details")
    r.raise_for_status()
    return parse_psa_page(r.text, cert)


# ---------- GemRate (optional paid key; population for PSA, BGS, SGC, CGC) ----------

GEMRATE_URL = "https://api.gemrate.com/v1/certs/{grader}/{cert}/population"
GEMRATE_GRADERS = {"PSA": "psa", "BGS": "beckett", "SGC": "sgc", "CGC": "cgc"}


def parse_gemrate(data: dict, grader: str, cert: str) -> CertInfo:
    d = (data or {}).get("data") or data or {}
    gd = d.get("grader_data") or {}
    pc = gd.get("population_context") or {}
    grade_txt = str(gd.get("grade") or gd.get("grade_label") or gd.get("label") or "")
    info = CertInfo(grader, cert, url=d.get("gemrate_url", ""), grade=grade_number(grade_txt),
                    grade_desc=str(gd.get("grade_label") or grade_txt),
                    pop_total=_int(pc.get("grade_population")), pop_higher=_int(pc.get("population_higher")))
    pd = d.get("parsed_description") or {}
    if isinstance(pd, dict):
        info.name = str(pd.get("name") or pd.get("player") or pd.get("subject") or "")
        info.set_name = str(pd.get("set") or pd.get("set_name") or "")
        info.number = str(pd.get("card_number") or pd.get("number") or "")
        info.year = str(pd.get("year") or "")
        info.variant = str(pd.get("parallel") or pd.get("variant") or "")
    desc = str(d.get("description") or "")
    if not info.name and desc:
        info.name = desc
    info.game = _guess_game(desc)
    if info.pop_total is None and not info.name:
        return CertInfo(grader, cert, ok=False, message="GemRate has no data for this cert")
    info.message = f"GemRate: {desc or info.name}".strip()
    return info


def lookup_gemrate(grader: str, cert: str, key: str, session=None) -> CertInfo:
    g = GEMRATE_GRADERS.get(grader)
    if not g:
        return CertInfo(grader, cert, ok=False, message=f"GemRate doesn't cover {grader}")
    s = session or make_session()
    r = s.get(GEMRATE_URL.format(grader=g, cert=cert), params={"parsed_description": "true", "all_graders": "false"},
              headers={"x-api-key": key.strip(), "Accept": "application/json"}, timeout=TIMEOUT)
    if r.status_code in (401, 403):
        return CertInfo(grader, cert, ok=False, message=f"GemRate rejected the API key ({r.status_code})")
    if r.status_code == 404:
        return CertInfo(grader, cert, ok=False, message="Cert not found on GemRate")
    if r.status_code == 429:
        return CertInfo(grader, cert, ok=False, message="GemRate rate limit reached")
    r.raise_for_status()
    return parse_gemrate(r.json(), grader, cert)


def cert_page_url(grader: str, cert: str) -> str:
    cert = re.sub(r"\D", "", cert or "")
    return {"PSA": PSA_PAGE_URL.format(cert=cert), "CGC": CGC_URL.format(cert=cert),
            "SGC": "https://gosgc.com/cert-code-lookup/",
            "BGS": "https://www.beckett.com/grading/card-lookup"}.get(grader, "")


def _merge(base: CertInfo, extra: CertInfo) -> CertInfo:
    """Fill gaps in base from extra (used to add GemRate population to PSA/CGC details)."""
    for f in ("name", "set_name", "number", "year", "variant", "game", "grade", "grade_desc"):
        if not getattr(base, f) and getattr(extra, f):
            setattr(base, f, getattr(extra, f))
    if base.pop_total is None and extra.pop_total is not None:
        base.pop_total, base.pop_higher = extra.pop_total, extra.pop_higher
        base.pop_via = "GemRate"
    return base


def _safe(fn, *args) -> CertInfo:
    try:
        return fn(*args)
    except Exception as e:
        return CertInfo(args[0] if fn is lookup_gemrate else "", "", ok=False, message=f"{type(e).__name__}: {e}")


def lookup(grader: str, cert: str, settings: dict) -> CertInfo:
    cert = re.sub(r"\D", "", cert or "")
    if not cert:
        return CertInfo(grader, cert, ok=False, message="Enter a cert number")
    notes = []
    info: Optional[CertInfo] = None
    if grader == "PSA":
        token = settings.get("psa_token", "")
        if token:
            api = _safe(lookup_psa, cert, token)
            if api.ok:
                info = api
            else:
                notes.append(f"PSA API: {api.message.split('.')[0]}")
        if info is None:
            page = _safe(lookup_psa_page, cert)
            info = page if page.ok else None
            if not page.ok:
                notes.append(page.message)
    elif grader == "CGC":
        page = _safe(lookup_cgc, cert)
        info = page if page.ok else None
        if not page.ok:
            notes.append(page.message)

    key = settings.get("gemrate_key", "")
    if key and grader in GEMRATE_GRADERS and (info is None or info.pop_total is None):
        gr = _safe(lookup_gemrate, grader, cert, key)
        if gr.ok:
            info = gr if info is None else _merge(info, gr)
            if info is gr:
                info.pop_via = "GemRate"
        else:
            notes.append(gr.message)

    if info is None:
        msg = "; ".join(n for n in notes if n) or \
            f"{grader} has no public cert lookup – enter details and population manually"
        return CertInfo(grader, cert, ok=False, message=msg, url=cert_page_url(grader, cert))
    info.grader, info.cert = grader, cert
    if not info.url:
        info.url = cert_page_url(grader, cert)
    if info.pop_total is None:
        info.message += " · population not available – enter it from the pop report"
    return info
