# Lonestar Valuator

Windows app for building customer card appraisals. Enter cards (raw or graded), it pulls recent sales and guide prices from several sources, computes a fair market value with a range and confidence rating, and exports a branded PDF valuation report.

## Data sources

| Source | What it provides | Raw | Graded | Setup |
|---|---|---|---|---|
| eBay | Recent sold listings (scraped from eBay's sold search) | ✓ | ✓ | none |
| 130point | Sold comps incl. best-offer-accepted prices | ✓ | ✓ | none |
| TCGplayer | Market price + latest sales by condition, card image | ✓ | – | none |
| PriceCharting | Guide value by grade (PSA/BGS/CGC/SGC/TAG/ACE 10, 9.5, 9…) | NM only | ✓ | API token (paid subscription) in Settings → Data sources |
| Card Ladder / anything else | Import a CSV (Date, Price, Title, Source) or add manual comps | ✓ | ✓ | – |

eBay, 130point and TCGplayer have no open public API for this, so the app uses the same pages/endpoints their websites use. If one of them changes or blocks a request, that source shows ✗ with the reason and the valuation continues with the others. The parsers live in `valuator/sources/` if one needs adjusting.

## Chrome engine (v1.2)

The app drives Google Chrome (Microsoft Edge if Chrome isn't installed) to gather data – the same way you'd browse – so eBay, 130point, TCGplayer, PriceCharting, PSA and CGC block it far less, JavaScript-only data (CGC population) loads, and sign-ins are remembered.

- Chrome runs **minimized** with its own profile in `%APPDATA%\LonestarValuator\chrome-profile`, separate from your normal Chrome.
- If a site shows a "verify you're human" check, a yellow banner appears and the Chrome window pops up – finish the check and the app carries on.
- **Chrome menu → Sign in to…** opens Card Ladder, eBay, PSA, TCGplayer or PriceCharting once; the login is kept.
- If Chrome can't start, every source falls back to direct requests. Settings → Browser turns Chrome mode off or switches to Edge.

## PSA cert lookup via Chrome (v1.2.1)

Look up (or a cert # in the quick-add bar) opens the PSA cert page in a visible Chrome tab, waits for it to finish loading – finish any human check if one appears – then reads the card details and the population from the page and the data it loads in the background, and minimizes Chrome again. If the page is slow, leave it open and click **📄** next to the cert box once the card shows. Turn the visible tab off in Settings → Browser.

## Faster workflow (v1.2)

- **Quick-add bar:** scan/type a cert # (or pick Raw/PSA/BGS/CGC… and type a card name) and press Enter. Certs are looked up, cards are valued in the background, and each row shows live status.
- **Find card:** search TCGplayer's catalog with pictures and pick the exact printing – stops wrong-card comps.
- **PriceCharting without a token:** reads the public product page – guide values for every grade plus its sold listings (eBay, Goldin, TCGplayer…).
- **Capture sales from Chrome:** open any sales page (Card Ladder, Goldin, Fanatics, Heritage…) via *Search in Chrome*, then click **Capture** – matching sales are added as comps.

## Cert lookup & population (v1.1)

Tick **Graded**, pick the grader, type the cert # and press **Look up** (or Enter).

- **PSA** – fills card name, year, set, number, variety, language, grade, and the population at grade + graded higher. Needs a free PSA API token: sign in at psacard.com/publicapi, copy the token into Settings → Data sources. PSA limits free tokens to a small number of calls per day.
- **CGC** – fills the card details from CGC's public cert page. CGC's population loads in the browser only, so enter it by hand.
- **BGS / SGC / TAG / ACE** – no public lookup; enter details and pop manually.

Population shows on the item list, the PDF summary and the card page, with the date it was pulled (PSA) or "Entered manually".

## Price history chart (v1.1)

Each card shows its dated sales (dots), a rolling median (line) and the fair market value (dashed). Hover a dot for its date and price. The same chart prints on the card's PDF page. Settings → Valuation sets how far back it reaches (default 365 days) and can turn it off in the PDF. Note eBay's sold search only goes back ~90 days, so longer history comes from 130point and imported Card Ladder CSVs.

## Insurance replacement value (v1.1)

Replacement value = fair market value + a markup (default 20%, Settings → Valuation) covering what it costs to re-buy the card at retail. Each report has a **Show insurance replacement value** checkbox and its own %; it switches on automatically when Purpose is Insurance. When on, the PDF adds a Replacement column, a replacement total under the FMV total, a line in each card's value box, and a sentence in the methodology.

## How the value is calculated

1. Sold listings are filtered by title: card name and number must match, wrong grades / raw-vs-slab / other languages / lots, proxies and sealed product are dropped.
2. Sales older than the lookback window (default 120 days) are ignored; 130point/eBay duplicates are merged (130point kept since it shows actual best-offer prices). eBay best-offer sales are unchecked by default because eBay shows the list price.
3. Outliers are removed (IQR, never tighter than ±25% of median).
4. FMV = recency-weighted median of sales (weight halves every 30 days), blended 80/20 with guide values when there are 3+ sales; with 1–2 sales it's a 50/50 average; with none it falls back to guide values.
5. Confidence: High = 8+ consistent sales with one in the last 30 days; Medium = 4+ sales or 3+ across sources; otherwise Low.

Every comp can be checked/unchecked, deleted or added manually, and any card can get an appraiser override with a reason (shown on the PDF alongside what the market data said). All weights are adjustable in Settings → Valuation.

## Using it

1. **New report** → fill in customer + purpose (Insurance, Estate, Sale…).
2. **+ Add card** → name, set, number, variant, condition or grader/grade/cert → **Gather sales data** → review comps → Save.
   If TCGplayer picks the wrong printing, paste the correct TCGplayer product ID (the number in the product URL) and gather again.
3. Or add several cards, then **Value all**.
4. **Export PDF** → summary page, one page per card (image, details, value box, source breakdown, recent comps), methodology, disclaimer and signature line.

Settings: store info, logo, appraiser name, report number prefix, accent color, PriceCharting token, which sources to use, valuation weights, disclaimer text. Data lives in `%APPDATA%\LonestarValuator` (SQLite database, cached images, saved PDFs).

## Building the exe

**GitHub (automatic):** every push to `main` runs the tests, builds `LonestarValuator.exe` and publishes it as release `v<__version__>` (from `valuator/__init__.py`). Bump `__version__` to ship a new release; pushing without a bump just refreshes the current release's exe. **Help → Check for updates** in the app downloads newer releases and restarts itself (requires the releases to be publicly downloadable).

**Locally on Windows:** install Python 3.11+, double-click `build.bat` → `dist\LonestarValuator.exe`.

To bake your store logo into the exe, drop it in `assets/logo.png` before building (or just pick it in Settings).

## Development

```
pip install -r requirements.txt pytest
python main.py
python -m pytest tests
```
