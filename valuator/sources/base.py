"""Base class for data sources."""
from __future__ import annotations

from ..models import Item, SourceResult
from ..net import make_session


class Source:
    name = "Source"
    kind = "sale"   # default comp kind produced

    def __init__(self, settings: dict | None = None, session=None):
        self.settings = settings or {}
        self.session = session or make_session()

    def supports(self, item: Item) -> bool:
        return True

    def fetch(self, item: Item) -> SourceResult:
        raise NotImplementedError

    def run(self, item: Item) -> SourceResult:
        """fetch() with errors turned into a failed result instead of exceptions."""
        if not self.supports(item):
            return SourceResult(self.name, ok=True, message="Not applicable for this item")
        try:
            return self.fetch(item)
        except Exception as e:  # network/parse errors shouldn't kill the whole valuation
            return SourceResult(self.name, ok=False, message=f"{type(e).__name__}: {e}")
