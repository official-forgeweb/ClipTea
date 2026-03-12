import aiohttp
import asyncio
import json
import re
import os
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional


from config import DATABASE_PATH

class ApifyInstagramService:
    """Fetch Instagram video metrics using Apify's Instagram Post Scraper."""
    
    # CORRECT URL FORMAT — note the TILDE (~) not slash
    BASE_URL = "https://api.apify.com/v2"
    
    def __init__(self, db_path=None):
        self.token = os.getenv("APIFY_TOKEN", "")
        actor_id_raw = os.getenv("APIFY_ACTOR_ID", "apify/instagram-post-scraper")
        self.actor_id = actor_id_raw.replace("/", "~")
        self.cache_duration_minutes = 120
        
        # Handle different types of db_path input
        if db_path is None:
            # No argument — use config default
            try:
                from config import DATABASE_PATH
                self.db_path = DATABASE_PATH
            except ImportError:
                self.db_path = "cliptea.db"
        elif isinstance(db_path, str):
            # String path — use directly
            self.db_path = db_path
        else:
            # It's probably a DatabaseManager object
            # Try to get the path from it
            if hasattr(db_path, 'db_path'):
                self.db_path = db_path.db_path
            elif hasattr(db_path, 'database_path'):
                self.db_path = db_path.database_path
            elif hasattr(db_path, 'path'):
                self.db_path = db_path.path
            elif hasattr(db_path, 'db_name'):
                self.db_path = db_path.db_name
            else:
                # Last resort — try to find the path attribute
                # Look for any string attribute that ends with .db
                found = False
                for attr_name in dir(db_path):
                    if attr_name.startswith('_'):
                        continue
                    try:
                        val = getattr(db_path, attr_name)
                        if isinstance(val, str) and val.endswith('.db'):
                            self.db_path = val
                            found = True
                            break
                    except:
                        continue
                if not found:
                    try:
                        from config import DATABASE_PATH
                        self.db_path = DATABASE_PATH
                    except ImportError:
                        self.db_path = "cliptea.db"
        
        # Make sure the directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        print(f"[REEL] Using database: {self.db_path}")
    
    async def init_tables(self):
        """Create cache and usage tables if they don't exist."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS apify_cache (
                        shortcode TEXT PRIMARY KEY,
                        views INTEGER DEFAULT 0,
                        likes INTEGER DEFAULT 0,
                        comments INTEGER DEFAULT 0,
                        shares INTEGER DEFAULT 0,
                        author_username TEXT DEFAULT '',
                        caption TEXT DEFAULT '',
                        posted_at TIMESTAMP DEFAULT NULL,
                        raw_response TEXT DEFAULT '',
                        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS api_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        service TEXT DEFAULT 'apify',
                        endpoint TEXT DEFAULT '',
                        shortcode TEXT DEFAULT '',
                        credits_used REAL DEFAULT 0.0,
                        success INTEGER DEFAULT 0,
                        error_message TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Always try adding missing columns (safe — fails silently if they already exist)
                for col_sql in [
                    "ALTER TABLE apify_cache ADD COLUMN shares INTEGER DEFAULT 0",
                    "ALTER TABLE apify_cache ADD COLUMN posted_at TIMESTAMP DEFAULT NULL",
                    "ALTER TABLE apify_cache ADD COLUMN caption TEXT DEFAULT ''",
                    "ALTER TABLE api_usage ADD COLUMN service TEXT DEFAULT 'apify'",
                    "ALTER TABLE api_usage ADD COLUMN error_message TEXT DEFAULT ''",
                ]:
                    try:
                        await db.execute(col_sql)
                    except Exception:
                        pass  # Column already exists
                
                await db.commit()
                print(f"[REEL] Database tables ready at {self.db_path}")
        except Exception as e:
            print(f"[REEL] Database init error: {e}")
    

    async def get_video_metrics(self, video_url: str, use_cache: bool = True) -> dict:
        """
        Main function: Get metrics for an Instagram video.
        
        1. Check cache first (free, instant)
        2. If not cached or expired, call Apify API
        3. If Apify fails, fall back to estimation
        """
        shortcode = self._extract_shortcode(video_url)
        if not shortcode:
            return {
                "views": 0, "likes": 0, "comments": 0,
                "author_username": "", "method": "invalid_url",
                "estimated": True, "cached": False,
                "error": "Could not extract shortcode from URL"
            }
        
        # Step 1: Check cache
        if use_cache:
            cached = await self._get_from_cache(shortcode)
            if cached:
                return cached
        
        # Step 2: Call Apify API
        if self.token:
            result = await self._call_apify(video_url, shortcode)
            if result and not result.get("error"):
                # Save to cache
                await self._save_to_cache(shortcode, result)
                # Log API usage
                await self._log_usage(shortcode, True)
                return result
            else:
                # Log failed API call
                error_msg = result.get("error", "Unknown error") if result else "No response"
                await self._log_usage(shortcode, False, error_msg)
        
        # Step 3: Fallback to estimation
        return await self._estimation_fallback(video_url, shortcode)
    
    async def _call_apify(self, video_url: str, shortcode: str) -> Optional[dict]:
        """
        Call Apify API to scrape Instagram post.
        Uses the run-sync-get-dataset-items endpoint.
        """
        # BUILD THE CORRECT URL
        # Actor ID must use TILDE: apify~instagram-post-scraper
        url = (
            f"{self.BASE_URL}/acts/{self.actor_id}"
            f"/run-sync-get-dataset-items"
            f"?token={self.token}"
        )
        
        # Request body — the input for the scraper
        # NOTE: apify/instagram-post-scraper requires "username" field
        # (it accepts URLs in this field despite the confusing name)
        payload = {
            "username": [video_url],
            "resultsLimit": 1
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=120)  # 120 second max
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                print(f"[REEL] Calling: {self.BASE_URL}/acts/{self.actor_id}/run-sync-get-dataset-items")
                print(f"[REEL] Payload: {json.dumps(payload)}")
                
                async with session.post(url, json=payload, headers=headers) as resp:
                    response_text = await resp.text()
                    
                    if resp.status != 200 and resp.status != 201:
                        print(f"[Apify] API Error: {resp.status} - {response_text[:500]}")
                        return {"error": f"Apify returned status {resp.status}"}
                    
                    # Parse response
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError:
                        print(f"[Apify] Invalid JSON response: {response_text[:500]}")
                        return {"error": "Invalid response from Apify"}
                    
                    # Response is an array of items
                    if isinstance(data, list) and len(data) > 0:
                        item = data[0]
                    elif isinstance(data, dict):
                        # Sometimes response is wrapped in a dict
                        items = data.get("items", data.get("data", []))
                        if isinstance(items, list) and len(items) > 0:
                            item = items[0]
                        else:
                            item = data
                    else:
                        print(f"[Apify] Unexpected response format: {response_text[:500]}")
                        return {"error": "Unexpected response format"}
                    
                    # Extract metrics from item
                    print(f"[REEL] RAW KEYS: {list(item.keys())}")
                    print(f"[REEL] RAW DATA: {json.dumps(item, indent=2, default=str)[:3000]}")
                    return self._parse_apify_response(item)
        
        except asyncio.TimeoutError:
            print("[Apify] Request timed out (120 seconds)")
            return {"error": "Apify request timed out"}
        except aiohttp.ClientError as e:
            print(f"[Apify] Connection error: {e}")
            return {"error": f"Connection error: {str(e)}"}
        except Exception as e:
            print(f"[Apify] Unexpected error: {e}")
            return {"error": f"Unexpected error: {str(e)}"}
    
    def _parse_apify_response(self, item: dict) -> dict:
        """
        Parse Apify scraper response.
        Different scrapers use different field names.
        Check all possible variations.
        """
        # ── CHECK FOR RESTRICTED PAGE ERROR FIRST ──────────
        error_val = str(item.get("error", "")).lower()
        error_desc = str(item.get("errorDescription", "")).lower()

        if "restricted" in error_val or "restricted" in error_desc:
            # Extract whatever partial data is available
            author = (
                item.get("ownerUsername") or
                item.get("owner_username") or
                item.get("username") or ""
            )
            caption = item.get("caption", "")
            if isinstance(caption, dict):
                caption = caption.get("text", "")

            print(f"[Apify] ⚠️ RESTRICTED PAGE — partial data only, author={author}")

            return {
                "views": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "author_username": str(author),
                "caption": str(caption or "")[:200],
                "method": "apify_restricted",
                "estimated": True,
                "cached": False,
                "error": "restricted_page",
                "partial_data": True,
            }

        # Views — check all possible field names
        views = (
            item.get("videoPlayCount") or
            item.get("videoViewCount") or
            item.get("video_view_count") or
            item.get("video_play_count") or
            item.get("playCount") or
            item.get("viewCount") or
            item.get("views") or
            item.get("play_count") or
            item.get("view_count") or
            0
        )
        
        # Likes
        likes = (
            item.get("likesCount") or
            item.get("likes_count") or
            item.get("likeCount") or
            item.get("like_count") or
            item.get("likes") or
            0
        )
        
        # Comments
        comments = (
            item.get("commentsCount") or
            item.get("comments_count") or
            item.get("commentCount") or
            item.get("comment_count") or
            item.get("comments") or
            0
        )
        
        # Author username
        author = (
            item.get("ownerUsername") or
            item.get("owner_username") or
            item.get("username") or
            ""
        )
        
        # If author is in a nested object
        if not author:
            owner = item.get("owner", {})
            if isinstance(owner, dict):
                author = owner.get("username", "")
        
        # Caption
        caption = item.get("caption", "")
        if isinstance(caption, dict):
            caption = caption.get("text", "")
        if caption is None:
            caption = ""
        
        # Shares
        shares = (
            item.get("sharesCount") or
            item.get("shares_count") or
            item.get("shareCount") or
            item.get("share_count") or
            0
        )
        
        # Posted at timestamp
        posted_at = item.get("timestamp") or item.get("created_at") or None
        
        # --- Description Regex Fallback (Important for 'restricted_page' errors) ---
        description = item.get("description", "")
        if description and isinstance(description, str):
            import re
            
            def parse_number(s):
                s = s.lower().replace(',', '').strip()
                multiplier = 1
                if 'k' in s:
                    multiplier = 1000
                    s = s.replace('k', '')
                elif 'm' in s:
                    multiplier = 1000000
                    s = s.replace('m', '')
                try:
                    return int(float(s) * multiplier)
                except:
                    return 0

            # Extract metrics from descriptions like "20 likes, 0 comments - user on ..."
            if likes == 0:
                l_match = re.search(r'([\d,.]+k?m?)\s+likes', description, re.IGNORECASE)
                if l_match:
                    likes = parse_number(l_match.group(1))
            
            if comments == 0:
                c_match = re.search(r'([\d,.]+k?m?)\s+comments', description, re.IGNORECASE)
                if c_match:
                    comments = parse_number(c_match.group(1))

            if views == 0:
                # SEO descriptions rarely show views, but we check just in case
                v_match = re.search(r'([\d,.]+k?m?)\s+views', description, re.IGNORECASE)
                if v_match:
                    views = parse_number(v_match.group(1))
            
            if not author:
                # Part of description: "- elitepokermoments on March 11, 2026"
                a_match = re.search(r'-\s+([\w.]+)\s+on\s+', description)
                if a_match:
                    author = a_match.group(1)

        # Ensure all values are integers
        try:
            views = int(views) if views else 0
        except (ValueError, TypeError):
            views = 0
        try:
            likes = int(likes) if likes else 0
        except (ValueError, TypeError):
            likes = 0
        try:
            comments = int(comments) if comments else 0
        except (ValueError, TypeError):
            comments = 0
        try:
            shares = int(shares) if shares else 0
        except (ValueError, TypeError):
            shares = 0
        
        print(f"[REEL] Parsed: views={views}, likes={likes}, comments={comments}, author={author}")
        
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
            "cached": False,
        }
    
    async def _get_from_cache(self, shortcode: str) -> Optional[dict]:
        """Get cached metrics if not expired."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM apify_cache WHERE shortcode = ?",
                    (shortcode,)
                )
                row = await cursor.fetchone()
                
                if not row:
                    return None
                
                # Check if cache is expired
                fetched_at = datetime.fromisoformat(str(row["fetched_at"]))
                cache_age = datetime.now() - fetched_at
                
                if cache_age > timedelta(minutes=self.cache_duration_minutes):
                    return None  # Expired
                
                print(f"[REEL] Cache hit for {shortcode} (age: {cache_age})")
                
                return {
                    "views": row["views"],
                    "likes": row["likes"],
                    "comments": row["comments"],
                    "shares": row["shares"] if "shares" in row.keys() else 0,
                    "author_username": row["author_username"],
                    "posted_at": row.get("posted_at") if "posted_at" in row.keys() else None,
                    "method": "cache",
                    "estimated": False,
                    "cached": True,
                    "cache_age_minutes": int(cache_age.total_seconds() / 60),
                }
        except Exception as e:
            print(f"[Apify] Cache read error: {e}")
            return None
    
    async def _save_to_cache(self, shortcode: str, data: dict):
        """Save metrics to cache."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO apify_cache 
                    (shortcode, views, likes, comments, shares, author_username, posted_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(shortcode) DO UPDATE SET
                        views = excluded.views,
                        likes = excluded.likes,
                        comments = excluded.comments,
                        shares = excluded.shares,
                        author_username = excluded.author_username,
                        posted_at = COALESCE(excluded.posted_at, apify_cache.posted_at),
                        fetched_at = excluded.fetched_at
                """, (
                    shortcode,
                    data.get("views", 0),
                    data.get("likes", 0),
                    data.get("comments", 0),
                    data.get("shares", 0),
                    data.get("author_username", ""),
                    data.get("posted_at"),
                    datetime.now().isoformat(),
                ))
                await db.commit()
        except Exception as e:
            print(f"[Apify] Cache write error: {e}")
    
    async def _log_usage(self, shortcode: str, success: bool, error_msg: str = ""):
        """Log API usage for tracking."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO api_usage 
                    (service, endpoint, shortcode, credits_used, success, error_message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    "apify",
                    "run-sync-get-dataset-items",
                    shortcode,
                    0.01,  # Approximate cost per call
                    1 if success else 0,
                    error_msg,
                    datetime.now().isoformat(),
                ))
                await db.commit()
        except Exception as e:
            print(f"[Apify] Usage logging error: {e}")
    
    async def _estimation_fallback(self, video_url: str, shortcode: str) -> dict:
        """Fallback: try embed endpoint for likes, estimate views."""
        likes = 0
        comments = 0
        author = ""
        
        # Try embed endpoint (free, no auth needed, gives likes/comments)
        try:
            embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(embed_url) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        
                        # Extract likes
                        import re
                        like_match = re.search(r'"edge_media_preview_like"\s*:\s*\{\s*"count"\s*:\s*(\d+)', html)
                        if like_match:
                            likes = int(like_match.group(1))
                        else:
                            like_match = re.search(r'(\d[\d,]*)\s*likes?', html)
                            if like_match:
                                likes = int(like_match.group(1).replace(",", ""))
                        
                        # Extract comments
                        comment_match = re.search(r'"edge_media_preview_comment"\s*:\s*\{\s*"count"\s*:\s*(\d+)', html)
                        if comment_match:
                            comments = int(comment_match.group(1))
                        
                        # Extract author
                        author_match = re.search(r'"owner"\s*:\s*\{\s*"username"\s*:\s*"([^"]+)"', html)
                        if author_match:
                            author = author_match.group(1)
        except Exception as e:
            print(f"[Apify] Embed fallback error: {e}")
        
        # Estimate views from likes (likes ≈ 4% of views)
        estimated_views = int(likes / 0.04) if likes > 0 else 0
        
        result = {
            "views": estimated_views,
            "likes": likes,
            "comments": comments,
            "shares": 0,
            "author_username": author,
            "method": "estimation",
            "estimated": True,
            "cached": False,
            "note": "Link your Instagram with /link_account for accurate views"
        }
        
        # Cache the estimation too (with shorter duration)
        if likes > 0:
            await self._save_to_cache(shortcode, result)
        
        return result
    
    async def get_monthly_usage(self) -> dict:
        """Get API usage stats for current month."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Get current month's start
                now = datetime.now()
                month_start = now.replace(day=1, hour=0, minute=0, second=0).isoformat()
                
                # Total calls this month
                cursor = await db.execute(
                    "SELECT COUNT(*) as total, SUM(success) as successes FROM api_usage WHERE created_at >= ?",
                    (month_start,)
                )
                row = await cursor.fetchone()
                total_calls = row[0] if row else 0
                successful = row[1] if row and row[1] else 0
                
                # Cache stats
                cursor2 = await db.execute(
                    "SELECT COUNT(*) FROM apify_cache"
                )
                cached_items = (await cursor2.fetchone())[0]
                
                return {
                    "total_calls": total_calls,
                    "successful": successful,
                    "failed": total_calls - successful,
                    "estimated_cost": round(total_calls * 0.01, 2),
                    "cached_items": cached_items,
                    "month": now.strftime("%B %Y"),
                }
        except Exception as e:
            print(f"[Apify] Usage stats error: {e}")
            return {
                "total_calls": 0, "successful": 0, "failed": 0,
                "estimated_cost": 0, "cached_items": 0, "month": "",
                "error": str(e)
            }
    
    @staticmethod
    def _extract_shortcode(url: str) -> str:
        """Extract shortcode from Instagram URL."""
        patterns = [
            r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return ""
