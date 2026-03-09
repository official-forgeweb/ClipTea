import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timezone, timedelta
from database.manager import DatabaseManager
from anti_detection.proxy_rotator import ProxyRotator
from anti_detection.rate_limiter import RateLimiter
from scrapers.instagram_scraper import InstagramScraper
from scrapers.tiktok_scraper import TikTokScraper
from scrapers.twitter_scraper import TwitterScraper


class CampaignManager:
    """Orchestrates scraping workflows for campaigns. 
    Now focused on video-submission-based scraping rather than profile scraping."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.proxy_rotator = ProxyRotator()
        self.rate_limiter = RateLimiter()

        from services.apify_instagram import ApifyInstagramService
        self.apify_service = ApifyInstagramService(self.db)

        self.scrapers = {
            "tiktok": TikTokScraper(self.proxy_rotator, self.rate_limiter),
            "twitter": TwitterScraper(self.proxy_rotator, self.rate_limiter),
        }

    async def initialize(self):
        """Initialize proxies before use."""
        await self.proxy_rotator.initialize()

    def get_scraper(self, platform: str):
        """Get the scraper for a given platform."""
        return self.scrapers.get(platform)

    async def scrape_video(self, video_url: str, platform: str) -> Optional[Dict[str, Any]]:
        """Scrape a single video URL and return full data including author."""
        if platform == "instagram":
            return await self.apify_service.get_video_metrics(video_url)
            
        scraper = self.get_scraper(platform)
        if not scraper:
            return None

        try:
            return await scraper.scrape_single_video(video_url)
        except Exception as e:
            print(f"[CampaignManager] Error scraping {video_url}: {e}")
            return None

    async def scrape_video_metrics(self, video_url: str, platform: str) -> Optional[Dict[str, Any]]:
        """Scrape just the metrics for a video (for periodic re-scraping)."""
        if platform == "instagram":
            return await self.apify_service.get_video_metrics(video_url)
            
        scraper = self.get_scraper(platform)
        if not scraper:
            return None

        try:
            return await scraper.scrape_post_metrics(video_url)
        except Exception as e:
            print(f"[CampaignManager] Error scraping metrics for {video_url}: {e}")
            return None

    async def scrape_all_tracking_videos(self, progress_callback: Callable = None) -> Dict[str, Any]:
        """Scrape metrics for all actively tracked videos across all active campaigns."""
        videos = await self.db.get_all_tracking_videos()

        summary = {
            "total_videos": len(videos),
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

        for i, video in enumerate(videos):
            video_url = video["video_url"]
            platform = video["platform"]
            video_id = video["id"]

            if progress_callback:
                await progress_callback(
                    f"Scraping {platform} video {i + 1}/{len(videos)}..."
                )

            # Check for 24h expiration
            exp_at_str = video.get('tracking_expires_at')
            if exp_at_str:
                try:
                    exp_at = datetime.fromisoformat(exp_at_str.replace("Z", "+00:00"))
                    if exp_at.tzinfo is None:
                        exp_at = exp_at.replace(tzinfo=timezone.utc)

                    if datetime.now(timezone.utc) > exp_at:
                        # Finalize it
                        metrics = await self.db.get_latest_metrics(video_id)
                        if not metrics:
                            metrics = {}
                        await self.db.mark_video_final(
                            video_id,
                            metrics.get('views', 0),
                            metrics.get('likes', 0),
                            metrics.get('comments', 0)
                        )
                        print(f"[CampaignManager] Finalized expired video {video_id}")
                        continue
                except Exception as e:
                    print(f"[CampaignManager] Expiration error: {e}")
                    pass

            try:
                metrics = await self.scrape_video_metrics(video_url, platform)
                if metrics:
                    await self.db.save_metric_snapshot(
                        video_id=video_id,
                        views=metrics.get("views", 0),
                        likes=metrics.get("likes", 0),
                        comments=metrics.get("comments", 0),
                        shares=metrics.get("shares", 0),
                    )
                    summary["successful"] += 1
                else:
                    summary["failed"] += 1
                    summary["errors"].append(f"No metrics returned for {video_url}")
            except Exception as e:
                summary["failed"] += 1
                summary["errors"].append(f"Error for {video_url}: {str(e)}")

            # Small delay between videos
            await asyncio.sleep(1.5)

        return summary

    async def fetch_campaign_data(self, campaign_id: str, progress_callback: Callable = None) -> Dict[str, Any]:
        """Fetch fresh metrics for all submitted videos in a campaign."""
        videos = await self.db.get_campaign_videos(campaign_id)
        if not videos:
            return {"success": False, "message": "No submitted videos in this campaign."}

        summary = {
            "total_videos": len(videos),
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

        for i, video in enumerate(videos):
            video_url = video["video_url"]
            platform = video["platform"]
            video_id = video["id"]

            if progress_callback:
                await progress_callback(
                    f"Scraping {platform} video {i + 1}/{len(videos)}..."
                )

            # Expiration check
            exp_at_str = video.get('tracking_expires_at')
            if exp_at_str:
                try:
                    exp_at = datetime.fromisoformat(exp_at_str.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) > exp_at:
                        # Finalize
                        metrics = await self.db.get_latest_metrics(video_id)
                        if not metrics:
                            metrics = {}
                        await self.db.mark_video_final(
                            video_id,
                            metrics.get('views', 0),
                            metrics.get('likes', 0),
                            metrics.get('comments', 0)
                        )
                        continue
                except: pass

            try:
                metrics = await self.scrape_video_metrics(video_url, platform)
                if metrics:
                    await self.db.save_metric_snapshot(
                        video_id=video_id,
                        views=metrics.get("views", 0),
                        likes=metrics.get("likes", 0),
                        comments=metrics.get("comments", 0),
                        shares=metrics.get("shares", 0),
                    )
                    summary["successful"] += 1
                else:
                    summary["failed"] += 1
                    summary["errors"].append(f"No metrics for {video_url}")
            except Exception as e:
                summary["failed"] += 1
                summary["errors"].append(f"Error: {str(e)}")

            await asyncio.sleep(1.5)

        return {"success": True, "summary": summary}
