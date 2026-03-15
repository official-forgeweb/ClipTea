import aiohttp
import asyncio
import json
import re
import os
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional


from config import DATABASE_PATH

# ── URL Validation ─────────────────────────────────────

def validate_instagram_url(url: str) -> dict:
    """Validate and normalize an Instagram reel/post URL before queueing.
    
    Returns:
        {"valid": True, "clean_url": "https://...", "shortcode": "..."}
        or
        {"valid": False, "reason": "..."}
    """
    # Strip query params and trailing slashes
    clean = url.split('?')[0].rstrip('/')
    
    # Match valid reel or post URL
    pattern = r'^https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)/?$'
    match = re.match(pattern, clean)
    
    if not match:
        return {"valid": False, "reason": "Not a valid Instagram reel/post URL"}
    
    shortcode = match.group(1)
    
    # Real Instagram shortcodes are exactly 11 characters
    if len(shortcode) != 11:
        return {
            "valid": False,
            "reason": f"Invalid shortcode length: {len(shortcode)} (expected 11)"
        }
    
    # Reject obviously fake shortcodes (all same char, or only 1-2 unique chars)
    if len(set(shortcode)) <= 2:
        return {"valid": False, "reason": "Shortcode looks fake"}
    
    normalized = f"https://www.instagram.com/reel/{shortcode}"
    
    return {
        "valid": True,
        "clean_url": normalized,
        "shortcode": shortcode,
    }


# ── Error Classification ──────────────────────────────

def classify_apify_response(raw_data: dict, input_url: str = "") -> dict:
    """Classify an Apify response into a specific error type.
    
    Returns dict with:
        type: SUCCESS | INVALID_URL | PARTIAL | RESTRICTED | UNKNOWN
        should_penalize_token: bool
        should_retry: bool
        + extracted data fields when available
    """
    # FULL SUCCESS — has actual view count data
    view_count = raw_data.get("videoPlayCount") or raw_data.get("videoViewCount")
    if view_count is not None:
        return {
            "type": "SUCCESS",
            "views": int(view_count),
            "likes": int(raw_data.get("likesCount", 0) or 0),
            "comments": int(raw_data.get("commentsCount", 0) or 0),
            "shares": int(raw_data.get("sharesCount", 0) or 0),
            "author": raw_data.get("ownerUsername", ""),
            "caption": _safe_caption(raw_data),
            "posted_at": raw_data.get("timestamp") or raw_data.get("created_at"),
            "should_penalize_token": False,
            "should_retry": False,
        }
    
    description = str(raw_data.get("description", "") or "")
    image = str(raw_data.get("image", "") or "")
    error = str(raw_data.get("error", "") or "")
    
    # INVALID URL — restricted error with NO description AND NO image
    # This means the post does not exist on Instagram
    if error == "restricted_page" and not description.strip() and not image.strip():
        return {
            "type": "INVALID_URL",
            "should_penalize_token": False,
            "should_retry": False,
            "reason": "Post does not exist or was deleted",
        }
    
    # PARTIAL DATA — restricted but description contains likes/comments
    if error == "restricted_page" and description.strip():
        parsed = parse_description(description)
        
        # Also try to get author from title
        author = parsed.get("author", "")
        if not author:
            title = str(raw_data.get("title", "") or "")
            title_match = re.search(r'\(@(\w+)\)', title)
            if title_match:
                author = title_match.group(1)
        if not author:
            author = (raw_data.get("ownerUsername") or
                      raw_data.get("owner_username") or
                      raw_data.get("username") or "")
        
        return {
            "type": "PARTIAL",
            "likes": parsed.get("likes", 0),
            "comments": parsed.get("comments", 0),
            "author": author,
            "views": None,  # DO NOT ESTIMATE. Views unknown.
            "should_penalize_token": True,
            "penalty_level": "mild",
            "should_retry": True,
        }
    
    # RESTRICTED — has image but no useful data
    if error == "restricted_page":
        return {
            "type": "RESTRICTED",
            "should_penalize_token": True,
            "penalty_level": "medium",
            "should_retry": True,
        }
    
    # UNKNOWN ERROR
    return {
        "type": "UNKNOWN",
        "should_penalize_token": True,
        "penalty_level": "medium",
        "should_retry": True,
        "raw_error": str(raw_data)[:500],
    }


def parse_description(description: str) -> dict:
    """Extract likes, comments, author from Apify restricted description.
    
    Pattern: "71 likes, 0 comments - gamblingmomentee on March 11, 2026: ..."
    """
    # Full pattern with all three fields
    match = re.match(
        r'([\d,]+)\s+likes?,\s*([\d,]+)\s+comments?\s*-\s*(\w+)\s+on\s+',
        description
    )
    if match:
        return {
            "likes": int(match.group(1).replace(',', '')),
            "comments": int(match.group(2).replace(',', '')),
            "author": match.group(3),
        }
    
    # Try individual fields
    result = {}
    likes_match = re.search(r'([\d,]+)\s+likes?', description, re.IGNORECASE)
    if likes_match:
        result["likes"] = int(likes_match.group(1).replace(',', ''))
    
    comments_match = re.search(r'([\d,]+)\s+comments?', description, re.IGNORECASE)
    if comments_match:
        result["comments"] = int(comments_match.group(1).replace(',', ''))
    
    author_match = re.search(r'-\s*(\w+)\s+on\s+', description)
    if author_match:
        result["author"] = author_match.group(1)
    
    return result


def _safe_caption(item: dict) -> str:
    """Safely extract caption text from an Apify item."""
    caption = item.get("caption", "")
    if isinstance(caption, dict):
        caption = caption.get("text", "")
    if caption is None:
        caption = ""
    return str(caption)[:200]


class ApifyInstagramService:
    """Fetch Instagram video metrics using Apify's Instagram Post Scraper."""
    
    # CORRECT URL FORMAT — note the TILDE (~) not slash
    BASE_URL = "https://api.apify.com/v2"
    
    def __init__(self, db_path=None):
        try:
            import config
            self.token = config.PRIMARY_APIFY_TOKEN
        except ImportError:
            self.token = os.getenv("APIFY_TOKEN", "")

        actor_id_raw = os.getenv("APIFY_ACTOR_ID", "apify/instagram-post-scraper")
        self.actor_id = actor_id_raw.replace("/", "~")
        self.cache_duration_minutes = 120
        
        # Token rotation for multiple Apify accounts
        from services.apify_token_rotator import ApifyTokenRotator
        self.token_rotator = ApifyTokenRotator()
        
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
        
        1. Validate URL
        2. Check cache first (free, instant)
        3. If not cached or expired, call Apify API
        4. If Apify fails, fall back (no estimation of views)
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
        
        # Step 2: Call Apify API (with fallback actor)
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
        
        # Step 3: Fallback — try embed endpoint for likes (NO view estimation)
        return await self._estimation_fallback(video_url, shortcode)
    
    async def _call_apify(self, video_url: str, shortcode: str) -> Optional[dict]:
        """
        Call multiple scraping methods in sequence (5-method waterfall).
        Returns as soon as one method gets full data (with views).
        Falls back to best partial data if no method gets views.
        """
        # Strip query params from the URL before sending to Apify
        clean_url = video_url.split('?')[0].rstrip('/')

        # Track best partial result across all methods
        best_partial_classification = None
        used_tokens = []  # Track tokens used so far

        # ═══ METHOD 1: Primary actor (instagram-post-scraper) ═══
        token = self.token_rotator.get_next_token()
        if not token:
            token = self.token
        if not token:
            return {"error": "No Apify tokens available (all on cooldown or none configured)"}
        used_tokens.append(token)

        print(f"[SCRAPER] 🔄 Method 1: Primary actor ({self.actor_id})")
        result = await self._call_apify_actor(
            actor_id=self.actor_id,
            payload={"username": [clean_url], "resultsLimit": 1},
            token=token,
            shortcode=shortcode,
        )

        if result is not None:
            classification = classify_apify_response(result, video_url)

            if classification["type"] == "SUCCESS":
                self.token_rotator.report_result(token, classification)
                print(f"[SCRAPER] ✅ Method 1 success: views={classification['views']}")
                return self._build_result(classification, method="live")

            self.token_rotator.report_result(token, classification)

            # INVALID_URL — won't work on any actor, return immediately
            if classification["type"] == "INVALID_URL":
                return {
                    "views": 0, "likes": 0, "comments": 0,
                    "author_username": "", "method": "invalid_url",
                    "estimated": False, "cached": False,
                    "error": classification.get("reason", "Post does not exist"),
                }

            # Track partial data
            if classification["type"] == "PARTIAL":
                best_partial_classification = classification
                print(f"[SCRAPER] ⚠️ Method 1 partial: likes={classification.get('likes')}")

        await asyncio.sleep(2)

        # ═══ METHOD 2: Fallback actor (instagram-scraper) ═══
        fallback_actor = "apify~instagram-scraper"
        if fallback_actor != self.actor_id:
            token2 = self.token_rotator.get_next_token_excluding(used_tokens) or token
            used_tokens.append(token2)

            print(f"[SCRAPER] 🔄 Method 2: Fallback actor ({fallback_actor})")
            fallback_result = await self._call_apify_actor(
                actor_id=fallback_actor,
                payload={
                    "directUrls": [clean_url],
                    "resultsLimit": 1,
                    "resultsType": "posts",
                },
                token=token2,
                shortcode=shortcode,
            )

            if fallback_result is not None:
                fb_classification = classify_apify_response(fallback_result, video_url)
                self.token_rotator.report_result(token2, fb_classification)

                if fb_classification["type"] == "SUCCESS":
                    print(f"[SCRAPER] ✅ Method 2 success: views={fb_classification['views']}")
                    return self._build_result(fb_classification, method="live")

                if fb_classification["type"] == "PARTIAL" and not best_partial_classification:
                    best_partial_classification = fb_classification
                    print(f"[SCRAPER] ⚠️ Method 2 partial: likes={fb_classification.get('likes')}")

        await asyncio.sleep(2)

        # ═══ METHOD 3: Primary actor WITH RESIDENTIAL PROXY ═══
        token3 = self.token_rotator.get_next_token_excluding(used_tokens) or token
        used_tokens.append(token3)

        print(f"[SCRAPER] 🔄 Method 3: Primary actor + RESIDENTIAL proxy")
        residential_result = await self._call_apify_actor(
            actor_id=self.actor_id,
            payload={
                "username": [clean_url],
                "resultsLimit": 1,
                "proxy": {
                    "useApifyProxy": True,
                    "apifyProxyGroups": ["RESIDENTIAL"],
                },
            },
            token=token3,
            shortcode=shortcode,
            timeout_seconds=120,
        )

        if residential_result is not None:
            res_classification = classify_apify_response(residential_result, video_url)
            self.token_rotator.report_result(token3, res_classification)

            if res_classification["type"] == "SUCCESS":
                print(f"[SCRAPER] ✅ Method 3 success: views={res_classification['views']}")
                return self._build_result(res_classification, method="live_residential")

            if res_classification["type"] == "PARTIAL" and not best_partial_classification:
                best_partial_classification = res_classification

        await asyncio.sleep(2)

        # ═══ METHOD 4: RapidAPI Instagram Scraper ═══
        print(f"[SCRAPER] 🔄 Method 4: RapidAPI")
        rapidapi_result = await self._method_rapidapi(clean_url, shortcode)
        if rapidapi_result is not None:
            print(f"[SCRAPER] ✅ Method 4 success: views={rapidapi_result.get('views')}")
            return rapidapi_result

        await asyncio.sleep(2)

        # ═══ METHOD 5: Community Apify actor ═══
        community_actor = "reGrowth~instagram-scraper"
        token5 = self.token_rotator.get_next_token_excluding(used_tokens) or token
        used_tokens.append(token5)

        print(f"[SCRAPER] 🔄 Method 5: Community actor ({community_actor})")
        try:
            community_result = await self._call_apify_actor(
                actor_id=community_actor,
                payload={"urls": [clean_url], "resultsLimit": 1},
                token=token5,
                shortcode=shortcode,
            )

            if community_result is not None:
                comm_classification = classify_apify_response(community_result, video_url)
                self.token_rotator.report_result(token5, comm_classification)

                if comm_classification["type"] == "SUCCESS":
                    print(f"[SCRAPER] ✅ Method 5 success: views={comm_classification['views']}")
                    return self._build_result(comm_classification, method="live_community")

                if comm_classification["type"] == "PARTIAL" and not best_partial_classification:
                    best_partial_classification = comm_classification
        except Exception as e:
            print(f"[SCRAPER] Method 5 failed: {e}")

        # ═══ ALL METHODS FAILED ═══
        # Return best partial data if we have any
        if best_partial_classification:
            print(f"[SCRAPER] 📊 All 5 methods failed for full data. "
                  f"Best partial: likes={best_partial_classification.get('likes')}")
            return self._build_result(best_partial_classification, method="apify_restricted_parsed")

        print(f"[SCRAPER] ❌ All 5 methods failed for {clean_url}")
        return {"error": "restricted_page", "restricted": True,
                "views": 0, "likes": 0, "comments": 0,
                "author_username": "", "method": "apify_failed",
                "estimated": False, "cached": False}

    async def _call_apify_actor(self, actor_id: str, payload: dict,
                                 token: str, shortcode: str,
                                 timeout_seconds: int = 120) -> Optional[dict]:
        """Call a specific Apify actor and return the first result item, or None."""
        url = (
            f"{self.BASE_URL}/acts/{actor_id}"
            f"/run-sync-get-dataset-items"
            f"?token={token}"
        )

        headers = {"Content-Type": "application/json"}

        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                print(f"[REEL] Calling: {self.BASE_URL}/acts/{actor_id}/run-sync-get-dataset-items")
                print(f"[REEL] Payload: {json.dumps(payload)}")

                async with session.post(url, json=payload, headers=headers) as resp:
                    response_text = await resp.text()

                    if resp.status not in (200, 201):
                        print(f"[Apify] API Error: {resp.status} - {response_text[:500]}")
                        if resp.status == 401:
                            self.token_rotator.report_invalid(token)
                        elif resp.status == 403 and "usage hard limit exceeded" in response_text.lower():
                            self.token_rotator.report_exhausted(token)
                        else:
                            self.token_rotator.report_error(token)
                        return None

                    # Parse response
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError:
                        print(f"[Apify] Invalid JSON response: {response_text[:500]}")
                        self.token_rotator.report_error(token)
                        return None

                    # Response is an array of items
                    if isinstance(data, list) and len(data) > 0:
                        item = data[0]
                    elif isinstance(data, dict):
                        items = data.get("items", data.get("data", []))
                        if isinstance(items, list) and len(items) > 0:
                            item = items[0]
                        else:
                            item = data
                    else:
                        print(f"[Apify] Unexpected response format: {response_text[:500]}")
                        self.token_rotator.report_error(token)
                        return None

                    # Log raw data for debugging
                    print(f"[REEL] RAW KEYS: {list(item.keys())}")
                    print(f"[REEL] RAW DATA: {json.dumps(item, indent=2, default=str)[:3000]}")

                    return item

        except asyncio.TimeoutError:
            print(f"[Apify] Request timed out ({timeout_seconds}s) for actor {actor_id}")
            self.token_rotator.report_error(token)
            return None
        except aiohttp.ClientError as e:
            print(f"[Apify] Connection error: {e}")
            self.token_rotator.report_error(token)
            return None
        except Exception as e:
            print(f"[Apify] Unexpected error: {e}")
            self.token_rotator.report_error(token)
            return None

    def _build_result(self, classification: dict, method: str = "live") -> dict:
        """Build a standardized result dict from a classification."""
        views = classification.get("views")
        likes = classification.get("likes", 0) or 0
        comments = classification.get("comments", 0) or 0
        shares = classification.get("shares", 0) or 0
        author = classification.get("author", "")

        # Views can be None (PARTIAL) or int (SUCCESS)
        has_real_views = views is not None
        # Store None (not -1) when views are unknown — cleaner for DB and display

        caption = classification.get("caption", "")

        return {
            "views": int(views) if views is not None else None,
            "likes": int(likes),
            "comments": int(comments),
            "shares": int(shares),
            "author_username": str(author),
            "caption": str(caption)[:200],
            "posted_at": classification.get("posted_at"),
            "method": method,
            "estimated": not has_real_views,
            "likes_real": True if likes > 0 else False,
            "comments_real": True if comments > 0 else False,
            "restricted": classification.get("type") in ("PARTIAL", "RESTRICTED"),
            "error": "restricted_page" if classification.get("type") == "RESTRICTED" else None,
            "cached": False,
            "views_unknown": not has_real_views,
        }

    async def _method_rapidapi(self, url: str, shortcode: str) -> Optional[dict]:
        """Method 4: RapidAPI Instagram scraper — completely different service."""
        api_key = os.getenv("RAPIDAPI_KEY")
        if not api_key:
            print("[SCRAPER] Method 4 skipped: no RAPIDAPI_KEY")
            return None

        api_url = "https://instagram-scraper-api2.p.rapidapi.com/v1/post_info"
        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": "instagram-scraper-api2.p.rapidapi.com",
        }
        query_params = {"code_or_id_or_url": shortcode}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url, headers=headers, params=query_params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        print(f"[SCRAPER] RapidAPI HTTP {resp.status}")
                        return None

                    data = await resp.json()
                    if not data or not data.get("data"):
                        return None

                    post = data["data"]
                    views = (
                        post.get("play_count")
                        or post.get("video_play_count")
                        or post.get("view_count")
                        or post.get("video_view_count")
                        or post.get("videoPlayCount")
                        or post.get("videoViewCount")
                    )

                    if views is not None:
                        return {
                            "views": int(views),
                            "likes": int(post.get("like_count", post.get("likesCount", 0)) or 0),
                            "comments": int(post.get("comment_count", post.get("commentsCount", 0)) or 0),
                            "shares": 0,
                            "author_username": post.get("user", {}).get("username", ""),
                            "method": "rapidapi",
                            "estimated": False,
                            "cached": False,
                            "views_unknown": False,
                        }

                    return None
        except Exception as e:
            print(f"[SCRAPER] RapidAPI error: {e}")
            return None

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
                    data.get("views", 0) or 0,
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
        """Fallback: try embed endpoint for likes. DO NOT estimate views."""
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
        
        # DO NOT estimate views. Return None/0 if no real views available.
        result = {
            "views": 0,
            "likes": likes,
            "comments": comments,
            "shares": 0,
            "author_username": author,
            "method": "embed_fallback",
            "estimated": True if likes > 0 else False,
            "views_unknown": True,
            "cached": False,
            "note": "⚠️ Could not fetch view count. Will retry automatically."
        }
        
        # Cache the partial data (with shorter duration)
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
        # Strip query params first
        clean = url.split('?')[0]
        patterns = [
            r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, clean)
            if match:
                return match.group(1)
        return ""
