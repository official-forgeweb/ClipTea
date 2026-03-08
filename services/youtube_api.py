import aiohttp
import asyncio
import os
import re
from datetime import datetime
from typing import Optional

class YouTubeService:
    """Fetch YouTube video metrics using official Google API."""
    
    BASE_URL = "https://www.googleapis.com/youtube/v3/videos"
    
    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY", "")
        if not self.api_key:
            print("[YouTube] WARNING: YOUTUBE_API_KEY is not set in .env")

    async def get_video_metrics(self, video_url: str) -> dict:
        """Get metrics for a YouTube video using its URL."""
        if not self.api_key:
            return {
                "error": "YouTube API key is not configured. Please contact the bot administrator.",
                "method": "api"
            }
            
        video_id = self._extract_video_id(video_url)
        if not video_id:
            return {"error": "Could not extract YouTube video ID from URL"}

        # API parameters
        params = {
            "part": "statistics,snippet",
            "id": video_id,
            "key": self.api_key
        }

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        print(f"[YouTube] API Error: {resp.status} - {text}")
                        return {"error": f"YouTube API returned status {resp.status}"}
                        
                    data = await resp.json()
                    
                    if not data.get("items"):
                        return {"error": "Video not found or is private"}
                        
                    item = data["items"][0]
                    stats = item.get("statistics", {})
                    snippet = item.get("snippet", {})
                    
                    # Parse metrics
                    views = int(stats.get("viewCount", 0))
                    likes = int(stats.get("likeCount", 0))
                    comments = int(stats.get("commentCount", 0))
                    
                    author = snippet.get("channelTitle", "")
                    title = snippet.get("title", "")
                    description = snippet.get("description", "")
                    posted_at = snippet.get("publishedAt")
                    
                    print(f"[YouTube] Fetched {video_id}: {views} views, {likes} likes")
                    
                    return {
                        "views": views,
                        "likes": likes,
                        "comments": comments,
                        "shares": 0, # YouTube API doesn't provide share counts publicly via this endpoint
                        "author_username": author,
                        "title": title,
                        "caption": description[:200], # Store preview of description
                        "posted_at": posted_at,
                        "method": "live",
                        "estimated": False,
                        "cached": False
                    }
                    
        except asyncio.TimeoutError:
            print("[YouTube] Request timed out")
            return {"error": "YouTube API request timed out"}
        except aiohttp.ClientError as e:
            print(f"[YouTube] Connection error: {e}")
            return {"error": f"Connection error: {str(e)}"}
        except Exception as e:
            print(f"[YouTube] Unexpected error: {e}")
            return {"error": f"Unexpected error: {str(e)}"}

    @staticmethod
    def _extract_video_id(url: str) -> str:
        """Extract video ID from various YouTube URL formats."""
        # Standard watch URL
        match = re.search(r'youtube\.com/watch\?v=([\w-]+)', url)
        if match: return match.group(1)
        
        # Shorts URL
        match = re.search(r'youtube\.com/shorts/([\w-]+)', url)
        if match: return match.group(1)
        
        match = re.search(r'youtu\.be/([\w-]+)', url)
        if match: return match.group(1)
        
        return ""

    async def get_channel_description(self, channel_identifier: str) -> Optional[str]:
        """Fetch the public channel description (About section) for a channel handle or ID."""
        if not self.api_key:
            return None
            
        identifier = channel_identifier.strip().lstrip('@')
        
        # Decide if this is a UC... ID or a handle
        if identifier.startswith("UC") and len(identifier) == 24:
            params = {
                "part": "snippet",
                "id": identifier,
                "key": self.api_key
            }
        else:
            params = {
                "part": "snippet",
                "forHandle": f"@{identifier}",
                "key": self.api_key
            }
            
        url = "https://www.googleapis.com/youtube/v3/channels"
        
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        print(f"[YouTube] API Error on channel fetch: {resp.status}")
                        return None
                        
                    data = await resp.json()
                    
                    if not data.get("items"):
                        return None
                        
                    snippet = data["items"][0].get("snippet", {})
                    return snippet.get("description", "")
                    
        except Exception as e:
            print(f"[YouTube] Error fetching channel description for {identifier}: {e}")
            return None
