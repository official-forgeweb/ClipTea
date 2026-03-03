import asyncio
import sys
import time
import json
import re
import os
import random
import argparse
import aiohttp
from playwright.async_api import async_playwright

# ── Configuration ──
FREE_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]

STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
"""

class InstagramTestScraper:
    def __init__(self):
        self.intercepted_responses = []
        self.bandwidth_used = 0
        self.user_data_dir = os.path.join(os.getcwd(), "ig_user_data")
        if not os.path.exists(self.user_data_dir):
            os.makedirs(self.user_data_dir)

    async def fetch_free_proxies(self, count=5) -> list[str]:
        found = []
        async with aiohttp.ClientSession() as session:
            for source in FREE_PROXY_SOURCES:
                try:
                    async with session.get(source, timeout=10) as response:
                        if response.status == 200:
                            text = await response.text()
                            proxies = [p.strip() for p in text.split('\n') if p.strip() and ':' in p]
                            found.extend(proxies)
                except: continue
        return found[:count]

    async def _test_proxy(self, proxy: str) -> bool:
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get("http://www.google.com", proxy=f"http://{proxy}", timeout=5) as resp:
                    return resp.status == 200
        except: return False

    def handle_response(self, response):
        self.intercepted_responses.append(response)

    async def scrape_post(self, url: str, headless: bool = True) -> dict:
        print(f"Attempting scraping for: {url}")
        
        # 1. Try Direct first
        print("Step 1: Attempting direct connection with persistent session...")
        res = await self._run_browser(url, None, headless=headless)
        
        if res.get("extracted") and (res["extracted"].get("likes") or res["extracted"].get("views")):
            print("Successfully scraped metrics!")
            return res
            
        # 2. Try Proxies ONLY if directly blocked
        if not headless: # Don't try proxies during manual login
            return res

        print("Step 2: Direct failed/blocked. Trying proxy rotation...")
        proxies = await self.fetch_free_proxies(3)
        for proxy in proxies:
            print(f"Testing proxy: {proxy}")
            if await self._test_proxy(proxy):
                p_res = await self._run_browser(url, proxy, headless=True)
                if p_res.get("extracted") and (p_res["extracted"].get("likes") or p_res["extracted"].get("views")):
                    return p_res
        
        return res

    async def _run_browser(self, url: str, proxy: str | None, headless: bool = True) -> dict:
        self.intercepted_responses = []
        self.bandwidth_used = 0
        proxy_server = {"server": f"http://{proxy}"} if proxy else None
        start_time = time.time()
        
        async with async_playwright() as p:
            # Use Persistent Context to keep user logged in
            context = await p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=headless,
                proxy=proxy_server,
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                args=["--disable-blink-features=AutomationControlled"]
            )
            
            page = await context.new_page()
            await context.add_init_script(STEALTH_JS)
            page.on("response", self.handle_response)
            
            load_start = time.time()
            nav_err = None
            try:
                await page.goto(url, wait_until="load", timeout=30000)
                await page.wait_for_timeout(5000) # Extra wait for dynamic metrics
            except Exception as e: nav_err = str(e)
            
            load_time = time.time() - load_start
            title = await page.title()
            
            # Logic to check if we are stuck on a login screen
            is_login = False
            if "login" in page.url.lower() or "Post isn't available" in title:
                is_login = True

            # Methods
            m1 = await self.method_1_meta_tags(page)
            m3 = await self.method_3_intercept_api(page)
            m4 = await self.method_4_html_parsing(page)
            m5 = await self.method_5_ld_json(page)
            
            # Bandwidth
            for r in self.intercepted_responses:
                try: self.bandwidth_used += int((await r.all_headers()).get("content-length", 0))
                except: pass
            
            await context.close()
            total_time = time.time() - start_time
            
            extracted = {}
            for m in [m1, m3, m4, m5]:
                if m.get("success"): extracted.update(m.get("data", {}))

            return {
                "proxy": proxy, "title": title, "load_time": load_time, "total_time": total_time,
                "bandwidth": self.bandwidth_used / (1024*1024), "extracted": extracted,
                "m1": m1, "m3": m3, "m4": m4, "m5": m5, "nav_err": nav_err, "is_login": is_login
            }

    async def method_1_meta_tags(self, page) -> dict:
        res = {"success": False, "data": {}, "desc": ""}
        try:
            og_desc = await page.evaluate("() => document.querySelector('meta[property=\"og:description\"]')?.content")
            desc = await page.evaluate("() => document.querySelector('meta[name=\"description\"]')?.content")
            res["desc"] = str(desc or og_desc or '')[:500]
            if og_desc:
                l = re.search(r'([0-9,BMK.]+)\s*(?:likes|Likes)', og_desc)
                c = re.search(r'([0-9,BMK.]+)\s*(?:comments|Comments)', og_desc)
                v = re.search(r'([0-9,BMK.]+)\s*(?:views|Views|plays|Plays)', og_desc)
                if l: res["data"]["likes"] = l.group(1)
                if c: res["data"]["comments"] = c.group(1)
                if v: res["data"]["views"] = v.group(1)
            if res["data"]: res["success"] = True
        except: pass
        return res

    async def method_3_intercept_api(self, page) -> dict:
        res = {"success": False, "data": {}}
        try:
            for r in self.intercepted_responses:
                if any(x in r.url for x in ["graphql", "api/v1"]):
                    try:
                        t = (await r.text()).lower()
                        v = re.search(r'"(?:video_view_count|play_count)":\s*([0-9]+)', t)
                        l = re.search(r'"(?:like_count)":\s*([0-9]+)', t)
                        if v: res["data"]["views"] = v.group(1)
                        if l: res["data"]["likes"] = l.group(1)
                        if res["data"]: res["success"] = True
                    except: pass
        except: pass
        return res

    async def method_4_html_parsing(self, page) -> dict:
        res = {"success": False, "data": {}}
        try:
            v = await page.evaluate(r"""() => {
                const els = Array.from(document.querySelectorAll('span, div'));
                for (const el of els) {
                    const t = el.textContent || '';
                    if (t.toLowerCase().includes('views') && /[0-9,.]+/.test(t)) {
                        const m = t.match(/([0-9,.]+)\s*views/i);
                        if (m) return m[1];
                    }
                }
                return null;
            }""")
            if v: res["data"]["views"] = v; res["success"] = True
        except: pass
        return res

    async def method_5_ld_json(self, page) -> dict:
        res = {"success": False, "data": {}}
        try:
            lds = await page.evaluate("() => Array.from(document.querySelectorAll('script[type=\"application/ld+json\"]')).map(s => s.textContent)")
            for ld in lds:
                data = json.loads(ld)
                stats = data.get("interactionStatistic") or []
                if isinstance(stats, dict): stats = [stats]
                for s in stats:
                    count = s.get("userInteractionCount")
                    type_str = s.get("interactionType", "")
                    if "LikeAction" in type_str: res["data"]["likes"] = count
                if res["data"]: res["success"] = True; break
        except: pass
        return res

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", help="Instagram URL")
    parser.add_argument("--login", action="store_true", help="Open browser to login manually")
    args = parser.parse_args()

    scraper = InstagramTestScraper()
    
    if args.login:
        print("Starting manual login session...")
        print("A browser window will open. Login to Instagram manually, then close the window.")
        await scraper.scrape_post("https://www.instagram.com/accounts/login/", headless=False)
        print("Login session saved. You can now run the scraper normally.")
        return

    url = args.url or "https://www.instagram.com/reel/Cn2M6X3A_H8/"
    print("Starting Instagram Scraper Test...")
    res = await scraper.scrape_post(url)
    
    success = bool(res['extracted'])
    print("\n══════════════════════════════════════════")
    print("INSTAGRAM SCRAPE TEST RESULTS")
    print("══════════════════════════════════════════")
    print(f"URL: {url}")
    print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}\n")
    print(f"Views:     {res['extracted'].get('views', 'Not found')}")
    print(f"Likes:     {res['extracted'].get('likes', 'Not found')}")
    print(f"Comments:  {res['extracted'].get('comments', 'Not found')}")
    print(f"Debug: Proxy={res['proxy'] or 'None'}, LoginWall={'YES' if res['is_login'] else 'No'}")
    print("══════════════════════════════════════════\n")

if __name__ == "__main__":
    asyncio.run(main())
