import asyncio
from typing import Dict, Any, Callable
from database.manager import DatabaseManager
from anti_detection.proxy_rotator import ProxyRotator
from anti_detection.rate_limiter import RateLimiter
from scrapers.instagram_scraper import InstagramScraper
from scrapers.tiktok_scraper import TikTokScraper
from scrapers.twitter_scraper import TwitterScraper
from config import MAX_POSTS_PER_USER

class CampaignManager:
    """Orchestrates the scraping workflow for a campaign."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.proxy_rotator = ProxyRotator()
        self.rate_limiter = RateLimiter()
        
        self.scrapers = {
            "instagram": InstagramScraper(self.proxy_rotator, self.rate_limiter),
            "tiktok": TikTokScraper(self.proxy_rotator, self.rate_limiter),
            "twitter": TwitterScraper(self.proxy_rotator, self.rate_limiter)
        }
        
    async def initialize(self):
        """Initializes proxies before use."""
        await self.proxy_rotator.initialize()
        
    async def fetch_campaign_data(self, campaign_id: str, progress_callback: Callable = None) -> Dict[str, Any]:
        """Fetches fresh metrics for all users in a campaign."""
        users = await self.db.get_campaign_users(campaign_id)
        if not users:
            return {"success": False, "message": "No users found in campaign."}
            
        summary = {
            "total_users": len(users),
            "successful_users": 0,
            "failed_users": 0,
            "total_posts_found": 0,
            "errors": []
        }
        
        for i, user in enumerate(users):
            username = user["username"]
            platform = user["platform"]
            user_id = user["id"]
            
            if progress_callback:
                await progress_callback(f"Fetching {platform} user @{username} ({i+1}/{len(users)})...")
                
            scraper = self.scrapers.get(platform)
            if not scraper:
                summary["failed_users"] += 1
                summary["errors"].append(f"No scraper for {platform}")
                continue
                
            try:
                # Scrape recent posts
                posts = await scraper.scrape_user_posts(username, max_posts=MAX_POSTS_PER_USER)
                
                if posts:
                    summary["total_posts_found"] += len(posts)
                    # Save post and metrics to DB
                    for post in posts:
                        await self.db.save_post_and_metrics(user_id, platform, post)
                    summary["successful_users"] += 1
                else:
                    summary["failed_users"] += 1
                    summary["errors"].append(f"No posts found for @{username} on {platform}")
                    
                # Delay between users
                await asyncio.sleep(2.0)
                
            except Exception as e:
                summary["failed_users"] += 1
                summary["errors"].append(f"Error for @{username}: {str(e)}")
                
        return {"success": True, "summary": summary}
