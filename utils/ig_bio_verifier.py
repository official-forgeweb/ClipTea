"""
Instagram bio code verifier.
Checks a public Instagram profile's bio for a specific verification code
using proxies from the bot's pool to avoid blocks.
"""

import re
import asyncio
import logging
import json
import httpx
from typing import Optional, List

log = logging.getLogger(__name__)

# Headers that mimic a regular browser / mobile app
_HEADERS = {
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


class IGBioVerifier:
    """Async verifier that checks for a code string inside an Instagram user's bio."""

    def __init__(self, proxy_rotator=None, timeout: float = 20.0):
        self.proxy_rotator = proxy_rotator
        self.timeout = timeout

    async def check_bio(self, username: str, code: str) -> bool:
        """
        Return True if `code` appears anywhere in `username`'s Instagram bio.
        Tries multiple methods in sequence:
          1. Instagram's unofficial JSON endpoint (?__a=1)
          2. Plain HTML page — extract bio from script tags (JSON)
          3. Plain HTML page — extract bio from <meta name="description"> tag
          4. Fallback — Search entire HTML for the code string
        """
        username = username.lstrip("@").strip()
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

    async def _check(self, username: str, code: str) -> bool:
        """
        Main check logic with a retry loop using different proxies.
        """
        attempts = 3
        last_exception = None
        
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
                    log.info("[IGBioVerifier] Attempt %d/%d using proxy: %s", attempt + 1, attempts, server_display)
            
            try:
                async with httpx.AsyncClient(
                    headers=_HEADERS,
                    follow_redirects=True,
                    timeout=15.0, # Shorter timeout per attempt
                    proxy=proxy_config
                ) as client:
                    
                    # 1. Try JSON API (only on first attempt, as it's most sensitive)
                    if attempt == 0:
                        bio = await self._try_json_api(client, username)
                        if bio and code.lower() in bio.lower():
                            log.info("[IGBioVerifier] Code found via JSON API for @%s", username)
                            return True

                    # 2. Try HTML scraping
                    html = await self._get_html(client, username)
                    if html:
                        if html == "PRIVATE_ACCOUNT_DETECTED":
                            log.warning("[IGBioVerifier] @%s is PRIVATE. Verification impossible.", username)
                            return False # Private accounts can't be verified via bio scraping
                            
                        # Success! We got the page.
                        if code.lower() in html.lower():
                            log.info("[IGBioVerifier] Code found in HTML for @%s (Attempt %d)", username, attempt + 1)
                            return True
                        
                        # Check specific extractions for logging
                        bio_script = self._extract_bio_from_script(html)
                        if bio_script and code.lower() in bio_script.lower():
                            return True
                            
                        meta_bio = self._extract_bio_from_meta(html)
                        if meta_bio and code.lower() in meta_bio.lower():
                            return True
                        
                        # If we got the HTML but code wasn't found, it's likely not there.
                        # However, we'll try one more proxy just in case we got a partial page or wrong language.
                        log.debug("[IGBioVerifier] HTML loaded but code not found for @%s. Retrying...", username)
                    else:
                        log.debug("[IGBioVerifier] Failed to get HTML for @%s via %s. Retrying...", username, server_display)
                        # Mark proxy as failed if it was blocked
                        if self.proxy_rotator and proxy_config:
                            await self.proxy_rotator.mark_failed(server_display)

            except Exception as e:
                log.error("[IGBioVerifier] Attempt %d failed: %s", attempt + 1, e)
                last_exception = e
                if self.proxy_rotator and proxy_config:
                    await self.proxy_rotator.mark_failed(server_display)
            
            # Small delay between retries
            await asyncio.sleep(1.5)

        log.warning("[IGBioVerifier] Verification failed for @%s after %d attempts.", username, attempts)
        return False

    async def _try_json_api(self, client: httpx.AsyncClient, username: str) -> Optional[str]:
        """Try Instagram's ?__a=1 JSON endpoint."""
        try:
            url = f"https://www.instagram.com/{username}/?__a=1&__d=dis"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                user = data.get("graphql", {}).get("user") or data.get("data", {}).get("user") or data.get("user")
                if user:
                    return user.get("biography") or user.get("bio", "")
        except Exception:
            pass
        return None

    async def _get_html(self, client: httpx.AsyncClient, username: str) -> Optional[str]:
        """Fetch the public HTML profile page."""
        try:
            url = f"https://www.instagram.com/{username}/"
            resp = await client.get(url)
            
            if resp.status_code == 404:
                log.warning("[IGBioVerifier] Profile @%s NOT FOUND (404).", username)
                return None
                
            if resp.status_code != 200:
                log.debug("[IGBioVerifier] HTML fetch failed for @%s (Status: %s)", username, resp.status_code)
                return None
            
            # Check for login redirection
            final_url = str(resp.url).lower()
            if "login" in final_url and "login" not in url.lower():
                log.warning("[IGBioVerifier] Redirected to login for @%s. Proxy is blocked.", username)
                return None
                
            text = resp.text
            
            # Check for private account
            if "This Account is Private" in text or "is_private\":true" in text.lower():
                log.warning("[IGBioVerifier] Account @%s is PRIVATE. Cannot read bio.", username)
                return "PRIVATE_ACCOUNT_DETECTED" # Special token
                
            return text
        except Exception as exc:
            log.debug("[IGBioVerifier] HTML fetch error for @%s: %s", username, exc)
        return None

    def _extract_bio_from_script(self, html: str) -> Optional[str]:
        """Try to find biography in JSON script tags."""
        try:
            # Look for "biography":"..." or biography: "..."
            match = re.search(r'"biography"\s*:\s*"([^"]+)"', html)
            if match:
                # Handle unicode escapes
                bio = match.group(1).encode('utf-16', 'surrogatepass').decode('utf-16')
                return bio
        except Exception:
            pass
        return None

    def _extract_bio_from_meta(self, html: str) -> Optional[str]:
        """Extract bio from <meta name="description"> tag."""
        try:
            match = re.search(
                r'<meta\s+(?:name|property)=["\'](?:og:description|description)["\']\s+content=["\']([^"\']*)["\']',
                html, re.IGNORECASE
            )
            if not match:
                match = re.search(
                    r'<meta\s+content=["\']([^"\']*)["\']\s+(?:name|property)=["\'](?:og:description|description)["\']',
                    html, re.IGNORECASE
                )
            
            if match:
                description = match.group(1)
                # Description usually has stats at start, bio at end
                if "Followers," in description and "-" in description:
                    parts = description.rsplit("-", 1)
                    return parts[-1].strip()
                return description
        except Exception:
            pass
        return None
