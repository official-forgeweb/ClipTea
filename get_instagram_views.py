#!/usr/bin/env python3
"""
Instagram View Count Extraction
================================
Extracts view counts from Instagram video/reel URLs using Webshare proxies.
Implements a 6-step waterfall strategy to safely and reliably extract data.

Usage:
    python get_instagram_views.py
    python get_instagram_views.py https://www.instagram.com/reel/ABC123/
"""

import asyncio
import aiohttp
import json
import re
import sys
import os
import random
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

# ──────────────────────────────────────────────────────────────
# ANSI color helpers
# ──────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

def ok(msg):   return f"{GREEN}✅ {msg}{RESET}"
def fail(msg): return f"{RED}❌ {msg}{RESET}"
def warn(msg): return f"{YELLOW}⚠️  {msg}{RESET}"
def info(msg): return f"{CYAN}ℹ️  {msg}{RESET}"
def skip(msg): return f"{DIM}⏭️  {msg}{RESET}"

# ──────────────────────────────────────────────────────────────
# Proxy Loader
# ──────────────────────────────────────────────────────────────
PROXY_FILE = os.path.join(os.path.dirname(__file__), "proxies.txt")

def load_proxies() -> List[str]:
    """Load proxies from proxies.txt (format: http://user:pass@ip:port)."""
    if not os.path.exists(PROXY_FILE):
        return []
    with open(PROXY_FILE, "r") as f:
        proxies = [line.strip() for line in f if line.strip()]
    return proxies

def get_random_proxy_url(proxies: List[str]) -> Optional[str]:
    """Return a random proxy URL string for aiohttp (http://user:pass@ip:port)."""
    if not proxies:
        return None
    proxy = random.choice(proxies)
    if not proxy.startswith("http"):
        proxy = f"http://{proxy}"
    return proxy

def get_playwright_proxy(proxies: List[str]) -> Optional[dict]:
    """Return a random proxy dict for Playwright with separated auth."""
    if not proxies:
        return None
    proxy = random.choice(proxies)
    if not proxy.startswith("http"):
        proxy = f"http://{proxy}"
    parsed = urlparse(proxy)
    result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username and parsed.password:
        result["username"] = parsed.username
        result["password"] = parsed.password
    return result

# ──────────────────────────────────────────────────────────────
# Constants & Stealth Setup
# ──────────────────────────────────────────────────────────────
REALISTIC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate", # No brotli to ensure compatibility
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { 0: {type: "application/x-google-chrome-pdf"}, description: "PDF", filename: "internal-pdf-viewer", length: 1, name: "Chrome PDF Plugin" },
        { 0: {type: "application/pdf"}, description: "", filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai", length: 1, name: "Chrome PDF Viewer" },
    ],
});
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""

# ──────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────
def extract_shortcode(url: str) -> str:
    """Extract shortcode from any Instagram URL format."""
    patterns = [
        r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract shortcode from: {url}")

def parse_count(text: str) -> int:
    """Parse human-readable counts into integers."""
    if not text:
        return 0
    text = text.strip().lower()
    text = re.sub(r'[^0-9.kmb]', '', text)
    try:
        if 'b' in text:
            return int(float(text.replace('b', '')) * 1_000_000_000)
        if 'm' in text:
            return int(float(text.replace('m', '')) * 1_000_000)
        if 'k' in text:
            return int(float(text.replace('k', '')) * 1_000)
        return int(float(text))
    except ValueError:
        return 0

def deep_find_key(data: Any, target_key: str) -> Optional[int]:
    """Recursively search a nested dict/list for a key."""
    if isinstance(data, dict):
        if target_key in data:
            val = data[target_key]
            if isinstance(val, (int, str)):
                 try:
                     return int(val)
                 except (ValueError, TypeError):
                     pass
        for value in data.values():
            result = deep_find_key(value, target_key)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = deep_find_key(item, target_key)
            if result is not None:
                return result
    return None


class InstagramViewScraper:
    def __init__(self):
        self.proxies = load_proxies()
        if self.proxies:
            print(f"  {info(f'Loaded {len(self.proxies)} Webshare proxies from proxies.txt')}")
        else:
            print(f"  {warn('No proxies found in proxies.txt — will use direct connections')}")

    def _get_aiohttp_proxy(self) -> Optional[str]:
        return get_random_proxy_url(self.proxies)

    def _get_pw_proxy(self) -> Optional[dict]:
        return get_playwright_proxy(self.proxies)

    async def method_1_embed_deep_parse(self, shortcode: str) -> dict:
        """Method 1: Deep parse the embed page HTML (No browser, WITH proxy)."""
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
        captioned_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        
        headers = REALISTIC_HEADERS.copy()
        headers.update({
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Referer": "https://www.google.com/",
        })
        
        result = {"views": 0, "likes": 0, "comments": 0, "author": ""}
        proxy_url = self._get_aiohttp_proxy()
        
        async with aiohttp.ClientSession() as session:
            for url in [captioned_url, embed_url]:
                try:
                    async with session.get(url, headers=headers, proxy=proxy_url,
                                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        html = await resp.text()
                        
                        # SEARCH PATTERN 1: regex matching for views
                        view_patterns = [
                            r'"video_view_count"\s*:\s*(\d+)',
                            r'"view_count"\s*:\s*(\d+)',
                            r'"play_count"\s*:\s*(\d+)',
                            r'"video_views"\s*:\s*(\d+)',
                        ]
                        for pattern in view_patterns:
                            match = re.search(pattern, html)
                            if match:
                                views = int(match.group(1))
                                if views > 0:
                                    result["views"] = views
                                    break
                                    
                        # SEARCH PATTERN 2: gql_data
                        gql_match = re.search(r'"gql_data"\s*:\s*(\{".*?"shortcode_media"\s*:\s*\{.*?\}\})', html, re.DOTALL)
                        if gql_match:
                            try:
                                gql_text = gql_match.group(1)
                                vc_match = re.search(r'"video_view_count"\s*:\s*(\d+)', gql_text)
                                if vc_match:
                                    result["views"] = int(vc_match.group(1))
                            except:
                                pass
                                
                        # SEARCH PATTERN 3: additionalDataLoaded
                        add_match = re.search(r'window\.__additionalDataLoaded\s*\(\s*[\'"][^\'"]*[\'"]\s*,\s*(\{.*?\})\s*\)', html, re.DOTALL)
                        if add_match:
                            try:
                                data = json.loads(add_match.group(1))
                                media = data.get("graphql", {}).get("shortcode_media", {})
                                if media.get("video_view_count"):
                                    result["views"] = media["video_view_count"]
                            except:
                                pass
                                
                        # SEARCH PATTERN 4: LD+JSON
                        ld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
                        if ld_match:
                            try:
                                ld_data = json.loads(ld_match.group(1))
                                stats = ld_data.get("interactionStatistic", [])
                                if isinstance(stats, list):
                                    for stat in stats:
                                        if stat.get("interactionType", {}).get("@type") == "WatchAction":
                                            result["views"] = int(stat.get("userInteractionCount", 0))
                                elif isinstance(stats, dict):
                                    if stats.get("interactionType", {}).get("@type") == "WatchAction":
                                         result["views"] = int(stats.get("userInteractionCount", 0))
                            except:
                                pass

                        # Extract likes, comments, author
                        if not result["likes"]:
                            like_match = re.search(r'"like_count"\s*:\s*(\d+)', html)
                            if like_match: result["likes"] = int(like_match.group(1))
                            elif re.search(r'([\d,]+)\s+likes', html):
                                result["likes"] = parse_count(re.search(r'([\d,]+)\s+likes', html).group(1))

                        if not result["comments"]:
                            comment_match = re.search(r'"comment_count"\s*:\s*(\d+)', html)
                            if comment_match: result["comments"] = int(comment_match.group(1))
                            elif re.search(r'([\d,]+)\s+comments', html):
                                result["comments"] = parse_count(re.search(r'([\d,]+)\s+comments', html).group(1))
                                
                        if not result["author"]:
                            author_match = re.search(r'"username"\s*:\s*"([^"]+)"', html)
                            if author_match: result["author"] = author_match.group(1)

                        if result["views"] > 0:
                            break

                except Exception as e:
                    continue
                    
        return result

    async def method_2_media_info(self, shortcode: str) -> dict:
        """Method 2: Instagram media info endpoint (WITH proxy)."""
        def shortcode_to_media_id(shortcode: str) -> int:
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            media_id = 0
            for char in shortcode:
                media_id = media_id * 64 + alphabet.index(char)
            return media_id
            
        try:
            media_id = shortcode_to_media_id(shortcode)
        except ValueError:
            return {"views": 0, "likes": 0, "comments": 0, "author": ""}
            
        info_url = f"https://i.instagram.com/api/v1/media/{media_id}/info/"
        headers = {
            "User-Agent": "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100; en_US; 458229258)",
            "X-IG-App-ID": "936619743392459",
            "X-IG-WWW-Claim": "0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        }
        proxy_url = self._get_aiohttp_proxy()
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(info_url, headers=headers, proxy=proxy_url,
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        if items:
                            item = items[0]
                            return {
                                "views": item.get("view_count", 0) or item.get("play_count", 0),
                                "likes": item.get("like_count", 0),
                                "comments": item.get("comment_count", 0),
                                "author": item.get("user", {}).get("username", ""),
                            }
            except Exception:
                pass
                
        return {"views": 0, "likes": 0, "comments": 0, "author": ""}

    async def method_3_graphql(self, shortcode: str) -> dict:
        """Method 3: Instagram Web GraphQL (WITH proxy)."""
        query_hashes = [
            "2c4c2e343a8f64c625ba02b2aa12c7f8",
            "b3055c01b4b222b8a47dc12b090e4e64",
            "9f8827793ef34641b2fb195d4d41151c",
        ]
        
        headers = REALISTIC_HEADERS.copy()
        headers.update({
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "X-ASBD-ID": "129477",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Referer": "https://www.instagram.com/",
        })
        
        variables = json.dumps({"shortcode": shortcode})
        proxy_url = self._get_aiohttp_proxy()
        
        async with aiohttp.ClientSession() as session:
            for query_hash in query_hashes:
                try:
                    url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={variables}"
                    async with session.get(url, headers=headers, proxy=proxy_url,
                                           timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            media = data.get("data", {}).get("shortcode_media", {})
                            if media:
                                views = media.get("video_view_count", 0) or media.get("play_count", 0)
                                if views:
                                    return {
                                        "views": views,
                                        "likes": media.get("edge_media_preview_like", {}).get("count", 0),
                                        "comments": media.get("edge_media_to_parent_comment", {}).get("count", 0),
                                        "author": media.get("owner", {}).get("username", ""),
                                    }
                except Exception:
                    continue
        
        return {"views": 0, "likes": 0, "comments": 0, "author": ""}

    async def method_4_embed_browser(self, shortcode: str) -> dict:
        """Method 4: Load EMBED page in a stealth browser WITH proxy."""
        result = {"views": 0, "likes": 0, "comments": 0, "author": ""}
        captured_data = []
        pw_proxy = self._get_pw_proxy()

        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            
            launch_opts = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ]
            }
            if pw_proxy:
                launch_opts["proxy"] = pw_proxy
                proxy_server = pw_proxy['server']
                print(f"    {info(f'Using proxy: {proxy_server}')}")
            
            browser = await pw.chromium.launch(**launch_opts)
            context = await browser.new_context(
                user_agent=REALISTIC_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            await context.add_init_script(STEALTH_JS)
            page = await context.new_page()

            async def on_response(response):
                url = response.url
                if any(keyword in url for keyword in ['graphql', 'query', 'media', 'api/v1', 'web_info']):
                    try:
                        data = await response.json()
                        captured_data.append({"url": url, "data": data})
                    except:
                        try:
                            text = await response.text()
                            captured_data.append({"url": url, "text": text})
                        except:
                            pass

            page.on("response", on_response)

            embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
            await page.goto(embed_url, timeout=30000, wait_until="networkidle")
            await asyncio.sleep(random.uniform(3, 5))

            # A: Rendered HTML
            view_selectors = [
                 'span:has-text("views")', 'span:has-text("plays")',
                 '[aria-label*="view"]', '[aria-label*="play"]', 'span.vcOH2'
            ]
            for selector in view_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for el in elements:
                        text = await el.text_content()
                        if text:
                            views = parse_count(text)
                            if views > 0:
                                result["views"] = views
                                break
                except:
                     pass
                if result["views"] > 0: break

            # B: JS context
            if result["views"] == 0:
                try:
                    js_data = await page.evaluate("""() => {
                        let data = {};
                        if (window.__additionalDataLoaded) data.additionalData = window.__additionalDataLoaded;
                        const scripts = document.querySelectorAll('script');
                        for (const script of scripts) {
                            const text = script.textContent || '';
                            const vMatch = text.match(/"video_view_count"\\s*:\\s*(\\d+)/);
                            if (vMatch) data.video_view_count = parseInt(vMatch[1]);
                            const vMatch2 = text.match(/"view_count"\\s*:\\s*(\\d+)/);
                            if (vMatch2) data.view_count = parseInt(vMatch2[1]);
                            const pMatch = text.match(/"play_count"\\s*:\\s*(\\d+)/);
                            if (pMatch) data.play_count = parseInt(pMatch[1]);
                            if (text.includes('gql_data')) {
                                const gqlMatch = text.match(/gql_data\\s*[=:]\\s*(\\{.*?\\});/s);
                                if (gqlMatch) {
                                    try { data.gql_data = JSON.parse(gqlMatch[1]); } catch(e) {}
                                }
                            }
                        }
                        const ldJson = document.querySelector('script[type="application/ld+json"]');
                        if (ldJson) {
                            try { data.ld_json = JSON.parse(ldJson.textContent); } catch(e) {}
                        }
                        return data;
                    }""")
                    
                    if js_data:
                        views = js_data.get("video_view_count") or js_data.get("view_count") or js_data.get("play_count") or 0
                        if views > 0: result["views"] = views
                        
                        gql = js_data.get("gql_data", {})
                        if gql:
                            media = gql.get("shortcode_media") or gql.get("data", {}).get("shortcode_media") or {}
                            if media.get("video_view_count"): result["views"] = media["video_view_count"]
                            if media.get("edge_media_preview_like", {}).get("count"): result["likes"] = media["edge_media_preview_like"]["count"]
                except Exception as e:
                    pass

            # C: Intercepted API responses
            if result["views"] == 0 and captured_data:
                 for capture in captured_data:
                     data = capture.get("data", {})
                     if isinstance(data, dict):
                         views = deep_find_key(data, "video_view_count") or deep_find_key(data, "play_count")
                         if views:
                             result["views"] = views

            # Fallback for likes/comments/author from HTML
            try:
                html = await page.content()
                if not result["likes"] and 'like_count' in html:
                    lm = re.search(r'"like_count"\s*:\s*(\d+)', html)
                    if lm: result["likes"] = int(lm.group(1))
                if not result["comments"] and 'comment_count' in html:
                    cm = re.search(r'"comment_count"\s*:\s*(\d+)', html)
                    if cm: result["comments"] = int(cm.group(1))
                if not result["author"] and 'username' in html:
                     am = re.search(r'"username"\s*:\s*"([^"]+)"', html)
                     if am: result["author"] = am.group(1)
            except:
                pass

        except ImportError:
             print("  ⚠️ Playwright not installed. Skipping browser method.")
        except Exception as e:
             pass
        finally:
             if 'browser' in locals():
                 await browser.close()
             if 'pw' in locals():
                 await pw.stop()

        return result

    async def method_5_direct_browser(self, shortcode: str) -> dict:
        """Method 5: Load FULL post page in stealth browser WITH proxy."""
        result = {"views": 0, "likes": 0, "comments": 0, "author": ""}
        captured_data = []
        pw_proxy = self._get_pw_proxy()

        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            
            launch_opts = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ]
            }
            if pw_proxy:
                launch_opts["proxy"] = pw_proxy
                proxy_server = pw_proxy['server']
                print(f"    {info(f'Using proxy: {proxy_server}')}")
            
            browser = await pw.chromium.launch(**launch_opts)
            context = await browser.new_context(
                user_agent=REALISTIC_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            await context.add_init_script(STEALTH_JS)
            page = await context.new_page()

            async def on_response(response):
                url = response.url
                if any(keyword in url for keyword in ['graphql', 'query', 'media', 'api/v1', 'web_info']):
                    try:
                        data = await response.json()
                        captured_data.append({"url": url, "data": data})
                    except:
                        pass

            page.on("response", on_response)

            full_url = f"https://www.instagram.com/p/{shortcode}/"
            resp = await page.goto(full_url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(5, 8))
            
            html = await page.content()
            if "/accounts/login" in html.lower() or "Log in" in html:
                print(f"    {warn('Login wall detected')}")
                return result
                
            # Intercepted API responses
            if captured_data:
                 for capture in captured_data:
                     data = capture.get("data", {})
                     if isinstance(data, dict):
                         views = deep_find_key(data, "video_view_count") or deep_find_key(data, "play_count")
                         if views:
                             result["views"] = views
                             
            # Meta tags / HTML
            if result["views"] == 0:
                view_el = await page.query_selector("span:has-text('plays')")
                if view_el:
                    text = await view_el.inner_text()
                    num_match = re.search(r'([\d,.]+[KMB]?)', text)
                    if num_match:
                         result["views"] = parse_count(num_match.group(1))

            # Extract from page HTML
            if not result["views"]:
                for pattern in [r'"video_view_count"\s*:\s*(\d+)', r'"play_count"\s*:\s*(\d+)']:
                    m = re.search(pattern, html)
                    if m:
                        result["views"] = int(m.group(1))
                        break

            # Likes/comments
            try:
                og_desc = await page.get_attribute("meta[name='description']", "content")
                if og_desc:
                    lm = re.search(r'([\d,]+)\s+likes', og_desc, re.IGNORECASE)
                    cm = re.search(r'([\d,]+)\s+comments', og_desc, re.IGNORECASE)
                    if lm: result["likes"] = parse_count(lm.group(1))
                    if cm: result["comments"] = parse_count(cm.group(1))
            except:
                pass
                    
            try:
                og_title = await page.get_attribute("meta[property='og:title']", "content")
                if og_title:
                    am = re.match(r'^(.+?)\s+on\s+Instagram', og_title)
                    if am: result["author"] = am.group(1).strip().lstrip('@')
            except:
                pass
                             
        except Exception as e:
            pass
        finally:
             if 'browser' in locals():
                 await browser.close()
             if 'pw' in locals():
                 await pw.stop()

        return result

    async def method_6_estimation(self, shortcode: str, known_likes: int = 0) -> dict:
        """Method 6: Estimate views based on likes."""
        if known_likes <= 0:
            return {"views": 0, "estimated": True}
        
        # Reels avg 4% engagement rate
        estimated_views = int(known_likes / 0.04)
        
        return {
            "views": estimated_views,
            "estimated": True,
            "estimation_method": "likes_ratio_4pct",
            "confidence": "low",
        }

    async def get_views(self, video_url: str) -> dict:
        """Main waterfall function."""
        try:
            shortcode = extract_shortcode(video_url)
        except ValueError as e:
            return {"views": 0, "likes": 0, "comments": 0, "author": "", "method": "fail_invalid_url", "estimated": False, "error": str(e)}

        all_results = {}
        
        print("  [1/6] Trying embed deep parse (with proxy)...")
        result = await self.method_1_embed_deep_parse(shortcode)
        all_results["method_1_embed_parse"] = result
        if result.get("views", 0) > 0:
            v = result['views']
            print(f"    {ok(f'Embed parse found views: {v:,}')}")
            return {**result, "method": "embed_parse", "estimated": False, "debug": all_results}
        print(f"    {fail('No views in embed HTML')}")
        if result.get('likes') or result.get('comments') or result.get('author'):
            likes_str = result.get('likes', 0)
            comm_str = result.get('comments', 0)
            auth_str = result.get('author', '')
            print(f"    {info(f'But found: likes={likes_str}, comments={comm_str}, author={auth_str}')}")

        print("  [2/6] Trying media info endpoint (with proxy)...")
        await asyncio.sleep(1)
        result = await self.method_2_media_info(shortcode)
        all_results["method_2_media_info"] = result
        if result.get("views", 0) > 0:
            v = result['views']
            print(f"    {ok(f'Media info found views: {v:,}')}")
            return {**result, "method": "media_info", "estimated": False, "debug": all_results}
        print(f"    {fail('Media info endpoint did not return views')}")

        print("  [3/6] Trying GraphQL endpoint (with proxy)...")
        await asyncio.sleep(1)
        result = await self.method_3_graphql(shortcode)
        all_results["method_3_graphql"] = result
        if result.get("views", 0) > 0:
            views_str = result["views"]
            print(f"    {ok(f'GraphQL found views: {views_str:,}')}")
            return {**result, "method": "graphql", "estimated": False, "debug": all_results}
        print(f"    {fail('GraphQL endpoint did not return views')}")

        print("  [4/6] Trying embed page in browser (with proxy)...")
        result = await self.method_4_embed_browser(shortcode)
        all_results["method_4_embed_browser"] = result
        if result.get("views", 0) > 0:
            views_str = result["views"]
            print(f"    {ok(f'Embed browser found views: {views_str:,}')}")
            return {**result, "method": "embed_browser", "estimated": False, "debug": all_results}
        print(f"    {fail('Embed browser did not find views')}")

        print("  [5/6] Trying full post in browser (with proxy)...")
        await asyncio.sleep(random.uniform(2, 4))
        result = await self.method_5_direct_browser(shortcode)
        all_results["method_5_direct_browser"] = result
        if result.get("views", 0) > 0:
            views_str = result["views"]
            print(f"    {ok(f'Direct browser found views: {views_str:,}')}")
            return {**result, "method": "direct_browser", "estimated": False, "debug": all_results}
        print(f"    {fail('Direct browser failed (login wall or blocked)')}")

        print("  [6/6] Falling back to estimation from likes...")
        best_likes = max([r.get("likes", 0) for r in all_results.values()])
        best_comments = max([r.get("comments", 0) for r in all_results.values()])
        best_author = next((r.get("author") for r in all_results.values() if r.get("author")), "")
        
        if best_likes > 0:
            result = await self.method_6_estimation(shortcode, best_likes)
            views_str = result["views"]
            print(f"    {warn(f'Estimated views: {views_str:,} (from {best_likes:,} likes)')}")
            return {
                **result,
                "likes": best_likes,
                "comments": best_comments,
                "author": best_author,
                "method": "estimation",
                "likes_used": best_likes,
                "debug": all_results
            }

        print(f"    {fail('ALL methods failed. No data available.')}")
        return {
            "views": 0, "likes": 0, "comments": 0, "author": "",
            "method": "all_failed", "estimated": False,
            "debug": all_results,
        }

async def main(url: str = None):
    if not url:
        url = input("Enter Instagram video/reel URL: ").strip()

    try:
        shortcode = extract_shortcode(url)
    except ValueError:
        print(f"{RED}Invalid URL: could not extract shortcode.{RESET}")
        return

    print(f"\n{BOLD}{CYAN}{'═' * 54}")
    print(f" INSTAGRAM VIEW EXTRACTION TEST")
    print(f"{'═' * 54}{RESET}")
    print(f"\nURL: {url}")
    print(f"Shortcode: {shortcode}\n")
    print("Testing 6 methods...\n")

    scraper = InstagramViewScraper()
    final_result = await scraper.get_views(url)

    print(f"\n{BOLD}{CYAN}{'═' * 54}")
    if final_result.get("method") == "all_failed":
        print(f" RESULT: {fail('FAILED')}")
    else:
        print(f" RESULT: {ok('SUCCESS')}")
    print(f"{'═' * 54}{RESET}\n")

    method_used = final_result.get("method", "Unknown")
    print(f"Method that worked: {BOLD}{method_used}{RESET}\n")

    print("Data extracted:")
    views = final_result.get("views", 0)
    likes = final_result.get("likes", 0)
    comments = final_result.get("comments", 0)
    author = final_result.get("author", "Unknown")
    is_estimated = final_result.get("estimated", False)

    print(f"  👁️  Views:    {views:,}")
    print(f"  ❤️  Likes:    {likes:,}")
    print(f"  💬  Comments: {comments:,}")
    print(f"  👤  Author:   @{author}")
    print(f"  📊  Estimated: {'Yes (Using likes ratio)' if is_estimated else 'No (Real data)'}")

    print("\nAll method results:")
    debug_results = final_result.get("debug", {})
    
    def format_debug_result(name, key):
         res = debug_results.get(key)
         if res is None:
              return f"Method {name}: {skip('skipped')}"
         if res.get('views', 0) > 0:
              views_str = res['views']
              return f"Method {name}: {ok(f'views={views_str:,}')}"
         info_str = f"views=0, likes={res.get('likes', 0)}"
         return f"Method {name}: {fail(info_str)}"

    print(f"  {format_debug_result('1 (embed parse)', 'method_1_embed_parse')}")
    print(f"  {format_debug_result('2 (media info)', 'method_2_media_info')}")
    print(f"  {format_debug_result('3 (graphql)   ', 'method_3_graphql')}")
    print(f"  {format_debug_result('4 (embed browser)', 'method_4_embed_browser')}")
    print(f"  {format_debug_result('5 (direct browser)', 'method_5_direct_browser')}")
    
    if is_estimated:
         print(f"  Method 6 (estimation): {warn(f'views={views:,}')}")
    else:
         print(f"  Method 6 (estimation): {skip('skipped')}")
         
    print(f"\n{BOLD}{CYAN}{'═' * 54}{RESET}\n")

if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(url_arg))
