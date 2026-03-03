import asyncio
import sys
import time
import json
import re
import os
import aiohttp
from playwright.async_api import async_playwright

TEST_URLS = ["https://x.com/X/status/1806305018693755353"]
FREE_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
]

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

class TwitterTestScraper:
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

    async def method_1_official_api(self, tweet_id: str) -> dict:
        res = {"success": False, "data": {}}
        token = os.environ.get("TWITTER_BEARER_TOKEN")
        if not token:
            res["error"] = "TWITTER_BEARER_TOKEN not set"
            return res
            
        url = f"https://api.twitter.com/2/tweets?ids={tweet_id}&tweet.fields=public_metrics"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as req:
                    if req.status == 200:
                        data = await req.json()
                        metrics = data.get("data", [{}])[0].get("public_metrics", {})
                        if metrics:
                            res["data"]["views"] = metrics.get("impression_count")
                            res["data"]["likes"] = metrics.get("like_count")
                            res["data"]["replies"] = metrics.get("reply_count")
                            res["data"]["retweets"] = metrics.get("retweet_count")
                            res["success"] = True
                    else:
                        res["error"] = f"API Error: {req.status}"
        except Exception as e:
            res["error"] = str(e)
        return res

    async def method_2_intercept_api(self, page) -> dict:
        res = {"success": False, "data": {}}
        try:
            for r in self.intercepted_responses:
                if "TweetResultByRestId" in r.url:
                    try:
                        data = await r.json()
                        text = json.dumps(data)
                        views = re.search(r'"views":\s*\{\s*"count":\s*"(\d+)"', text)
                        likes = re.search(r'"favorite_count":\s*(\d+)', text)
                        replies = re.search(r'"reply_count":\s*(\d+)', text)
                        retweets = re.search(r'"retweet_count":\s*(\d+)', text)
                        
                        if views or likes or replies or retweets:
                            if views: res["data"]["views"] = views.group(1)
                            if likes: res["data"]["likes"] = likes.group(1)
                            if replies: res["data"]["replies"] = replies.group(1)
                            if retweets: res["data"]["retweets"] = retweets.group(1)
                            res["success"] = True
                            return res
                    except: pass
            res["error"] = "TweetResultByRestId API response not found or not parsed"
        except Exception as e: res["error"] = str(e)
        return res

    async def scrape_post(self, url: str):
        proxy = await self.fetch_free_proxy()
        proxy_server = {"server": f"http://{proxy}"} if proxy else None
        
        start_time = time.time()
        
        # Extract tweet ID
        tweet_id_match = re.search(r'status/(\d+)', url)
        tweet_id = tweet_id_match.group(1) if tweet_id_match else ""
        
        m1 = await self.method_1_official_api(tweet_id)
        if m1["success"]:
            return {
                "proxy": "None (Official API)", "title": "API Direct", "load_time": time.time() - start_time,
                "total_time": time.time() - start_time, "bandwidth": 0, "extracted": m1["data"],
                "m1": m1, "m2": {"success": False, "error": "Skipped because API worked"}
            }

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
            
            m2 = await self.method_2_intercept_api(page)
            
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
    url = url or (input("Enter Twitter/X URL: ") if sys.stdin.isatty() else TEST_URLS[0])
    scraper = TwitterTestScraper()
    print("Starting Twitter/X Scraper Test...")
    res = await scraper.scrape_post(url)
    
    success = bool(res['extracted'])
    
    print("\n══════════════════════════════════════════")
    print("TWITTER/X SCRAPE TEST RESULTS")
    print("══════════════════════════════════════════")
    print(f"URL: {url}")
    print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}\n")
    
    print("── Extracted Data ──")
    print(f"Views:     {res['extracted'].get('views', 'Not found')}")
    print(f"Likes:     {res['extracted'].get('likes', 'Not found')}")
    print(f"Replies:   {res['extracted'].get('replies', 'Not found')}")
    print(f"Retweets:  {res['extracted'].get('retweets', 'Not found')}")
    
    print("\n── Method Results ──")
    print(f"Method 1 (Official API):   {'✅ Found' if res['m1']['success'] else '❌ ' + res['m1'].get('error', '')}")
    print(f"Method 2 (API Intercept):  {'✅ Found' if res['m2']['success'] else '❌ ' + res['m2'].get('error', '')}")
    
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
