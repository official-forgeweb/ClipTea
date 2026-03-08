"""
Universal Bio Verifier.
Checks a public social media profile's bio / description for a specific code.
Supports: Instagram, TikTok, Twitter/X, and YouTube.
"""

import logging
from typing import Optional
from utils.ig_bio_verifier import IGBioVerifier
from services.tiktok_scraper import TikTokApifyService
from services.twitter_scraper import TwitterApifyService
from services.youtube_api import YouTubeService
from anti_detection.proxy_rotator import ProxyRotator

log = logging.getLogger(__name__)

class UniversalBioVerifier:
    """Async verifier that works across multiple social platforms."""

    def __init__(self, proxy_rotator: Optional[ProxyRotator] = None):
        self.proxy_rotator = proxy_rotator
        self.ig_verifier = IGBioVerifier(proxy_rotator=proxy_rotator, timeout=45.0)
        self.tiktok_verifier = TikTokApifyService()
        self.twitter_verifier = TwitterApifyService()
        self.youtube_verifier = YouTubeService()

    async def check_bio(self, platform: str, username: str, code: str) -> bool:
        """
        Return True if `code` appears anywhere in the `username`'s profile bio on `platform`.
        """
        platform = platform.lower()
        code = code.strip().lower()
        
        if platform == "instagram":
            return await self.ig_verifier.check_bio(username, code)
            
        elif platform == "tiktok":
            log.info("[UniversalVerifier] Checking TikTok bio for @%s", username)
            bio = await self.tiktok_verifier.get_profile_bio(username)
            return self._contains_code(bio, code)
            
        elif platform == "twitter":
            log.info("[UniversalVerifier] Checking Twitter bio for @%s", username)
            bio = await self.twitter_verifier.get_profile_bio(username)
            return self._contains_code(bio, code)
            
        elif platform == "youtube":
            log.info("[UniversalVerifier] Checking YouTube bio/description for @%s", username)
            bio = await self.youtube_verifier.get_channel_description(username)
            return self._contains_code(bio, code)
            
        else:
            log.error("[UniversalVerifier] Unsupported platform: %s", platform)
            return False

    def _contains_code(self, bioText: Optional[str], code: str) -> bool:
        if not bioText:
            return False
        return code in bioText.lower()
