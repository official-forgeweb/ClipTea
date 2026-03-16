import aiohttp
import os
import re
import logging
import asyncio
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SOCIALDATA_API_KEY = os.getenv("SOCIALDATA_API_KEY")
SOCIALDATA_BASE = "https://api.socialdata.tools"


def extract_shortcode(url: str) -> str:
    """Extract Instagram shortcode from any reel/post URL."""
    clean = url.split('?')[0].rstrip('/')
    match = re.search(r'/(?:reel|p)/([A-Za-z0-9_-]+)', clean)
    return match.group(1) if match else None


async def socialdata_get_video(url: str) -> dict:
    """
    Fetch video details from SocialData.tools API.
    Returns: {success, views, likes, comments, timestamp, author}
    """
    if not SOCIALDATA_API_KEY:
        logger.error("[SocialData] ❌ No API key! Set SOCIALDATA_API_KEY in .env")
        return {"success": False, "error": "No API key"}
    
    shortcode = extract_shortcode(url)
    if not shortcode:
        logger.error(f"[SocialData] ❌ Invalid URL: {url}")
        return {"success": False, "error": "Invalid URL"}
    
    api_url = f"{SOCIALDATA_BASE}/instagram.com/post/{shortcode}"
    headers = {
        "Authorization": f"Bearer {SOCIALDATA_API_KEY}",
        "Accept": "application/json"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url, 
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                
                if resp.status == 200:
                    data = await resp.json()
                    
                    views = (
                        data.get("video_play_count") or 
                        data.get("video_view_count") or
                        data.get("play_count") or
                        data.get("view_count")
                    )
                    likes = data.get("like_count", data.get("likes_count", 0))
                    comments = data.get("comment_count", data.get("comments_count", 0))
                    timestamp = data.get("taken_at", data.get("timestamp", None))
                    
                    user = data.get("user", data.get("owner", {}))
                    author = ""
                    if isinstance(user, dict):
                        author = user.get("username", "")
                    elif isinstance(user, str):
                        author = user
                    
                    logger.info(
                        f"[SocialData] ✅ {shortcode}: "
                        f"views={views}, likes={likes}, comments={comments}"
                    )
                    
                    return {
                        "success": True,
                        "views": int(views) if views is not None else None,
                        "likes": int(likes) if likes else 0,
                        "comments": int(comments) if comments else 0,
                        "timestamp": timestamp,
                        "author": author,
                        "shortcode": shortcode
                    }
                
                elif resp.status == 404:
                    logger.warning(f"[SocialData] Post not found: {shortcode}")
                    return {"success": False, "error": "Post not found"}
                
                elif resp.status == 401:
                    logger.error("[SocialData] ❌ Invalid API key!")
                    return {"success": False, "error": "Invalid API key"}
                
                elif resp.status == 429:
                    logger.warning("[SocialData] ⚠️ Rate limited")
                    return {"success": False, "error": "Rate limited"}
                
                else:
                    error_text = await resp.text()
                    logger.warning(
                        f"[SocialData] HTTP {resp.status}: {error_text[:300]}"
                    )
                    return {"success": False, "error": f"HTTP {resp.status}"}
    
    except asyncio.TimeoutError:
        logger.warning(f"[SocialData] Timeout for {shortcode}")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        logger.error(f"[SocialData] Exception: {e}")
        return {"success": False, "error": str(e)}


async def socialdata_get_bio(username: str) -> dict:
    """
    Fetch account bio from SocialData.tools API.
    Returns: {success, bio, full_name, followers, following, profile_pic}
    """
    if not SOCIALDATA_API_KEY:
        return {"success": False, "error": "No API key"}
    
    # Remove @ if present
    username = username.lstrip('@')
    
    api_url = f"{SOCIALDATA_BASE}/instagram.com/user/{username}"
    headers = {
        "Authorization": f"Bearer {SOCIALDATA_API_KEY}",
        "Accept": "application/json"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "success": True,
                        "bio": data.get("biography", ""),
                        "full_name": data.get("full_name", ""),
                        "followers": data.get("followers_count", data.get("follower_count", 0)),
                        "following": data.get("following_count", data.get("followings_count", 0)),
                        "profile_pic": data.get("profile_pic_url", data.get("profile_pic_url_hd", ""))
                    }
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
