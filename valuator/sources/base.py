"""Base class for data sources."""
from __future__ import annotations

from .. import browser as browser_mod
from ..models import Item, SourceResult
from ..net import TIMEOUT, make_session


class Source:
    name = "Source"
    kind = "sale"   # default comp kind produced

    def __init__(self, settings: dict | None = None, session=None, use_browser: bool | None = None):
        self.settings = settings or {}
        self.session = session or make_session()
        if use_browser is None:
            use_browser = bool(self.settings.get("use_browser", True))
        self._use_browser = use_browser
        self.via = "direct"

    @property
    def browser(self):
        if not self._use_browser:
            return None
        svc = browser_mod.service(self.settings)
        if svc is None:
            return None
        try:
            svc.ensure_started()
        except browser_mod.BrowserUnavailable:
            return None
        return svc

    # ---- transport helpers: Chrome first, plain HTTP fallback ----
    def get_html(self, url: str, wait_selector: str | None = None, settle_ms: int = 0) -> str:
        b = self.browser
        if b is not None:
            try:
                html = b.get_html(url, wait_selector, settle_ms, site=self.name)
                self.via = "Chrome"
                return html
            except Exception:
                pass
        r = self.session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        self.via = "direct"
        return r.text

    def fetch(self, origin: str, url: str, method: str = "GET", json_body=None, form: dict | None = None,
              params: dict | None = None, headers: dict | None = None, as_json: bool = True):
        from urllib.parse import urlencode
        full = url + (("&" if "?" in url else "?") + urlencode(params) if params else "")
        b = self.browser
        if b is not None:
            try:
                body = json_body
                hdrs = dict(headers or {})
                if form is not None:
                    body = urlencode(form)
                    hdrs["Content-Type"] = "application/x-www-form-urlencoded"
                out = b.fetch(origin, full, method, body, hdrs, as_json=as_json)
                self.via = "Chrome"
                return out
            except Exception:
                pass
        self.via = "direct"
        hdrs = {"Origin": origin.rstrip("/").rsplit("/", 1)[0] if origin.count("/") > 3 else origin.rstrip("/"),
                "Referer": origin, **(headers or {})}
        if method == "POST":
            r = self.session.post(full, json=json_body if form is None else None, data=form, headers=hdrs,
                                  timeout=TIMEOUT)
        else:
            r = self.session.get(full, headers=hdrs, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json() if as_json else r.text

    def supports(self, item: Item) -> bool:
        return True

    def fetch_item(self, item: Item) -> SourceResult:
        raise NotImplementedError

    def run(self, item: Item) -> SourceResult:
        """fetch_item() with errors turned into a failed result instead of exceptions."""
        if not self.supports(item):
            return SourceResult(self.name, ok=True, message="Not applicable for this item")
        try:
            res = self.fetch_item(item)
            if self.via == "Chrome" and res.message:
                res.message += " · via Chrome"
            return res
        except Exception as e:  # network/parse errors shouldn't kill the whole valuation
            return SourceResult(self.name, ok=False, message=f"{type(e).__name__}: {e}")
