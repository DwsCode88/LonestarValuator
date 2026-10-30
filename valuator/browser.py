"""Drives the PC's installed Google Chrome (falls back to Microsoft Edge) through Playwright.

Why: eBay, 130point, TCGplayer, PSA and CGC all treat a real browser better than a script –
fewer bot blocks, JavaScript-rendered data (CGC population), and saved sign-ins (Card Ladder).

Chrome runs with its own profile in %APPDATA%\\LonestarValuator\\chrome-profile (separate from the
user's normal Chrome, so both can be open). The window stays minimized and only comes forward
when a site needs a person – a sign-in or a "verify you are human" check.

All Playwright work happens on one background asyncio loop; other threads call `call()`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Callable, Optional

BOT_PATTERNS = [r"just a moment", r"attention required", r"verify you are human", r"are you a robot",
                r"pardon our interruption", r"access denied", r"captcha", r"security check",
                r"checking your browser", r"press (and|&) hold"]
WIN_POS_HIDDEN = {"windowState": "minimized"}
WIN_POS_SHOWN = {"left": 80, "top": 60, "width": 1300, "height": 900}


class BrowserUnavailable(RuntimeError):
    pass


class BrowserService:
    def __init__(self, profile_dir: Path, channel: str = "chrome", headless: bool = False):
        self.profile_dir = Path(profile_dir)
        self.channel = os.environ.get("LSV_BROWSER", channel)       # "chrome" | "msedge" | "chromium"
        self.headless = headless or os.environ.get("LSV_HEADLESS") == "1"
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._pw = None
        self.ctx = None
        self.used_channel = ""
        self.error = ""
        self._started = threading.Event()
        self._lock = threading.Lock()
        self._sem: Optional[asyncio.Semaphore] = None
        self._origin_pages: dict = {}
        self._visible_page = None
        self.on_attention: Optional[Callable[[str], None]] = None   # UI callback: site needs the user
        self.on_attention_done: Optional[Callable[[], None]] = None

    # ---------- lifecycle ----------
    def ensure_started(self, timeout: float = 60) -> None:
        with self._lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self._run_loop, name="chrome", daemon=True)
                self.thread.start()
        if not self._started.wait(timeout):
            raise BrowserUnavailable("Chrome took too long to start")
        if self.ctx is None:
            raise BrowserUnavailable(self.error or "Chrome could not be started")

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._launch())
        except Exception as e:  # report, don't crash the app
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self._started.set()
        if self.ctx is not None:
            self.loop.run_forever()

    async def _launch(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._sem = asyncio.Semaphore(4)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = ["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows", "--window-size=1300,900"]
        order = [self.channel] + [c for c in ("chrome", "msedge") if c != self.channel]
        errors = []
        for ch in order:
            try:
                kw = dict(user_data_dir=str(self.profile_dir), headless=self.headless, args=args,
                          no_viewport=True, accept_downloads=False,
                          ignore_default_args=["--enable-automation"])
                if ch != "chromium":
                    kw["channel"] = ch
                self.ctx = await self._pw.chromium.launch_persistent_context(**kw)
                self.used_channel = ch
                break
            except Exception as e:
                errors.append(f"{ch}: {str(e).splitlines()[0][:140]}")
        if self.ctx is None:
            self.error = ("Couldn't start Google Chrome or Microsoft Edge. Install Chrome, or close any "
                          "LonestarValuator window that's still open. (" + " | ".join(errors) + ")")
            await self._pw.stop()
            return
        await self.ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        await page.goto("about:blank")
        self._home = page
        await self._set_window(page, WIN_POS_HIDDEN)

    def call(self, coro_factory, timeout: float = 90):
        """Run `await coro_factory()` on the browser loop from any thread and return its result."""
        self.ensure_started()
        fut: Future = asyncio.run_coroutine_threadsafe(coro_factory(), self.loop)
        return fut.result(timeout)

    def close(self):
        if self.loop and self.ctx is not None:
            async def _close():
                try:
                    await self.ctx.close()
                    await self._pw.stop()
                except Exception:
                    pass
            try:
                asyncio.run_coroutine_threadsafe(_close(), self.loop).result(10)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)

    @property
    def running(self) -> bool:
        return self.ctx is not None

    # ---------- window ----------
    async def _set_window(self, page, bounds: dict):
        if self.headless:
            return
        try:
            cdp = await self.ctx.new_cdp_session(page)
            win = await cdp.send("Browser.getWindowForTarget")
            if bounds.get("windowState") != "minimized":
                await cdp.send("Browser.setWindowBounds", {"windowId": win["windowId"],
                                                            "bounds": {"windowState": "normal"}})
            await cdp.send("Browser.setWindowBounds", {"windowId": win["windowId"], "bounds": bounds})
            await cdp.detach()
        except Exception:
            pass

    async def _show(self, page):
        await self._set_window(page, WIN_POS_SHOWN)
        try:
            await page.bring_to_front()
        except Exception:
            pass

    async def _hide(self):
        page = self._home if getattr(self, "_home", None) and not self._home.is_closed() else \
            (self.ctx.pages[0] if self.ctx.pages else None)
        if page:
            await self._set_window(page, WIN_POS_HIDDEN)

    def show(self, url: str | None = None):
        """Bring Chrome forward, optionally opening url in a new tab (sign-ins, Card Ladder…)."""
        async def go():
            page = await self.ctx.new_page()
            if url:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    pass
            self._visible_page = page
            await self._show(page)
        self.call(go, 60)

    def hide(self):
        self.call(self._hide, 20)

    # ---------- bot checks ----------
    @staticmethod
    def _looks_blocked(title: str, text: str) -> bool:
        blob = f"{title} {text[:1500]}".lower()
        return any(re.search(p, blob) for p in BOT_PATTERNS)

    async def _handle_block(self, page, site: str, ok_selector: str | None, wait_s: int = 120):
        """Show the window so the user can pass the check, then hide again."""
        if self.on_attention:
            self.on_attention(f"{site} wants a quick human check – finish it in the Chrome window")
        await self._show(page)
        for _ in range(wait_s):
            await asyncio.sleep(1)
            try:
                if ok_selector and await page.query_selector(ok_selector):
                    break
                title = await page.title()
                text = await page.inner_text("body")
                if not self._looks_blocked(title, text):
                    break
            except Exception:
                continue
        await self._hide()
        if self.on_attention_done:
            self.on_attention_done()

    # ---------- page fetching ----------
    async def _get_html(self, url: str, wait_selector: str | None = None, settle_ms: int = 0,
                        timeout_ms: int = 45000, site: str = "") -> str:
        async with self._sem:
            page = await self.ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                title, text = await page.title(), await page.inner_text("body")
                if self._looks_blocked(title, text):
                    await self._handle_block(page, site or url.split("/")[2], wait_selector)
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=min(timeout_ms, 20000))
                    except Exception:
                        pass
                if settle_ms:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=settle_ms)
                    except Exception:
                        pass
                return await page.content()
            finally:
                await page.close()

    def get_html(self, url: str, wait_selector: str | None = None, settle_ms: int = 0, site: str = "",
                 timeout: float = 150) -> str:
        return self.call(lambda: self._get_html(url, wait_selector, settle_ms, site=site), timeout)

    async def _origin_page(self, origin_url: str):
        key = origin_url.split("/")[2]
        page = self._origin_pages.get(key)
        if page is None or page.is_closed():
            page = await self.ctx.new_page()
            await page.goto(origin_url, wait_until="domcontentloaded", timeout=45000)
            title, text = await page.title(), await page.inner_text("body")
            if self._looks_blocked(title, text):
                await self._handle_block(page, key, None)
            self._origin_pages[key] = page
        return page

    async def _fetch(self, origin_url: str, url: str, method: str, body, headers: dict, as_json: bool):
        async with self._sem:
            page = await self._origin_page(origin_url)
            res = await page.evaluate(
                """async ([url, method, body, headers]) => {
                    const r = await fetch(url, {method, headers, body: body === null ? undefined : body,
                                                credentials: 'include'});
                    return {status: r.status, text: await r.text()};
                }""", [url, method, body, headers])
        if res["status"] >= 400:
            raise RuntimeError(f"HTTP {res['status']} from {url.split('/')[2]}")
        return json.loads(res["text"]) if as_json else res["text"]

    def fetch(self, origin_url: str, url: str, method: str = "GET", body=None, headers: dict | None = None,
              as_json: bool = True, timeout: float = 120):
        """fetch() from inside a page on origin_url – uses that site's cookies like the website itself."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
            headers = {"Content-Type": "application/json", **(headers or {})}
        return self.call(lambda: self._fetch(origin_url, url, method, body, headers or {}, as_json), timeout)

    def capture_visible(self) -> tuple[str, str]:
        """HTML + URL of the tab the user is looking at (for Card Ladder and other capture)."""
        async def grab():
            pages = [p for p in self.ctx.pages if not p.is_closed() and p.url not in ("about:blank", "")]
            pages = [p for p in pages if p not in self._origin_pages.values()]
            page = self._visible_page if self._visible_page and not self._visible_page.is_closed() else \
                (pages[-1] if pages else None)
            if page is None:
                return "", ""
            return await page.content(), page.url
        return self.call(grab, 30)


_service: Optional[BrowserService] = None


def service(settings: dict | None = None) -> Optional[BrowserService]:
    """The shared Chrome instance, or None if browser mode is off / Playwright isn't installed."""
    global _service
    settings = settings or {}
    if not settings.get("use_browser", True):
        return None
    if _service is None:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return None
        from .settings import data_dir
        _service = BrowserService(data_dir() / "chrome-profile", settings.get("browser_channel", "chrome"))
    return _service


def shutdown():
    if _service is not None:
        _service.close()
