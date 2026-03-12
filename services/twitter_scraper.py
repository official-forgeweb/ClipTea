import aiohttp
import asyncio
import json
import re
import os
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional

class TwitterApifyService:
    """Fetch Twitter/X post metrics using Apify."""
    
    BASE_URL = "https://api.apify.com/v2"
    
    def __init__(self, db_path=None):
        self.token = os.getenv("APIFY_TOKEN", "")
        actor_id_raw = os.getenv("TWITTER_ACTOR_ID", "apidojo/tweet-scraper")
        self.actor_id = actor_id_raw.replace("/", "~")
        self.cache_duration_minutes = 120
        
        if db_path is None:
            try:
                from config import DATABASE_PATH
                self.db_path = DATABASE_PATH
            except ImportError:
                self.db_path = "cliptea.db"
        elif isinstance(db_path, str):
            self.db_path = db_path
        else:
            if hasattr(db_path, 'db_path'): self.db_path = db_path.db_path
            elif hasattr(db_path, 'database_path'): self.db_path = db_path.database_path
            elif hasattr(db_path, 'path'): self.db_path = db_path.path
            else: self.db_path = "cliptea.db"

    async def get_video_metrics(self, video_url: str, use_cache: bool = True) -> dict:
        """Get metrics for a Twitter/X post. Checks cache first."""
        video_id = self._extract_video_id(video_url)
        if not video_id:
            return {"error": "Could not extract Twitter status ID"}

        # 1. Check cache
        if use_cache:
            cached = await self._get_from_cache(video_id)
            if cached:
                return cached

        # 2. Call Apify
        if not self.token:
            return {"error": "Apify token not configured"}
            
        result = await self._call_apify(video_url, video_id)
        if result and not result.get("error"):
            await self._save_to_cache(video_id, result)
            return result
            
        return result or {"error": "Failed to fetch from Apify"}

    async def _call_apify(self, video_url: str, video_id: str) -> Optional[dict]:
        url = f"{self.BASE_URL}/acts/{self.actor_id}/run-sync-get-dataset-items?token={self.token}"
        
        # apidojo/tweet-scraper typically takes 'startUrls'
        payload = {
            "startUrls": [{"url": video_url}],
            "maxItems": 1
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                print(f"[Twitter] Calling Apify for {video_url}")
                async with session.post(url, json=payload, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status not in (200, 201):
                        print(f"[Twitter] API Error: {resp.status} - {text[:200]}")
                        return {"error": f"Apify returned {resp.status}"}
                        
                    try:
                        data = json.loads(text)
                    except:
                        return {"error": "Invalid Apify JSON response"}
                        
                    if isinstance(data, list) and len(data) > 0:
                        item = data[0]
                    elif isinstance(data, dict):
                        items = data.get("items", data.get("data", []))
                        if isinstance(items, list) and len(items) > 0:
                            item = items[0]
                        else:
                            item = data
                    else:
                        return {"error": "Unexpected Apify response format"}
                        
                    return self._parse_response(item)
                    
        except asyncio.TimeoutError:
            return {"error": "Twitter scrape timed out (120s)"}
        except Exception as e:
            return {"error": f"Error: {str(e)}"}

    def _parse_response(self, item: dict) -> dict:
        """Extract metrics mapping Twitter impressions/retweets to standard formats."""
        # Views -> Impressions in Twitter terms
        views = (item.get("viewCount") or item.get("views") or 
                 item.get("impressionsCount") or 0)
        
        # Likes
        likes = (item.get("likeCount") or item.get("likes") or item.get("favoriteCount") or 0)
                 
        # Comments -> Replies
        comments = (item.get("replyCount") or item.get("replies") or 0)
                    
        # Shares -> Retweets/Quotes
        retweets = item.get("retweetCount") or item.get("retweets") or 0
        quotes = item.get("quoteCount") or item.get("quotes") or 0
        try: retweet_total = int(retweets) + int(quotes)
        except: retweet_total = 0
                  
        # Author
        author = item.get("author", {}).get("userName") or \
                 item.get("user", {}).get("screen_name") or \
                 item.get("screen_name") or \
                 item.get("authorMeta", {}).get("name") or ""
                 
        # To string and int conversions
        try: views = int(views)
        except: views = 0
        try: likes = int(likes)
        except: likes = 0
        try: comments = int(comments)
        except: comments = 0
        
        caption = item.get("text") or item.get("full_text") or ""
        posted_at = item.get("createdAt") or item.get("created_at") or None

        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": retweet_total,
            "author_username": author,
            "caption": str(caption)[:200],
            "posted_at": posted_at,
            "method": "live",
            "estimated": False,
            "cached": False,
            # Twitter-specific extras that unified_scraper can pull if needed
            "bookmarks": item.get("bookmarkCount") or 0
        }

    async def _get_from_cache(self, video_id: str) -> Optional[dict]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("SELECT * FROM apify_cache WHERE shortcode = ?", (video_id,))
                row = await cursor.fetchone()
                
                if not row: return None
                
                fetched_at = datetime.fromisoformat(str(row["fetched_at"]))
                if datetime.now() - fetched_at > timedelta(minutes=self.cache_duration_minutes):
                    return None
                    
                return {
                    "views": row["views"],
                    "likes": row["likes"],
                    "comments": row["comments"],
                    "shares": row["shares"] if "shares" in row.keys() else 0,
                    "author_username": row["author_username"],
                    "posted_at": row.get("posted_at") if "posted_at" in row.keys() else None,
                    "method": "cache",
                    "estimated": False,
                    "cached": True
                }
        except: return None

    async def _save_to_cache(self, video_id: str, data: dict):
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO apify_cache 
                    (shortcode, views, likes, comments, shares, author_username, posted_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(shortcode) DO UPDATE SET
                        views = excluded.views, likes = excluded.likes,
                        comments = excluded.comments, shares = excluded.shares,
                        author_username = excluded.author_username,
                        posted_at = COALESCE(excluded.posted_at, apify_cache.posted_at),
                        fetched_at = excluded.fetched_at
                """, (
                    video_id, data.get("views",0), data.get("likes",0),
                    data.get("comments",0), data.get("shares",0),
                    data.get("author_username", ""), data.get("posted_at"),
                    datetime.now().isoformat()
                ))
                await db.commit()
        except Exception as e:
            print(f"[Twitter] Cache save error: {e}")

    @staticmethod
    def _extract_video_id(url: str) -> str:
        match = re.search(r'(?:x|twitter)\.com/\w+/status/(\d+)', url)
        return match.group(1) if match else ""

    async def get_profile_bio(self, username: str) -> Optional[str]:
        """Fetch a Twitter/X user's bio using Apify."""
        if not self.token:
            return None
            
        url = f"{self.BASE_URL}/acts/{self.actor_id}/run-sync-get-dataset-items?token={self.token}"
        clean_user = username.strip().lstrip('@')
        target_url = f"https://x.com/{clean_user}"
        
        payload = {
            "startUrls": [{"url": target_url}],
            "maxItems": 1
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            timeout = aiohttp.ClientTimeout(total=45)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status not in (200, 201):
                        return None
                        
                    text = await resp.text()
                    data = json.loads(text)
                    
                    if isinstance(data, list) and len(data) > 0:
                        item = data[0]
                    elif isinstance(data, dict):
                        items = data.get("items", data.get("data", []))
                        if isinstance(items, list) and len(items) > 0:
                            item = items[0]
                        else:
                            item = data
                    else:
                        return None
                        
                    # apidojo tweet-scraper profile format
                    bio = item.get("author", {}).get("description") or \
                          item.get("user", {}).get("description") or \
                          item.get("description") or ""
                          
                    return str(bio)
                    
        except Exception as e:
            print(f"[Twitter] Error fetching profile bio for {username}: {e}")
            return None
