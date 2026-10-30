from .ebay import EbaySource
from .tcgplayer import TCGplayerSource
from .pricecharting import PriceChartingSource
from .onethirty import OneThirtyPointSource

ALL_SOURCES = [EbaySource, OneThirtyPointSource, TCGplayerSource, PriceChartingSource]


def enabled_sources(settings: dict):
    on = settings.get("sources_enabled", {})
    return [cls for cls in ALL_SOURCES if on.get(cls.name, True)]
