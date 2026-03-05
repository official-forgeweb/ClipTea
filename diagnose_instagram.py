#!/usr/bin/env python3
"""
Instagram Scraping Diagnostic Tool
===================================
Runs 7 independent tests to identify exactly why Instagram scraping
is failing and recommends the best solution path.

Usage:
    python diagnose_instagram.py
    python diagnose_instagram.py https://www.instagram.com/reel/XXXXX/
"""

import asyncio
import aiohttp
import json
import os
import re
import sys
import time
import random
from datetime import datetime
from typing import Optional, Dict, List

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
def heading(msg): return f"\n{BOLD}{CYAN}{'═' * 60}\n  {msg}\n{'═' * 60}{RESET}"

# ──────────────────────────────────────────────────────────────
# Stealth JS (inline — no imports from project)
# ──────────────────────────────────────────────────────────────
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.apply(this, arguments);
};
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);
"""

REALISTIC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

FREE_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]

# ──────────────────────────────────────────────────────────────
# Global results storage
# ──────────────────────────────────────────────────────────────
results: Dict[str, dict] = {}


# ══════════════════════════════════════════════════════════════
#  TEST 1: Direct Connection Test
# ══════════════════════════════════════════════════════════════
async def test_1_direct_connection() -> dict:
    print(heading("TEST 1: Direct Connection (No Proxy, No Browser)"))
    result = {"test": "Direct Connection", "status": "UNKNOWN"}

    url = "https://www.instagram.com/"
    print(f"  URL: {url}")

    try:
        start = time.time()
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=REALISTIC_HEADERS, allow_redirects=True) as resp:
                elapsed = time.time() - start
                body = await resp.text()

                result["status_code"] = resp.status
                result["response_size"] = len(body)
                result["contains_html"] = "<html" in body.lower()
                result["time_seconds"] = round(elapsed, 2)
                result["final_url"] = str(resp.url)

                print(f"  Status: {resp.status}")
                print(f"  Response Size: {len(body):,} bytes")
                print(f"  Contains HTML: {'Yes' if result['contains_html'] else 'No'}")
                print(f"  Time: {elapsed:.2f} seconds")
                print(f"  Final URL: {result['final_url']}")

                if resp.status == 200 and result["contains_html"]:
                    result["status"] = "PASS"
                    print(f"  Result: {ok('PASS — Instagram is reachable')}")
                elif resp.status == 429:
                    result["status"] = "FAIL"
                    print(f"  Result: {fail('FAIL — Rate limited (429)')}")
                else:
                    result["status"] = "PARTIAL"
                    print(f"  Result: {warn(f'PARTIAL — Status {resp.status}')}")

    except asyncio.TimeoutError:
        result["status"] = "FAIL"
        result["error"] = "Timeout after 30 seconds"
        print(f"  Result: {fail('FAIL — Connection timed out')}")
    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"  Result: {fail(f'FAIL — {e}')}")

    return result


# ══════════════════════════════════════════════════════════════
#  TEST 2: Direct Connection to a Specific Public Post
# ══════════════════════════════════════════════════════════════
async def test_2_public_post(test_url: str) -> dict:
    print(heading("TEST 2: Public Post Access (No Proxy, No Browser)"))
    result = {"test": "Public Post Access", "status": "UNKNOWN"}

    urls_to_try = [test_url, "https://www.instagram.com/instagram/"]
    print(f"  Testing URLs: {urls_to_try}")

    for url in urls_to_try:
        print(f"\n  → Testing: {url}")
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=REALISTIC_HEADERS, allow_redirects=False) as resp:
                    body = await resp.text()

                    status = resp.status
                    has_login = "login" in body.lower() and "/accounts/login" in body.lower()
                    has_post_data = "shortcode_media" in body or "edge_media" in body
                    has_og_data = 'og:description' in body or 'og:title' in body
                    rate_limited = status == 429

                    result[url] = {
                        "status_code": status,
                        "login_wall": has_login,
                        "has_post_data": has_post_data,
                        "has_og_tags": has_og_data,
                        "rate_limited": rate_limited,
                        "response_size": len(body),
                    }

                    print(f"    Status: {status}")
                    print(f"    Login Wall Detected: {'YES' if has_login else 'NO'}")
                    print(f"    Contains Post Data: {'YES' if has_post_data else 'NO'}")
                    print(f"    Contains OG Tags: {'YES' if has_og_data else 'NO'}")
                    print(f"    Rate Limited: {'YES' if rate_limited else 'NO'}")
                    print(f"    Response Size: {len(body):,} bytes")

                    # Check rate limit headers
                    rl_headers = {k: v for k, v in resp.headers.items()
                                  if 'rate' in k.lower() or 'limit' in k.lower() or 'retry' in k.lower()}
                    if rl_headers:
                        print(f"    Rate-Limit Headers: {json.dumps(rl_headers, indent=6)}")

                    if status == 200 and (has_post_data or has_og_data) and not has_login:
                        result["status"] = "PASS"
                        result["working_url"] = url
                        print(f"    Result: {ok('PASS')}")
                        break
                    elif status == 200 and has_login:
                        result["status"] = "FAIL"
                        print(f"    Result: {fail('FAIL — login wall')}")
                    elif status == 302:
                        location = resp.headers.get("Location", "")
                        print(f"    Redirect to: {location}")
                        result["status"] = "FAIL"
                        print(f"    Result: {fail('FAIL — redirected (likely login)')}")
                    elif rate_limited:
                        result["status"] = "FAIL"
                        print(f"    Result: {fail('FAIL — rate limited')}")
                    else:
                        result["status"] = "PARTIAL"
                        print(f"    Result: {warn(f'PARTIAL — status {status}')}")

        except asyncio.TimeoutError:
            print(f"    Result: {fail('FAIL — Timeout')}")
            result["status"] = "FAIL"
        except Exception as e:
            print(f"    Result: {fail(f'FAIL — {e}')}")
            result["status"] = "FAIL"

    if result["status"] == "UNKNOWN":
        result["status"] = "FAIL"
        print(f"\n  Overall: {fail('FAIL — could not access any public post')}")

    return result


# ══════════════════════════════════════════════════════════════
#  TEST 3: Playwright Browser Test (No Proxy, No Stealth)
# ══════════════════════════════════════════════════════════════
async def test_3_basic_playwright(test_url: str) -> dict:
    print(heading("TEST 3: Basic Playwright Browser (No Stealth, No Proxy)"))
    result = {"test": "Basic Playwright Browser", "status": "UNKNOWN"}

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )
            context = await browser.new_context(
                user_agent=REALISTIC_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            page = await context.new_page()

            print(f"  Browser: Chromium (headless)")
            print(f"  URL: {test_url}")

            try:
                resp = await page.goto(test_url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(3)

                title = await page.title()
                final_url = page.url
                content = await page.content()
                webdriver_val = await page.evaluate("() => navigator.webdriver")

                has_login = "/accounts/login" in content.lower() or "Log in" in content
                has_og = "og:description" in content or "og:title" in content

                result["page_title"] = title
                result["final_url"] = final_url
                result["content_length"] = len(content)
                result["login_wall"] = has_login
                result["has_og_tags"] = has_og
                result["webdriver_value"] = webdriver_val
                result["status_code"] = resp.status if resp else None

                print(f"  Page Title: {title}")
                print(f"  Page URL: {final_url}")
                print(f"  Status: {resp.status if resp else 'N/A'}")
                print(f"  Login Wall: {'YES' if has_login else 'NO'}")
                print(f"  Has OG Tags: {'YES' if has_og else 'NO'}")
                print(f"  Content Length: {len(content):,} chars")
                print(f"  navigator.webdriver: {webdriver_val}")

                # Save screenshot
                screenshot_path = "test3_basic_browser.png"
                await page.screenshot(path=screenshot_path, full_page=False)
                result["screenshot"] = screenshot_path
                print(f"  Screenshot: {screenshot_path}")

                if not has_login and has_og:
                    result["status"] = "PASS"
                    print(f"  Result: {ok('PASS')}")
                elif has_login:
                    result["status"] = "FAIL"
                    print(f"  Result: {fail('FAIL — Login wall detected')}")
                else:
                    result["status"] = "PARTIAL"
                    print(f"  Result: {warn('PARTIAL — Page loaded but unclear data')}")

            except Exception as e:
                result["status"] = "FAIL"
                result["error"] = str(e)
                print(f"  Result: {fail(f'FAIL — {e}')}")
            finally:
                await browser.close()

    except ImportError:
        result["status"] = "FAIL"
        result["error"] = "Playwright not installed"
        print(f"  Result: {fail('FAIL — Playwright not installed. Run: pip install playwright && playwright install chromium')}")
    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"  Result: {fail(f'FAIL — {e}')}")

    return result


# ══════════════════════════════════════════════════════════════
#  TEST 4: Playwright with Stealth (No Proxy)
# ══════════════════════════════════════════════════════════════
async def test_4_stealth_playwright(test_url: str) -> dict:
    print(heading("TEST 4: Stealth Playwright Browser (No Proxy)"))
    result = {"test": "Stealth Playwright Browser", "status": "UNKNOWN"}

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ]
            )
            context = await browser.new_context(
                user_agent=REALISTIC_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                device_scale_factor=1,
            )
            # Apply stealth
            await context.add_init_script(STEALTH_JS)
            result["stealth_applied"] = True
            print(f"  Stealth patches applied: YES")

            page = await context.new_page()
            print(f"  URL: {test_url}")

            try:
                resp = await page.goto(test_url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(3)

                title = await page.title()
                final_url = page.url
                content = await page.content()
                webdriver_val = await page.evaluate("() => navigator.webdriver")

                has_login = "/accounts/login" in content.lower() or "Log in" in content
                has_og = "og:description" in content or "og:title" in content

                # Extract any metrics from meta tags
                og_desc = await page.get_attribute("meta[name='description']", "content") or ""
                og_title = await page.get_attribute("meta[property='og:title']", "content") or ""

                result["page_title"] = title
                result["final_url"] = final_url
                result["content_length"] = len(content)
                result["login_wall"] = has_login
                result["has_og_tags"] = has_og
                result["webdriver_value"] = webdriver_val
                result["og_description"] = og_desc[:200] if og_desc else ""
                result["og_title"] = og_title[:200] if og_title else ""

                print(f"  navigator.webdriver: {webdriver_val} {'(patched ✅)' if webdriver_val is None or webdriver_val == 'undefined' else '(NOT patched ❌)'}")
                print(f"  Page Title: {title}")
                print(f"  Page URL: {final_url}")
                print(f"  Status: {resp.status if resp else 'N/A'}")
                print(f"  Login Wall: {'YES' if has_login else 'NO'}")
                print(f"  Has OG Tags: {'YES' if has_og else 'NO'}")
                print(f"  Content Length: {len(content):,} chars")
                if og_title:
                    print(f"  OG Title: {og_title[:100]}")
                if og_desc:
                    print(f"  OG Description: {og_desc[:100]}")

                # Compare with test 3
                test3 = results.get("test_3", {})
                if test3:
                    t3_login = test3.get("login_wall", None)
                    t4_login = has_login
                    if t3_login is True and not t4_login:
                        print(f"  Difference from Test 3: {ok('BETTER — stealth bypassed login wall!')}")
                    elif t3_login == t4_login:
                        print(f"  Difference from Test 3: {info('SAME — no difference')}")
                    else:
                        print(f"  Difference from Test 3: {fail('WORSE')}")

                screenshot_path = "test4_stealth_browser.png"
                await page.screenshot(path=screenshot_path, full_page=False)
                result["screenshot"] = screenshot_path
                print(f"  Screenshot: {screenshot_path}")

                if not has_login and has_og:
                    result["status"] = "PASS"
                    print(f"  Result: {ok('PASS')}")
                elif has_login:
                    result["status"] = "FAIL"
                    print(f"  Result: {fail('FAIL — Login wall detected')}")
                else:
                    result["status"] = "PARTIAL"
                    print(f"  Result: {warn('PARTIAL')}")

            except Exception as e:
                result["status"] = "FAIL"
                result["error"] = str(e)
                print(f"  Result: {fail(f'FAIL — {e}')}")
            finally:
                await browser.close()

    except ImportError:
        result["status"] = "FAIL"
        print(f"  Result: {fail('FAIL — Playwright not installed')}")
    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"  Result: {fail(f'FAIL — {e}')}")

    return result


# ══════════════════════════════════════════════════════════════
#  TEST 5: Free Proxy Quality Test
# ══════════════════════════════════════════════════════════════
async def test_5_proxy_quality() -> dict:
    print(heading("TEST 5: Free Proxy Quality"))
    result = {"test": "Free Proxy Quality", "status": "UNKNOWN", "working_proxies": []}

    # Fetch proxies
    all_proxies = set()
    print(f"  Fetching proxies from {len(FREE_PROXY_SOURCES)} sources...")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for src in FREE_PROXY_SOURCES:
            try:
                async with session.get(src) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        proxies = [p.strip() for p in text.splitlines() if p.strip() and ":" in p]
                        all_proxies.update(proxies)
                        print(f"    Fetched {len(proxies)} from {src[:50]}...")
            except Exception as e:
                print(f"    Failed: {src[:50]}... ({e})")

    total_fetched = len(all_proxies)
    result["total_fetched"] = total_fetched
    print(f"\n  Total unique proxies fetched: {total_fetched}")

    if total_fetched == 0:
        result["status"] = "FAIL"
        print(f"  Result: {fail('FAIL — No proxies fetched')}")
        return result

    # Test a random sample (max 100 to save time)
    sample = random.sample(list(all_proxies), min(100, total_fetched))
    print(f"  Testing sample of {len(sample)} proxies...")

    # Step 1: Test connectivity via httpbin
    httpbin_working = []
    semaphore = asyncio.Semaphore(30)
    test_timeout = aiohttp.ClientTimeout(total=8)

    async def test_proxy_httpbin(proxy_str):
        proxy_url = proxy_str if proxy_str.startswith("http") else f"http://{proxy_str}"
        async with semaphore:
            try:
                async with aiohttp.ClientSession(timeout=test_timeout) as s:
                    async with s.get("http://httpbin.org/ip", proxy=proxy_url) as r:
                        if r.status == 200:
                            httpbin_working.append(proxy_str)
            except Exception:
                pass

    tasks = [test_proxy_httpbin(p) for p in sample]
    await asyncio.gather(*tasks)

    result["httpbin_working"] = len(httpbin_working)
    httpbin_pct = (len(httpbin_working) / len(sample) * 100) if sample else 0
    print(f"\n  Connection test (httpbin.org):")
    print(f"    {ok(f'Working: {len(httpbin_working)} ({httpbin_pct:.1f}%)')}")
    print(f"    {fail(f'Dead/Timeout: {len(sample) - len(httpbin_working)} ({100 - httpbin_pct:.1f}%)')}")

    # Step 2: Test if working proxies can reach Instagram
    ig_working = []
    ig_blocked = 0
    ig_error = 0

    if httpbin_working:
        print(f"\n  Instagram access test ({len(httpbin_working)} working proxies):")

        async def test_proxy_instagram(proxy_str):
            nonlocal ig_blocked, ig_error
            proxy_url = proxy_str if proxy_str.startswith("http") else f"http://{proxy_str}"
            try:
                async with aiohttp.ClientSession(timeout=test_timeout) as s:
                    async with s.get("https://www.instagram.com/", proxy=proxy_url,
                                     headers=REALISTIC_HEADERS) as r:
                        body = await r.text()
                        if r.status == 200 and "<html" in body.lower():
                            ig_working.append(proxy_str)
                        elif r.status == 429 or r.status == 403:
                            ig_blocked += 1
                        else:
                            ig_error += 1
            except Exception:
                ig_error += 1

        ig_tasks = [test_proxy_instagram(p) for p in httpbin_working]
        await asyncio.gather(*ig_tasks)

        total_ig = len(httpbin_working)
        print(f"    {ok(f'Can reach Instagram: {len(ig_working)} ({len(ig_working)/total_ig*100:.1f}%)')}")
        print(f"    {fail(f'Blocked by Instagram: {ig_blocked} ({ig_blocked/total_ig*100:.1f}%)')}")
        print(f"    {fail(f'Timeout/Error: {ig_error} ({ig_error/total_ig*100:.1f}%)')}")

    result["ig_working"] = len(ig_working)
    result["ig_blocked"] = ig_blocked
    result["ig_error"] = ig_error
    result["working_proxies"] = ig_working[:10]  # Keep best 10

    overall_pct = (len(ig_working) / total_fetched * 100) if total_fetched else 0
    print(f"\n  Working proxies for Instagram: {len(ig_working)}")

    if len(ig_working) >= 10:
        result["status"] = "GOOD"
        print(f"  Result: {ok(f'GOOD — {len(ig_working)} usable proxies')}")
    elif len(ig_working) > 0:
        result["status"] = "POOR"
        print(f"  Result: {warn(f'POOR — Only {len(ig_working)} proxies work ({overall_pct:.1f}%)')}")
    else:
        result["status"] = "FAIL"
        print(f"  Result: {fail('FAIL — No free proxies work with Instagram')}")

    return result


# ══════════════════════════════════════════════════════════════
#  TEST 6: Full Scrape Attempt (Stealth + Proxy Fallback)
# ══════════════════════════════════════════════════════════════
async def test_6_full_scrape(test_url: str) -> dict:
    print(heading("TEST 6: Full Scrape Attempt"))
    result = {"test": "Full Scrape Attempt", "status": "UNKNOWN"}

    # Determine proxy to use
    test5 = results.get("test_5", {})
    working_proxies = test5.get("working_proxies", [])
    proxy_to_use = None
    if working_proxies:
        proxy_str = working_proxies[0]
        proxy_to_use = proxy_str if proxy_str.startswith("http") else f"http://{proxy_str}"
        print(f"  Proxy: {proxy_to_use}")
    else:
        print(f"  Proxy: {info('direct — no proxy (none available)')}")

    print(f"  URL: {test_url}")

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ]
            launch_opts = {"headless": True, "args": launch_args}
            if proxy_to_use:
                launch_opts["proxy"] = {"server": proxy_to_use}

            browser = await p.chromium.launch(**launch_opts)
            context = await browser.new_context(
                user_agent=REALISTIC_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
            )
            await context.add_init_script(STEALTH_JS)

            # Intercept XHR/GraphQL responses
            intercepted_data = []

            async def on_response(response):
                url = response.url
                if "graphql" in url or "query" in url or "__a=1" in url:
                    try:
                        body = await response.json()
                        intercepted_data.append({"url": url, "data": body})
                    except Exception:
                        pass

            page = await context.new_page()
            page.on("response", on_response)

            try:
                resp = await page.goto(test_url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(4)

                content = await page.content()
                has_login = "/accounts/login" in content.lower() or "Log in" in content

                result["page_loaded"] = True
                result["login_wall"] = has_login
                print(f"  Page loaded: YES")
                print(f"  Login wall: {'YES' if has_login else 'NO'}")

                print(f"\n  Extraction Methods:")

                # Method A: Meta tags
                og_desc = await page.get_attribute("meta[name='description']", "content")
                og_title = await page.get_attribute("meta[property='og:title']", "content")
                method_a = bool(og_desc or og_title)
                result["meta_tags"] = method_a
                print(f"    Meta tags (og:description):     {ok('Found') if method_a else fail('Not found')}")
                if og_desc:
                    print(f"      → {og_desc[:120]}")

                # Method B: window._sharedData
                shared_data = await page.evaluate("""() => {
                    for (let s of document.getElementsByTagName('script')) {
                        if (s.innerHTML.includes('window._sharedData'))
                            return s.innerHTML;
                    }
                    return null;
                }""")
                method_b = shared_data is not None and "shortcode_media" in (shared_data or "")
                result["shared_data"] = method_b
                print(f"    window._sharedData:             {ok('Found') if method_b else fail('Not found')}")

                # Method C: __additionalDataLoaded
                additional_data = await page.evaluate("""() => {
                    for (let s of document.getElementsByTagName('script')) {
                        if (s.innerHTML.includes('__additionalDataLoaded'))
                            return s.innerHTML;
                    }
                    return null;
                }""")
                method_c = additional_data is not None
                result["additional_data"] = method_c
                print(f"    __additionalDataLoaded:         {ok('Found') if method_c else fail('Not found')}")

                # Method D: Intercepted XHR/GraphQL
                method_d = len(intercepted_data) > 0
                result["intercepted_xhr"] = method_d
                result["intercepted_count"] = len(intercepted_data)
                print(f"    Intercepted XHR/GraphQL:        {ok(f'Found ({len(intercepted_data)} responses)') if method_d else fail('Not found')}")

                # Method E: HTML content parsing
                likes_in_html = bool(re.search(r'([\d,]+)\s+likes', content, re.IGNORECASE))
                views_in_html = bool(re.search(r'([\d,]+)\s+views', content, re.IGNORECASE))
                method_e = likes_in_html or views_in_html
                result["html_parsing"] = method_e
                print(f"    HTML content parsing:           {ok('Found') if method_e else fail('Not found')}")

                # Try to extract actual data
                extracted = {}
                if og_desc:
                    likes_m = re.search(r'([\d,]+)\s+likes', og_desc, re.IGNORECASE)
                    comments_m = re.search(r'([\d,]+)\s+comments', og_desc, re.IGNORECASE)
                    views_m = re.search(r'([\d,]+)\s+views', og_desc, re.IGNORECASE)
                    if likes_m:
                        extracted["likes"] = likes_m.group(1)
                    if comments_m:
                        extracted["comments"] = comments_m.group(1)
                    if views_m:
                        extracted["views"] = views_m.group(1)
                if og_title:
                    author_m = re.match(r'^(.+?)\s+on\s+Instagram', og_title)
                    if author_m:
                        extracted["author"] = author_m.group(1).strip()

                result["extracted_data"] = extracted
                if extracted:
                    print(f"\n  Extracted Data:")
                    for k, v in extracted.items():
                        print(f"    {k.title()}: {v}")

                screenshot_path = "test6_scrape_attempt.png"
                await page.screenshot(path=screenshot_path, full_page=False)
                result["screenshot"] = screenshot_path
                print(f"\n  Screenshot: {screenshot_path}")

                any_method_worked = method_a or method_b or method_c or method_d or method_e
                if any_method_worked and not has_login and extracted:
                    result["status"] = "PASS"
                    print(f"  Result: {ok('SUCCESS — Data extracted!')}")
                elif any_method_worked and not has_login:
                    result["status"] = "PARTIAL"
                    print(f"  Result: {warn('PARTIAL — Methods available but no metrics extracted')}")
                else:
                    result["status"] = "FAIL"
                    print(f"  Result: {fail('FAIL')}")

            except Exception as e:
                result["status"] = "FAIL"
                result["error"] = str(e)
                print(f"  Result: {fail(f'FAIL — {e}')}")
            finally:
                await browser.close()

    except ImportError:
        result["status"] = "FAIL"
        print(f"  Result: {fail('FAIL — Playwright not installed')}")
    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"  Result: {fail(f'FAIL — {e}')}")

    return result


# ══════════════════════════════════════════════════════════════
#  TEST 7: Alternative API Endpoints
# ══════════════════════════════════════════════════════════════
async def test_7_alternative_endpoints(test_url: str) -> dict:
    print(heading("TEST 7: Alternative API Endpoints"))
    result = {"test": "Alternative Endpoints", "status": "UNKNOWN", "endpoints": {}}

    # Extract shortcode from URL
    shortcode_match = re.search(r'instagram\.com/(?:p|reel)/([\w-]+)', test_url)
    if not shortcode_match:
        shortcode = "CsYfJOrMo1p"  # known public post fallback
        print(f"  Could not extract shortcode from URL, using fallback: {shortcode}")
    else:
        shortcode = shortcode_match.group(1)
        print(f"  Shortcode: {shortcode}")

    timeout = aiohttp.ClientTimeout(total=20)

    # ── Endpoint 1: ?__a=1&__d=dis ──
    print(f"\n  {BOLD}Endpoint 1: ?__a=1&__d=dis{RESET}")
    ep1_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ep1_url, headers=REALISTIC_HEADERS, allow_redirects=False) as resp:
                status = resp.status
                body_text = await resp.text()
                has_data = "shortcode_media" in body_text or '"graphql"' in body_text

                ep1_result = {"status": status, "has_data": has_data, "size": len(body_text)}
                result["endpoints"]["json_api"] = ep1_result

                print(f"    Status: {status}")
                if status == 200 and has_data:
                    print(f"    Contains data: YES")
                    print(f"    Result: {ok('WORKS')}")
                    ep1_result["works"] = True
                elif status == 302:
                    location = resp.headers.get("Location", "")
                    print(f"    Redirect to: {location}")
                    print(f"    Result: {fail('BLOCKED — redirected to login')}")
                    ep1_result["works"] = False
                else:
                    print(f"    Result: {fail(f'Status {status}')}")
                    ep1_result["works"] = False
    except Exception as e:
        print(f"    Result: {fail(f'ERROR — {e}')}")
        result["endpoints"]["json_api"] = {"works": False, "error": str(e)}

    # ── Endpoint 2: GraphQL query ──
    print(f"\n  {BOLD}Endpoint 2: GraphQL query{RESET}")
    # Query hash for media detail
    query_hash = "b3055c01b4b222b8a47dc12b090e4e64"
    variables = json.dumps({"shortcode": shortcode, "child_comment_count": 3, "fetch_comment_count": 40,
                            "parent_comment_count": 24, "has_threaded_comments": True})
    ep2_url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={variables}"
    try:
        gql_headers = {**REALISTIC_HEADERS, "X-Requested-With": "XMLHttpRequest"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ep2_url, headers=gql_headers, allow_redirects=False) as resp:
                status = resp.status
                body_text = await resp.text()
                has_data = "shortcode_media" in body_text

                ep2_result = {"status": status, "has_data": has_data}
                result["endpoints"]["graphql"] = ep2_result

                print(f"    Status: {status}")
                if status == 200 and has_data:
                    print(f"    Contains data: YES")
                    print(f"    Result: {ok('WORKS')}")
                    ep2_result["works"] = True
                elif status == 200:
                    print(f"    Contains data: NO")
                    print(f"    Result: {warn('PARTIAL — responded but no media data')}")
                    ep2_result["works"] = False
                else:
                    print(f"    Result: {fail(f'Status {status}')}")
                    ep2_result["works"] = False
    except Exception as e:
        print(f"    Result: {fail(f'ERROR — {e}')}")
        result["endpoints"]["graphql"] = {"works": False, "error": str(e)}

    # ── Endpoint 3: /embed/ ──
    print(f"\n  {BOLD}Endpoint 3: /embed/{RESET}")
    ep3_url = f"https://www.instagram.com/p/{shortcode}/embed/"
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ep3_url, headers=REALISTIC_HEADERS, allow_redirects=True) as resp:
                status = resp.status
                body_text = await resp.text()

                has_login = "/accounts/login" in body_text.lower()
                has_likes = bool(re.search(r'([\d,]+)\s+likes?', body_text, re.IGNORECASE))
                has_comments = bool(re.search(r'([\d,]+)\s+comments?', body_text, re.IGNORECASE))
                has_views = bool(re.search(r'([\d,]+)\s+views?', body_text, re.IGNORECASE))
                has_caption = "Caption" in body_text or "edge_media_to_caption" in body_text
                has_embed_data = "shortcode_media" in body_text or "EmbeddedMedia" in body_text or "embeds" in body_text.lower()

                # Try to extract username from embed
                author_match = re.search(r'"username"\s*:\s*"([^"]+)"', body_text)
                author = author_match.group(1) if author_match else None

                ep3_result = {
                    "status": status, "login_wall": has_login,
                    "has_likes": has_likes, "has_comments": has_comments,
                    "has_views": has_views, "has_embed_data": has_embed_data,
                    "author": author, "size": len(body_text)
                }
                result["endpoints"]["embed"] = ep3_result

                print(f"    Status: {status}")
                print(f"    Login Wall: {'YES' if has_login else 'NO'}")
                print(f"    Contains Likes: {'YES' if has_likes else 'NO'}")
                print(f"    Contains Comments: {'YES' if has_comments else 'NO'}")
                print(f"    Contains Views: {'YES' if has_views else 'NO'}")
                print(f"    Contains Embed Data: {'YES' if has_embed_data else 'NO'}")
                print(f"    Response Size: {len(body_text):,} bytes")
                if author:
                    print(f"    Author extracted: @{author}")

                if status == 200 and not has_login and (has_likes or has_embed_data):
                    print(f"    Result: {ok('WORKS')}")
                    ep3_result["works"] = True
                elif status == 200 and not has_login:
                    print(f"    Result: {warn('PARTIAL — page loads but limited data')}")
                    ep3_result["works"] = "partial"
                else:
                    print(f"    Result: {fail('BLOCKED')}")
                    ep3_result["works"] = False
    except Exception as e:
        print(f"    Result: {fail(f'ERROR — {e}')}")
        result["endpoints"]["embed"] = {"works": False, "error": str(e)}

    # ── Endpoint 4: /embed/captioned/ ──
    print(f"\n  {BOLD}Endpoint 4: /embed/captioned/{RESET}")
    ep4_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ep4_url, headers=REALISTIC_HEADERS, allow_redirects=True) as resp:
                status = resp.status
                body_text = await resp.text()
                has_login = "/accounts/login" in body_text.lower()
                has_data = "EmbeddedMedia" in body_text or "shortcode_media" in body_text or len(body_text) > 5000

                # Try to find likes count
                likes_match = re.search(r'"edge_media_preview_like"\s*:\s*\{\s*"count"\s*:\s*(\d+)', body_text)
                comments_match = re.search(r'"edge_media_to_parent_comment"\s*:\s*\{\s*"count"\s*:\s*(\d+)', body_text)
                views_match = re.search(r'"video_view_count"\s*:\s*(\d+)', body_text)

                ep4_result = {
                    "status": status, "login_wall": has_login,
                    "has_data": has_data, "size": len(body_text),
                    "likes": int(likes_match.group(1)) if likes_match else None,
                    "comments": int(comments_match.group(1)) if comments_match else None,
                    "views": int(views_match.group(1)) if views_match else None,
                }
                result["endpoints"]["embed_captioned"] = ep4_result

                print(f"    Status: {status}")
                print(f"    Login Wall: {'YES' if has_login else 'NO'}")
                print(f"    Has Embed Data: {'YES' if has_data else 'NO'}")
                print(f"    Response Size: {len(body_text):,} bytes")
                if likes_match:
                    print(f"    Likes: {likes_match.group(1)}")
                if comments_match:
                    print(f"    Comments: {comments_match.group(1)}")
                if views_match:
                    print(f"    Views: {views_match.group(1)}")

                if status == 200 and not has_login and has_data:
                    print(f"    Result: {ok('WORKS')}")
                    ep4_result["works"] = True
                else:
                    print(f"    Result: {fail('BLOCKED or no data')}")
                    ep4_result["works"] = False
    except Exception as e:
        print(f"    Result: {fail(f'ERROR — {e}')}")
        result["endpoints"]["embed_captioned"] = {"works": False, "error": str(e)}

    # Determine overall status
    any_works = any(
        ep.get("works") is True or ep.get("works") == "partial"
        for ep in result["endpoints"].values()
    )
    if any_works:
        result["status"] = "PASS"
        working = [name for name, ep in result["endpoints"].items() if ep.get("works")]
        print(f"\n  Overall: {ok(f'PASS — Working endpoints: {", ".join(working)}')}")
    else:
        result["status"] = "FAIL"
        print(f"\n  Overall: {fail('FAIL — No alternative endpoints work')}")

    return result


# ══════════════════════════════════════════════════════════════
#  FINAL REPORT
# ══════════════════════════════════════════════════════════════
def generate_report():
    print(f"\n\n{BOLD}{CYAN}{'══' * 30}")
    print(f"         INSTAGRAM SCRAPING DIAGNOSTIC REPORT")
    print(f"{'══' * 30}{RESET}")

    status_map = {
        "PASS": ok("PASS"),
        "FAIL": fail("FAIL"),
        "PARTIAL": warn("PARTIAL"),
        "POOR": warn("POOR"),
        "GOOD": ok("GOOD"),
        "UNKNOWN": DIM + "SKIPPED" + RESET,
    }

    test_names = {
        "test_1": "Direct Connection",
        "test_2": "Public Post Access",
        "test_3": "Basic Playwright",
        "test_4": "Stealth Playwright",
        "test_5": "Free Proxy Quality",
        "test_6": "Full Scrape Attempt",
        "test_7": "Alternative Endpoints",
    }

    print(f"\n{BOLD}Test Results Summary:{RESET}")
    for key, name in test_names.items():
        status = results.get(key, {}).get("status", "UNKNOWN")
        detail = ""
        if key == "test_2" and status == "FAIL":
            detail = " (login wall)"
        elif key == "test_5":
            ig_w = results.get(key, {}).get("ig_working", 0)
            total = results.get(key, {}).get("total_fetched", 0)
            detail = f" ({ig_w}/{total} work)" if total else ""
        elif key == "test_7":
            eps = results.get(key, {}).get("endpoints", {})
            working = [n for n, e in eps.items() if e.get("works")]
            if working:
                detail = f" ({', '.join(working)})"

        label = status_map.get(status, status)
        dots = "." * (35 - len(name))
        print(f"  TEST {key[-1]}: {name} {dots} {label}{detail}")

    # ── Diagnosis & Recommendations ──
    t1 = results.get("test_1", {}).get("status")
    t2 = results.get("test_2", {}).get("status")
    t3 = results.get("test_3", {}).get("status")
    t4 = results.get("test_4", {}).get("status")
    t5 = results.get("test_5", {}).get("status")
    t6 = results.get("test_6", {}).get("status")
    t7 = results.get("test_7", {}).get("status")

    # Check specific endpoints
    embed_works = results.get("test_7", {}).get("endpoints", {}).get("embed", {}).get("works")
    embed_cap_works = results.get("test_7", {}).get("endpoints", {}).get("embed_captioned", {}).get("works")

    print(f"\n{'══' * 30}")

    recommendations = []

    if t6 == "PASS":
        print(f"\n{BOLD}DIAGNOSIS:{RESET} Current scraping approach works!")
        recommendations.append(
            "OPTION A (Current Setup Works):\n"
            "  → Your stealth browser scraping is working\n"
            "  → Continue using current approach\n"
            "  → Consider adding longer delays for stability"
        )
    else:
        if t1 != "PASS":
            print(f"\n{BOLD}DIAGNOSIS:{RESET} Cannot reach Instagram at all")
            recommendations.append(
                "CRITICAL:\n"
                "  → Check your internet connection\n"
                "  → Check if Instagram is blocked by firewall/ISP\n"
                "  → Try from a different network"
            )
        elif t2 != "PASS":
            print(f"\n{BOLD}DIAGNOSIS:{RESET} Instagram is blocking post access (login wall)")
        else:
            print(f"\n{BOLD}DIAGNOSIS:{RESET} Browser detection or proxy issues")

    if embed_works or embed_cap_works:
        recommendations.append(
            "OPTION A (Free — Best Chance):\n"
            "  → Use Instagram EMBED endpoint (/p/{shortcode}/embed/)\n"
            "  → No login wall, contains likes/comments\n"
            "  → May contain view counts for videos\n"
            "  → Use aiohttp (no browser needed = much faster!)\n"
            "  → Combine with /embed/captioned/ for more data"
        )

    if t4 == "PASS" and t5 in ("FAIL", "POOR"):
        recommendations.append(
            "OPTION B (Costs $7-15/month):\n"
            "  → Buy residential proxies (e.g., IPRoyal $7/GB)\n"
            "  → Re-run diagnostic with residential proxy\n"
            "  → Should pass all tests"
        )

    if t4 == "PASS" or t3 == "PASS":
        recommendations.append(
            "OPTION C (Free — Direct Scraping):\n"
            "  → Use your home IP without proxy\n"
            "  → Add longer delays (15-30 seconds between requests)\n"
            "  → Limit to 20-30 scrapes per hour\n"
            "  → Risk: your IP may get temporarily blocked"
        )

    if t3 != "PASS" and t4 != "PASS" and not recommendations:
        recommendations.append(
            "OPTION D (Technical — API Approach):\n"
            "  → Use Instagram's Graph API with a Facebook App token\n"
            "  → Requires creating a Facebook Developer account\n"
            "  → Most reliable but limited to your own posts"
        )

    if not recommendations:
        recommendations.append(
            "NO CLEAR PATH:\n"
            "  → All methods currently blocked\n"
            "  → Wait 24 hours and re-run this diagnostic\n"
            "  → Consider residential proxies"
        )

    print(f"\n{BOLD}RECOMMENDED SOLUTION PATH:{RESET}\n")
    for i, rec in enumerate(recommendations):
        print(f"  {rec}\n")

    print(f"{'══' * 30}")

    # Screenshots
    screenshots = []
    for key in ["test_3", "test_4", "test_6"]:
        ss = results.get(key, {}).get("screenshot")
        if ss:
            screenshots.append(ss)

    if screenshots:
        print(f"\nScreenshots saved:")
        for ss in screenshots:
            print(f"  {ss}")

    # Save JSON
    json_path = "diagnostic_results.json"
    try:
        # Clean results for JSON serialization
        clean = {}
        for k, v in results.items():
            clean[k] = {}
            for kk, vv in v.items():
                try:
                    json.dumps(vv)
                    clean[k][kk] = vv
                except (TypeError, ValueError):
                    clean[k][kk] = str(vv)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)
        print(f"\nRaw data saved to: {json_path}")
    except Exception as e:
        print(f"\nFailed to save JSON: {e}")

    print(f"\n{'══' * 30}\n")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
async def main():
    # Determine test URL
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        test_url = "https://www.instagram.com/instagram/"
    
    print(f"{BOLD}{CYAN}")
    print(f"  ╔══════════════════════════════════════════════╗")
    print(f"  ║   INSTAGRAM SCRAPING DIAGNOSTIC TOOL        ║")
    print(f"  ║   Testing: {test_url[:35]:35s}║")
    print(f"  ║   Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):35s}║")
    print(f"  ╚══════════════════════════════════════════════╝")
    print(f"{RESET}")

    # Run all 7 tests
    results["test_1"] = await test_1_direct_connection()
    results["test_2"] = await test_2_public_post(test_url)
    results["test_3"] = await test_3_basic_playwright(test_url)
    results["test_4"] = await test_4_stealth_playwright(test_url)
    results["test_5"] = await test_5_proxy_quality()
    results["test_6"] = await test_6_full_scrape(test_url)
    results["test_7"] = await test_7_alternative_endpoints(test_url)

    # Generate report
    generate_report()


if __name__ == "__main__":
    asyncio.run(main())
