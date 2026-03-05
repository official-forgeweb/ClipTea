import os
import aiohttp
import asyncio
import time
import json
from typing import Dict, Any, Optional
from database.manager import DatabaseManager
from config import PAGE_TIMEOUT

class ApifyInstagramService:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.apify_token = os.getenv("APIFY_TOKEN")
        self.actor_id = os.getenv("APIFY_ACTOR_ID", "apify/instagram-post-scraper")
        self.cache_ttl = 7200  # 2 hours in seconds

    async def get_video_metrics(self, video_url: str) -> dict:
        """
        Main entry point to get metrics.
        Checks cache first, then calls Apify. If Apify fails, returns fallback structure.
        """
        # 1. Extract shortcode
        shortcode = self._extract_shortcode(video_url)
        if not shortcode:
            return self._build_estimation_fallback(video_url)

        # 2. Check Cache
        cached_data = await self._get_from_cache(shortcode)
        if cached_data:
            age = time.time() - cached_data.get('fetched_at_ts', 0)
            if age < self.cache_ttl:
                return {
                    "views": int(cached_data.get('views', 0)),
                    "likes": int(cached_data.get('likes', 0)),
                    "comments": int(cached_data.get('comments', 0)),
                    "author_username": cached_data.get('author_username', ''),
                    "method": "cache",
                    "estimated": False,
                    "cached": True
                }

        # 3. If no token, return estimation directly
        if not self.apify_token:
            return self._build_estimation_fallback(video_url)

        # 4. Call Apify
        apify_result = await self._call_apify_sync(video_url, shortcode)
        
        if apify_result:
            return apify_result
            
        return self._build_estimation_fallback(video_url)

    async def _call_apify_sync(self, video_url: str, shortcode: str) -> Optional[dict]:
        """Calls Apify run-sync-get-dataset-items."""
        url = f"https://api.apify.com/v2/acts/{self.actor_id}/run-sync-get-dataset-items"
        headers = {
            "Authorization": f"Bearer {self.apify_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "directUrls": [video_url],
            "resultsLimit": 1
        }
        
        start_time = time.time()
        success = False
        credits_used = 0.001  # Base estimate

        try:
            # 60 seconds timeout as requested
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=60) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            item = data[0]
                            parsed = self._parse_apify_item(item)
                            
                            # Cache the successful result
                            await self._save_to_cache(
                                shortcode=shortcode,
                                views=parsed['views'],
                                likes=parsed['likes'],
                                comments=parsed['comments'],
                                author=parsed['author_username'],
                                raw=json.dumps(item)
                            )
                            success = True
                            
                            await self._log_api_usage(
                                endpoint="/run-sync-get-dataset-items",
                                shortcode=shortcode,
                                credits=credits_used,
                                success=True
                            )
                            return parsed
                    else:
                        print(f"[Apify] API Error: {response.status} - {await response.text()}")
        except asyncio.TimeoutError:
            print(f"[Apify] Timeout after 60s for {video_url}")
        except Exception as e:
            print(f"[Apify] Exception for {video_url}: {e}")

        # Log failure
        await self._log_api_usage(
            endpoint="/run-sync-get-dataset-items",
            shortcode=shortcode,
            credits=credits_used,
            success=False
        )
        return None

    def _parse_apify_item(self, item: dict) -> dict:
        """Parses the messy Apify response handling all naming variations."""
        views_keys = ['videoViewCount', 'videoPlayCount', 'video_view_count', 'video_play_count', 'playCount', 'viewCount', 'views']
        likes_keys = ['likesCount', 'likes_count', 'likeCount', 'like_count', 'likes']
        comments_keys = ['commentsCount', 'comments_count', 'commentCount', 'comment_count', 'comments']
        
        views = 0
        likes = 0
        comments = 0
        author_username = ""

        # Find views
        for k in views_keys:
            if k in item and item[k] is not None:
                views = int(item[k])
                break
                
        # Find likes
        for k in likes_keys:
            if k in item and item[k] is not None:
                likes = int(item[k])
                break
                
        # Find comments
        for k in comments_keys:
            if k in item and item[k] is not None:
                comments = int(item[k])
                break
                
        # Find author
        if 'ownerUsername' in item: author_username = item['ownerUsername']
        elif 'owner_username' in item: author_username = item['owner_username']
        elif 'username' in item: author_username = item['username']
        elif 'owner' in item and isinstance(item['owner'], dict) and 'username' in item['owner']:
            author_username = item['owner']['username']
            
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "author_username": author_username,
            "method": "apify",
            "estimated": False,
            "cached": False
        }

    def _build_estimation_fallback(self, video_url: str) -> dict:
        """Fallback to estimation if Apify fails/timeouts/missing token."""
        return {
            "views": 0,
            "likes": 0,
            "comments": 0,
            "author_username": "",
            "method": "estimation",
            "estimated": True,
            "cached": False
        }

    def _extract_shortcode(self, url: str) -> str:
        """Extract shortcode from IG url."""
        import re
        match = re.search(r'instagram\.com/(?:reel|p)/([\w-]+)', url)
        if match:
            return match.group(1)
        return ""

    async def _get_from_cache(self, shortcode: str) -> Optional[dict]:
        """Fetch from sqlite cache."""
        import aiosqlite
        try:
            async with aiosqlite.connect(self.db.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT *, strftime('%s', fetched_at) as fetched_at_ts FROM apify_cache WHERE shortcode = ?", 
                    (shortcode,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception:
            return None
            
    async def _save_to_cache(self, shortcode: str, views: int, likes: int, comments: int, author: str, raw: str):
        """Save to sqlite cache."""
        import aiosqlite
        try:
            async with aiosqlite.connect(self.db.db_path) as db:
                await db.execute('''
                    INSERT INTO apify_cache (shortcode, views, likes, comments, author_username, raw_response, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(shortcode) DO UPDATE SET 
                        views = ?, likes = ?, comments = ?,
                        author_username = ?, raw_response = ?, fetched_at = CURRENT_TIMESTAMP
                ''', (shortcode, views, likes, comments, author, raw,
                      views, likes, comments, author, raw))
                await db.commit()
        except Exception as e:
            print(f"[Apify] Cache save error: {e}")

    async def _log_api_usage(self, endpoint: str, shortcode: str, credits: float, success: bool):
        """Log API Usage."""
        import aiosqlite
        try:
            async with aiosqlite.connect(self.db.db_path) as db:
                await db.execute('''
                    INSERT INTO api_usage (service, endpoint, shortcode, credits_used, success)
                    VALUES ('apify', ?, ?, ?, ?)
                ''', (endpoint, shortcode, credits, 1 if success else 0))
                await db.commit()
        except Exception as e:
            print(f"[Apify] API logging error: {e}")
