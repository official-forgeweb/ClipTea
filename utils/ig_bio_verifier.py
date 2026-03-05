"""
Instagram bio code verifier.
Checks a public Instagram profile's bio for a specific verification code
without requiring login, proxies, or a browser — uses httpx + BeautifulSoup
on the lightweight mobile API endpoint, with an HTML fallback.
"""

import re
import asyncio
import logging
import httpx

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
}


class IGBioVerifier:
    """Async verifier that checks for a code string inside an Instagram user's bio."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    async def check_bio(self, username: str, code: str) -> bool:
        """
        Return True if `code` appears anywhere in `username`'s Instagram bio.
        Tries two methods in sequence:
          1. Instagram's unofficial JSON endpoint (?__a=1)
          2. Plain HTML page — extract bio from <meta name="description"> tag
        Returns False if both fail (network error, account private, etc.)
        """
        username = username.lstrip("@").strip()
        code = code.strip()

        try:
            result = await asyncio.wait_for(
                self._check(username, code), timeout=self.timeout
            )
            return result
        except asyncio.TimeoutError:
            log.warning("[IGBioVerifier] Timed out checking @%s", username)
            return False
        except Exception as exc:
            log.warning("[IGBioVerifier] Unexpected error for @%s: %s", username, exc)
            return False

    async def _check(self, username: str, code: str) -> bool:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=self.timeout,
        ) as client:
            # Method 1: Unofficial JSON API
            bio = await self._try_json_api(client, username)
            if bio is not None:
                log.info("[IGBioVerifier] Got bio via JSON for @%s: %r", username, bio[:80])
                return code.lower() in bio.lower()

            # Method 2: HTML meta description
            bio = await self._try_html(client, username)
            if bio is not None:
                log.info("[IGBioVerifier] Got bio via HTML for @%s: %r", username, bio[:80])
                return code.lower() in bio.lower()

        log.warning("[IGBioVerifier] Could not retrieve bio for @%s", username)
        return False

    async def _try_json_api(self, client: httpx.AsyncClient, username: str):
        """Try Instagram's ?__a=1 JSON endpoint. Returns bio string or None."""
        try:
            url = f"https://www.instagram.com/{username}/?__a=1&__d=dis"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                # Navigate the JSON to find the biography field
                user = (
                    data.get("graphql", {}).get("user")
                    or data.get("data", {}).get("user")
                    or data.get("user")
                )
                if user:
                    bio = user.get("biography") or user.get("bio", "")
                    return bio
        except Exception as exc:
            log.debug("[IGBioVerifier] JSON API failed for @%s: %s", username, exc)
        return None

    async def _try_html(self, client: httpx.AsyncClient, username: str):
        """
        Scrape the public HTML profile page and extract the bio from:
          <meta name="description" content="X Followers, Y Following, Z Posts ...bio text...">
        Instagram puts the bio as the last part of this description tag.
        Returns bio string or None.
        """
        try:
            url = f"https://www.instagram.com/{username}/"
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text
            # Extract meta description
            match = re.search(
                r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']',
                html,
                re.IGNORECASE,
            )
            if not match:
                # Try the other attribute order
                match = re.search(
                    r'<meta\s+content=["\']([^"\']*)["\']\s+name=["\']description["\']',
                    html,
                    re.IGNORECASE,
                )
            if match:
                description = match.group(1)
                # The description is formatted as:
                # "X Followers, Y Following, Z Posts - See Instagram photos ... - bio"
                # Bio typically appears after the last " - "
                parts = description.rsplit(" - ", 1)
                bio = parts[-1] if len(parts) > 1 else description
                return bio
        except Exception as exc:
            log.debug("[IGBioVerifier] HTML scrape failed for @%s: %s", username, exc)
        return None
