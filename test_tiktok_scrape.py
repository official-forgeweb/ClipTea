import asyncio
import sys
import time
import json
import re
import aiohttp
from playwright.async_api import async_playwright

TEST_URLS = ["https://www.tiktok.com/@tiktok/video/7199997194689039659"]
FREE_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
]

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
"""

class TikTokTestScraper:
    def __init__(self):
        self.bandwidth_used = 0
        self.intercepted_responses = []

    async def fetch_free_proxy(self):
        async with aiohttp.ClientSession() as session:
            for source in FREE_PROXY_SOURCES:
                try:
                    async with session.get(source, timeout=5) as response:
                        if response.status == 200:
                            proxies = [p for p in (await response.text()).split() if p.strip()]
                            if proxies: return proxies[0]
                except: continue
        return None

    def handle_response(self, response):
        self.intercepted_responses.append(response)

    async def method_1_sigi_state(self, page) -> dict:
        res = {"success": False, "data": {}}
        try:
            sigi = await page.evaluate("() => document.querySelector('#SIGI_STATE')?.textContent")
            if sigi:
                data = json.loads(sigi)
                item_module = data.get("ItemModule", {})
                for key, val in item_module.items():
                    stats = val.get("stats", {})
                    if stats:
                        res["data"]["views"] = stats.get("playCount")
                        res["data"]["likes"] = stats.get("diggCount")
                        res["data"]["comments"] = stats.get("commentCount")
                        res["data"]["shares"] = stats.get("shareCount")
                        res["success"] = True
                        return res
            res["error"] = "SIGI_STATE not found or no stats"
        except Exception as e: res["error"] = str(e)
        return res

    async def method_2_universal_data(self, page) -> dict:
        res = {"success": False, "data": {}}
        try:
            univ = await page.evaluate("() => document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent")
            if univ:
                data = json.loads(univ)
                stats = data.get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {}).get("stats", {})
                if stats:
                    res["data"]["views"] = stats.get("playCount")
                    res["data"]["likes"] = stats.get("diggCount")
                    res["data"]["comments"] = stats.get("commentCount")
                    res["data"]["shares"] = stats.get("shareCount")
                    res["success"] = True
                    return res
            res["error"] = "UNIVERSAL_DATA not found"
        except Exception as e: res["error"] = str(e)
        return res

    async def scrape_post(self, url: str):
        proxy = await self.fetch_free_proxy()
        proxy_server = {"server": f"http://{proxy}"} if proxy else None
        
        start_time = time.time()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, proxy=proxy_server)
            context = await browser.new_context(viewport={"width": 1280, "height": 720}, user_agent="Mozilla/5.0")
            await context.add_init_script(STEALTH_JS)
            page = await context.new_page()
            page.on("response", self.handle_response)
            
            load_start = time.time()
            try: await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except: pass
            
            await page.wait_for_timeout(3000)
            load_time = time.time() - load_start
            title = await page.title()
            
            m1 = await self.method_1_sigi_state(page)
            m2 = await self.method_2_universal_data(page)
            
            for r in self.intercepted_responses:
                try: self.bandwidth_used += int((await r.all_headers()).get("content-length", 0))
                except: pass
            
            await browser.close()
            total_time = time.time() - start_time
            
            extracted = m1.get("data", {}) if m1.get("success") else m2.get("data", {})
            return {
                "proxy": proxy, "title": title, "load_time": load_time, "total_time": total_time,
                "bandwidth": self.bandwidth_used / (1024*1024), "extracted": extracted, "m1": m1, "m2": m2
            }

async def main(url):
    url = url or (input("Enter TikTok URL: ") if sys.stdin.isatty() else TEST_URLS[0])
    scraper = TikTokTestScraper()
    print("Starting TikTok Scraper Test...")
    res = await scraper.scrape_post(url)
    
    success = bool(res['extracted'])
    
    print("\n══════════════════════════════════════════")
    print("TIKTOK SCRAPE TEST RESULTS")
    print("══════════════════════════════════════════")
    print(f"URL: {url}")
    print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}\n")
    
    print("── Extracted Data ──")
    print(f"Views:     {res['extracted'].get('views', 'Not found')}")
    print(f"Likes:     {res['extracted'].get('likes', 'Not found')}")
    print(f"Comments:  {res['extracted'].get('comments', 'Not found')}")
    print(f"Shares:    {res['extracted'].get('shares', 'Not found')}")
    
    print("\n── Method Results ──")
    print(f"Method 1 (SIGI_STATE):     {'✅ Found' if res['m1']['success'] else '❌ ' + res['m1'].get('error', '')}")
    print(f"Method 2 (Universal Data): {'✅ Found' if res['m2']['success'] else '❌ ' + res['m2'].get('error', '')}")
    
    print("\n── Debug Info ──")
    print(f"Proxy Used:     {res['proxy'] or 'None (Direct)'}")
    print(f"Page Title:     {res['title']}")
    print(f"Page Load Time: {res['load_time']:.2f} seconds")
    print(f"Total Time:     {res['total_time']:.2f} seconds")
    print(f"Bandwidth:      {res['bandwidth']:.2f} MB")
    print("══════════════════════════════════════════\n")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(url))
