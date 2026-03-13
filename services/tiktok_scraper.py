import aiohttp
import asyncio
import json
import re
import os
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional

class TikTokApifyService:
    """Fetch TikTok video metrics using Apify."""
    
    BASE_URL = "https://api.apify.com/v2"
    
    def __init__(self, db_path=None):
        try:
            import config
            self.token = config.PRIMARY_APIFY_TOKEN
        except ImportError:
            self.token = os.getenv("APIFY_TOKEN", "")

        actor_id_raw = os.getenv("TIKTOK_ACTOR_ID", "clockworks/free-tiktok-scraper")
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
        """Get metrics for a TikTok video. Checks cache first."""
        video_id = self._extract_video_id(video_url)
        if not video_id:
            # Maybe it's a vm.tiktok.com link, which is a shortened ID. Treat the shortened part as the ID.
            match = re.search(r'vm\.tiktok\.com/([\w]+)', video_url)
            if match:
                video_id = match.group(1)
            else:
                return {"error": "Could not extract TikTok video ID"}

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
        
        # clockworks/free-tiktok-scraper likely takes an array of URLs.
        # Other actors might have different inputs. We send a few common input formats.
        payload = {
            "postURLs": [video_url],
            "urls": [video_url],
            "url": video_url,
            "resultsPerPage": 1,
            "maxItems": 1
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            timeout = aiohttp.ClientTimeout(total=120) # Extracted TikToks can be slow
            async with aiohttp.ClientSession(timeout=timeout) as session:
                print(f"[TikTok] Calling Apify for {video_url}")
                async with session.post(url, json=payload, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status not in (200, 201):
                        print(f"[TikTok] API Error: {resp.status} - {text[:200]}")
                        return {"error": f"Apify returned {resp.status}"}
                        
                    try:
                        data = json.loads(text)
                    except:
                        return {"error": "Invalid Apify JSON response"}
                        
                    # Locate the first item
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
            return {"error": "TikTok scrape timed out (120s)"}
        except Exception as e:
            return {"error": f"Error: {str(e)}"}

    def _parse_response(self, item: dict) -> dict:
        """Extract metrics from arbitrary TikTok actor JSON output."""
        # Views
        views = (item.get("playCount") or item.get("play_count") or 
                 item.get("viewCount") or item.get("videoViewCount") or 
                 item.get("views") or 0)
        
        # Likes
        likes = (item.get("diggCount") or item.get("likeCount") or 
                 item.get("likes_count") or item.get("likesCount") or 
                 item.get("likes") or 0)
                 
        # Comments
        comments = (item.get("commentCount") or item.get("commentsCount") or 
                    item.get("comments") or 0)
                    
        # Shares
        shares = (item.get("shareCount") or item.get("sharesCount") or 
                  item.get("shares") or 0)
                  
        # Author
        author = item.get("authorMeta", {}).get("name") or \
                 item.get("author", {}).get("uniqueId") or \
                 item.get("uniqueId") or \
                 item.get("authorMeta", {}).get("nickName") or ""
                 
        if not author:
            # Sometime it's under 'author' as string
            auth = item.get("author")
            if isinstance(auth, str):
                author = auth
                
        # To string and int conversions
        try: views = int(views)
        except: views = 0
        try: likes = int(likes)
        except: likes = 0
        try: comments = int(comments)
        except: comments = 0
        try: shares = int(shares)
        except: shares = 0
        
        caption = item.get("text") or item.get("desc") or ""
        posted_at = item.get("createTimeISO") or item.get("createTime") or None
        
        # If timestamp is integer (Unix), convert it to UTC ISO string
        if posted_at is not None:
            try:
                import datetime as dt_mod
                # Case 1: Already a number (Unix Epoch)
                if isinstance(posted_at, (int, float)) and posted_at > 0:
                    ts = float(posted_at)
                    posted_at = dt_mod.datetime.fromtimestamp(ts, tz=dt_mod.timezone.utc).isoformat()
                # Case 2: Stringified number
                elif isinstance(posted_at, str) and posted_at.replace('.','',1).isdigit():
                    ts = float(posted_at)
                    posted_at = dt_mod.datetime.fromtimestamp(ts, tz=dt_mod.timezone.utc).isoformat()
            except:
                pass

        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "author_username": author,
            "caption": str(caption)[:200],
            "posted_at": posted_at,
            "method": "live",
            "estimated": False,
            "cached": False
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
                # Assuming table exists (created by ApifyInstagramService)
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
            print(f"[TikTok] Cache save error: {e}")

    @staticmethod
    def _extract_video_id(url: str) -> str:
        match = re.search(r'tiktok\.com/@[\w.-]+/video/(\d+)', url)
        return match.group(1) if match else ""

    async def get_profile_bio(self, username: str) -> Optional[str]:
        """Fetch a TikTok user's bio using Apify."""
        if not self.token:
            return None
            
        url = f"{self.BASE_URL}/acts/{self.actor_id}/run-sync-get-dataset-items?token={self.token}"
        clean_user = username.strip().lstrip('@')
        target_url = f"https://www.tiktok.com/@{clean_user}"
        
        payload = {
            "postURLs": [target_url],
            "urls": [target_url],
            "url": target_url,
            "resultsPerPage": 1,
            "maxItems": 1
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            timeout = aiohttp.ClientTimeout(total=60)
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
                        
                    # Different actors return bio in different keys
                    bio = item.get("authorMeta", {}).get("signature") or \
                          item.get("author", {}).get("signature") or \
                          item.get("signature") or ""
                          
                    return str(bio)
                    
        except Exception as e:
            print(f"[TikTok] Error fetching profile bio for {username}: {e}")
            return None
