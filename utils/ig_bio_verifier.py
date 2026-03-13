"""
Instagram bio code verifier.
Checks a public Instagram profile's bio for a specific verification code.

Strategy (in priority order):
  1. Apify Instagram Profile Scraper  – most reliable, uses the user's existing token
  2. i.instagram.com mobile API        – lightweight, sometimes works with proxies
  3. HTML scraping + meta/JSON fallback – last resort
"""

import re
import os
import asyncio
import logging
import json
import httpx
from typing import Optional, List
import config

log = logging.getLogger(__name__)

# Headers that mimic a regular browser / mobile app
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Headers that mimic the Instagram mobile app (for i.instagram.com)
_MOBILE_API_HEADERS = {
    "User-Agent": "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-S901B; s5e9925; exynos2200)",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-IG-Connection-Type": "WIFI",
    "X-Requested-With": "XMLHttpRequest",
}


class IGBioVerifier:
    """Async verifier that checks for a code string inside an Instagram user's bio."""

    def __init__(self, proxy_rotator=None, timeout: float = 45.0):
        self.proxy_rotator = proxy_rotator
        self.timeout = timeout
        self.apify_token = config.PRIMARY_APIFY_TOKEN


    async def check_bio(self, username: str, code: str) -> bool:
        """
        Return True if `code` appears anywhere in `username`'s Instagram bio.
        Tries multiple methods in priority order.
        """
        username = username.lstrip("@").strip().lower()
        code = code.strip()

        if not username or not code:
            return False

        try:
            return await asyncio.wait_for(
                self._check(username, code), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            log.warning("[IGBioVerifier] Timed out checking @%s", username)
            return False
        except Exception as exc:
            log.error("[IGBioVerifier] Error checking @%s: %s", username, exc)
            return False

    # ────────────────────────────────────────────────
    #  Main orchestrator
    # ────────────────────────────────────────────────

    async def _check(self, username: str, code: str) -> bool:
        """Try every method in order until one succeeds."""

        # ── Method 1: Apify (most reliable) ─────────
        if self.apify_token:
            log.info("[IGBioVerifier] Trying Apify profile scraper for @%s", username)
            bio = await self._try_apify(username)
            if bio is not None:
                if code.lower() in bio.lower():
                    log.info("[IGBioVerifier] ✅ Code found via Apify for @%s", username)
                    return True
                else:
                    log.info("[IGBioVerifier] ❌ Bio fetched via Apify but code not found for @%s. Bio: %s", username, bio[:200])
                    return False  # We got the bio reliably; code is simply not there
        else:
            log.warning("[IGBioVerifier] No APIFY_TOKEN set, skipping Apify method.")

        # ── Method 2: Instagram mobile API ──────────
        log.info("[IGBioVerifier] Trying mobile API for @%s", username)
        bio = await self._try_mobile_api(username)
        if bio is not None:
            if code.lower() in bio.lower():
                log.info("[IGBioVerifier] ✅ Code found via mobile API for @%s", username)
                return True
            else:
                log.info("[IGBioVerifier] ❌ Bio fetched via mobile API but code not found for @%s", username)
                return False

        # ── Method 3: HTML scraping with proxies ────
        log.info("[IGBioVerifier] Trying HTML scraping for @%s", username)
        result = await self._try_html_scraping(username, code)
        if result is not None:
            return result

        log.warning("[IGBioVerifier] All methods failed for @%s", username)
        return False

    # ────────────────────────────────────────────────
    #  Method 1: Apify Instagram Profile Scraper
    # ────────────────────────────────────────────────

    async def _try_apify(self, username: str) -> Optional[str]:
        """
        Use Apify's Instagram Profile Scraper to fetch the bio.
        Uses the synchronous run endpoint for simplicity.
        """
        try:
            # Try the well-known profile scraper actor
            actor_id = "apify~instagram-profile-scraper"
            url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"

            payload = {
                "usernames": [username],
                "resultsLimit": 1,
            }

            async with httpx.AsyncClient(timeout=40.0) as client:
                log.info("[IGBioVerifier] Calling Apify actor %s for @%s", actor_id, username)
                resp = await client.post(
                    url,
                    params={"token": self.apify_token},
                    json=payload,
                )

                log.info("[IGBioVerifier] Apify response status: %s for @%s", resp.status_code, username)
                if 200 <= resp.status_code < 300:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        profile = data[0]
                        bio = profile.get("biography") or profile.get("bio") or profile.get("biographyText") or ""
                        log.info("[IGBioVerifier] Apify returned bio for @%s: '%s'", username, bio[:200])
                        return bio
                    else:
                        log.warning("[IGBioVerifier] Apify returned empty dataset for @%s", username)
                else:
                    log.warning("[IGBioVerifier] Apify returned status %s for @%s: %s",
                                resp.status_code, username, resp.text[:300])

                # Fallback: try the scraper with a different actor slug
                alt_actor_id = "apify~instagram-scraper"
                alt_url = f"https://api.apify.com/v2/acts/{alt_actor_id}/run-sync-get-dataset-items"

                alt_payload = {
                    "directUrls": [f"https://www.instagram.com/{username}/"],
                    "resultsType": "details",
                    "resultsLimit": 1,
                    "searchType": "user",
                }

                log.info("[IGBioVerifier] Trying alternative Apify actor %s for @%s", alt_actor_id, username)
                resp2 = await client.post(
                    alt_url,
                    params={"token": self.apify_token},
                    json=alt_payload,
                )

                if 200 <= resp2.status_code < 300:
                    data2 = resp2.json()
                    if isinstance(data2, list) and len(data2) > 0:
                        profile2 = data2[0]
                        bio = profile2.get("biography") or profile2.get("bio") or profile2.get("biographyText") or ""
                        log.info("[IGBioVerifier] Alt Apify returned bio for @%s: %s", username, bio[:200])
                        return bio
                else:
                    log.warning("[IGBioVerifier] Alt Apify returned status %s for @%s",
                                resp2.status_code, username)

        except asyncio.TimeoutError:
            log.warning("[IGBioVerifier] Apify request timed out for @%s", username)
        except Exception as e:
            log.error("[IGBioVerifier] Apify error for @%s: %s", username, e)

        return None

    # ────────────────────────────────────────────────
    #  Method 2: Instagram mobile web API
    # ────────────────────────────────────────────────

    async def _try_mobile_api(self, username: str) -> Optional[str]:
        """
        Try the i.instagram.com/api/v1/users/web_profile_info/ endpoint.
        This sometimes works with residential proxies.
        """
        attempts = 2
        for attempt in range(attempts):
            proxy_config = None

            if self.proxy_rotator:
                proxy_dict = await self.proxy_rotator.get_proxy()
                if proxy_dict:
                    server = proxy_dict['server']
                    user = proxy_dict.get('username')
                    pw = proxy_dict.get('password')
                    if user and pw:
                        from urllib.parse import urlparse
                        p = urlparse(server)
                        proxy_config = f"{p.scheme}://{user}:{pw}@{p.hostname}:{p.port}"
                    else:
                        proxy_config = server

            try:
                async with httpx.AsyncClient(
                    headers=_MOBILE_API_HEADERS,
                    follow_redirects=True,
                    timeout=12.0,
                    proxy=proxy_config,
                ) as client:
                    # Try the web_profile_info API
                    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
                    resp = await client.get(url)

                    if resp.status_code == 200:
                        data = resp.json()
                        user_data = data.get("data", {}).get("user", {})
                        if user_data:
                            bio = user_data.get("biography", "")
                            log.info("[IGBioVerifier] Mobile API returned bio for @%s", username)
                            return bio

                    # Try alternate mobile endpoint
                    url2 = f"https://i.instagram.com/api/v1/users/search/?query={username}"
                    resp2 = await client.get(url2)
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        users = data2.get("users", [])
                        for u in users:
                            if u.get("username", "").lower() == username.lower():
                                bio = u.get("biography", "")
                                if bio:
                                    log.info("[IGBioVerifier] Mobile search API returned bio for @%s", username)
                                    return bio

            except Exception as e:
                log.debug("[IGBioVerifier] Mobile API attempt %d failed: %s", attempt + 1, e)

            await asyncio.sleep(1.0)

        return None

    # ────────────────────────────────────────────────
    #  Method 3: HTML scraping (legacy fallback)
    # ────────────────────────────────────────────────

    async def _try_html_scraping(self, username: str, code: str) -> Optional[bool]:
        """
        Fallback: fetch the public HTML page and search for the code.
        Returns True/False if conclusive, None if inconclusive (couldn't fetch page).
        """
        attempts = 2
        for attempt in range(attempts):
            proxy_config = None
            server_display = "Direct"

            if self.proxy_rotator:
                proxy_dict = await self.proxy_rotator.get_proxy()
                if proxy_dict:
                    server = proxy_dict['server']
                    user = proxy_dict.get('username')
                    pw = proxy_dict.get('password')
                    if user and pw:
                        from urllib.parse import urlparse
                        p = urlparse(server)
                        proxy_config = f"{p.scheme}://{user}:{pw}@{p.hostname}:{p.port}"
                    else:
                        proxy_config = server
                    server_display = server

            try:
                async with httpx.AsyncClient(
                    headers=_BROWSER_HEADERS,
                    follow_redirects=True,
                    timeout=12.0,
                    proxy=proxy_config,
                ) as client:
                    url = f"https://www.instagram.com/{username}/"
                    resp = await client.get(url)

                    if resp.status_code != 200:
                        log.debug("[IGBioVerifier] HTML fetch failed: status %s", resp.status_code)
                        continue

                    # Check for login redirect
                    final_url = str(resp.url).lower()
                    if "login" in final_url and "login" not in url.lower():
                        log.debug("[IGBioVerifier] Redirected to login. Proxy blocked.")
                        if self.proxy_rotator and proxy_config:
                            await self.proxy_rotator.mark_failed(server_display)
                        continue

                    html = resp.text

                    # Quick raw search
                    if code.lower() in html.lower():
                        log.info("[IGBioVerifier] ✅ Code found via raw HTML for @%s", username)
                        return True

                    # Try extracting bio from JSON in page
                    bio = self._extract_bio_from_script(html)
                    if bio and code.lower() in bio.lower():
                        log.info("[IGBioVerifier] ✅ Code found in script bio for @%s", username)
                        return True

                    bio = self._extract_bio_from_shared_data(html)
                    if bio and code.lower() in bio.lower():
                        log.info("[IGBioVerifier] ✅ Code found in SharedData bio for @%s", username)
                        return True

                    bio = self._extract_bio_from_meta(html)
                    if bio and code.lower() in bio.lower():
                        log.info("[IGBioVerifier] ✅ Code found in meta bio for @%s", username)
                        return True

                    log.debug("[IGBioVerifier] HTML loaded but code not found for @%s", username)

            except Exception as e:
                log.debug("[IGBioVerifier] HTML attempt %d error: %s", attempt + 1, e)

            await asyncio.sleep(1.0)

        return None  # Inconclusive

    # ────────────────────────────────────────────────
    #  Extraction helpers
    # ────────────────────────────────────────────────

    def _extract_bio_from_script(self, html: str) -> Optional[str]:
        """Try to find biography in JSON script tags."""
        try:
            match = re.search(r'"biography"\s*:\s*"([^"]+)"', html)
            if match:
                bio = match.group(1).encode('utf-16', 'surrogatepass').decode('utf-16')
                return bio
        except Exception:
            pass
        return None

    def _extract_bio_from_shared_data(self, html: str) -> Optional[str]:
        """Extract bio from window._sharedData JSON object."""
        try:
            match = re.search(r'window\._sharedData\s*=\s*({.+?});', html)
            if match:
                data = json.loads(match.group(1))
                user = data.get("entry_data", {}).get("ProfilePage", [{}])[0].get("graphql", {}).get("user", {})
                return user.get("biography")
        except Exception:
            pass
        return None

    def _extract_bio_from_meta(self, html: str) -> Optional[str]:
        """Extract bio from <meta name="description"> tag."""
        try:
            patterns = [
                r'<meta\s+(?:name|property)=["\'](?:og:description|description)["\']\s+content=["\']([^"\']*)["\']',
                r'<meta\s+content=["\']([^"\']*)["\']\\s+(?:name|property)=["\'](?:og:description|description)["\']',
                r'"description"\s*:\s*"([^"]+)"'
            ]
            for pattern in patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    description = match.group(1)
                    if "Followers," in description and "-" in description:
                        parts = description.rsplit("-", 1)
                        return parts[-1].strip()
                    return description
        except Exception:
            pass
        return None
