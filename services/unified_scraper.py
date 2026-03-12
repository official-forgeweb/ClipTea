import sys
from typing import Optional, Dict, Any

from utils.platform_detector import detect_platform
from services.apify_instagram import ApifyInstagramService
from services.tiktok_scraper import TikTokApifyService
from services.twitter_scraper import TwitterApifyService
from services.youtube_api import YouTubeService
from database.manager import DatabaseManager

class UnifiedScraper:
    """Single entry point for fetching video metrics across all supported platforms.
    Auto-detects platform from URL and delegates to the correct service."""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db
        self.instagram = ApifyInstagramService(db)
        self.tiktok = TikTokApifyService(db)
        self.twitter = TwitterApifyService(db)
        self.youtube = YouTubeService()
        
    async def get_video_metrics(self, url: str, platform: str = None, use_cache: bool = True) -> Dict[str, Any]:
        """Get metrics for any supported video URL.
        
        If platform is not provided, it will be auto-detected from the URL.
        
        Returns a standardized dictionary with keys:
        - views
        - likes
        - comments
        - shares
        - author_username
        - posted_at
        - platform
        - error (if failed)
        """
        # Determine platform
        if not platform:
            platform = detect_platform(url)
            
        if not platform:
            return {
                "error": "Unsupported or unrecognized URL format",
                "platform": "unknown"
            }
            
        print(f"[UnifiedScraper] Processing {platform} URL: {url} (use_cache={use_cache})")
        
        try:
            # Delegate to appropriate service
            if platform == "instagram":
                result = await self.instagram.get_video_metrics(url, use_cache=use_cache)
            elif platform == "tiktok":
                result = await self.tiktok.get_video_metrics(url, use_cache=use_cache)
            elif platform == "twitter":
                result = await self.twitter.get_video_metrics(url, use_cache=use_cache)
            elif platform == "youtube":
                result = await self.youtube.get_video_metrics(url) # YouTube doesn't have local cache table
            else:
                return {
                    "error": f"Scraper not implemented for platform: {platform}",
                    "platform": platform
                }
                
            # Add platform info to result if successful
            if result and not result.get("error"):
                result["platform"] = platform
                
            return result
            
        except Exception as e:
            print(f"[UnifiedScraper] Error fetching {platform} metrics: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": f"Internal error during scrape: {str(e)}",
                "platform": platform
            }
