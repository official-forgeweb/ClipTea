import asyncio
import random
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from playwright.async_api import Page
from anti_detection.proxy_rotator import ProxyRotator
from anti_detection.rate_limiter import RateLimiter
from anti_detection.stealth import create_stealth_browser, apply_stealth_scripts
from anti_detection.bandwidth_optimizer import BandwidthOptimizer
from anti_detection.fingerprint import FingerprintGenerator


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    def __init__(self, proxy_rotator: ProxyRotator, rate_limiter: RateLimiter):
        self.proxy_rotator = proxy_rotator
        self.rate_limiter = rate_limiter
        self.fingerprint_gen = FingerprintGenerator()
        self.browser = None
        self.context = None

    async def _setup_browser(self, use_proxy: bool = True):
        """Creates a stealth browser, optionally with a proxy."""
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()

        proxy = None
        if use_proxy:
            proxy = await self.proxy_rotator.get_proxy()

        if proxy:
            print(f"[SCRAPER] Using proxy: {proxy.get('server', 'unknown')}")
        else:
            print("[SCRAPER] Using direct connection (no proxy)")

        self.browser = await create_stealth_browser(self.playwright, proxy=proxy)

        fingerprint = self.fingerprint_gen.get_fingerprint()

        self.context = await self.browser.new_context(
            user_agent=fingerprint["user_agent"],
            viewport=fingerprint["viewport"],
            timezone_id=fingerprint["timezone_id"],
            locale=fingerprint["locale"],
            device_scale_factor=fingerprint["device_scale_factor"]
        )

        await apply_stealth_scripts(self.context)
        return self.context

    async def _create_optimized_page(self, use_proxy: bool = True) -> Page:
        """Creates a page with bandwidth optimization enabled."""
        if not self.context:
            await self._setup_browser(use_proxy=use_proxy)

        page = await self.context.new_page()
        optimizer = BandwidthOptimizer()
        await page.route("**/*", optimizer.route_handler)
        return page

    async def _teardown_browser(self):
        """Cleans up browser resources and resets state for reuse."""
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if hasattr(self, 'playwright') and self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        self.context = None
        self.browser = None
        self.playwright = None

    async def _human_like_delay(self):
        """Random wait between 1.5 to 4 seconds to mimic human behavior."""
        await asyncio.sleep(random.uniform(1.5, 4.0))

    async def _random_scroll(self, page: Page):
        """Scrolls the page a random amount to mimic human browsing."""
        scroll_amount = random.randint(300, 800)
        await page.mouse.wheel(0, scroll_amount)
        await self._human_like_delay()

    @abstractmethod
    async def scrape_user_posts(self, username: str, max_posts: int) -> List[Dict]:
        """Scrapes recent posts for a user."""
        pass

    @abstractmethod
    async def scrape_post_metrics(self, post_url: str) -> Optional[Dict]:
        """Scrapes detailed metrics for a single post."""
        pass

    @abstractmethod
    async def scrape_single_video(self, video_url: str) -> Optional[Dict]:
        """
        Scrape a single video page and extract:
        - author_username: the username of who posted this video
        - views, likes, comments, shares
        - caption, video_id, platform
        
        Returns dict with all fields or None on failure.
        """
        pass
