import re
from typing import Optional

# Platform detection patterns for video URLs
PLATFORM_PATTERNS = {
    "instagram": [
        re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/(?:reel|p)/[\w-]+', re.IGNORECASE),
    ],
    "tiktok": [
        re.compile(r'(?:https?://)?(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+', re.IGNORECASE),
        re.compile(r'(?:https?://)?(?:vm\.)?tiktok\.com/[\w]+', re.IGNORECASE),
    ],
    "twitter": [
        re.compile(r'(?:https?://)?(?:www\.)?(?:x|twitter)\.com/\w+/status/\d+', re.IGNORECASE),
    ],
    "youtube": [
        re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+', re.IGNORECASE),
        re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+', re.IGNORECASE),
        re.compile(r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+', re.IGNORECASE),
    ]
}

def detect_platform(url: str) -> Optional[str]:
    """Detect the social media platform from a URL.
    
    Returns: 'instagram', 'tiktok', 'twitter', 'youtube', or None if unrecognized.
    """
    url = url.strip()
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(url):
                return platform
    return None

def is_valid_video_url(url: str) -> bool:
    """Check if a URL is a valid social media video/post URL."""
    return detect_platform(url) is not None

def extract_video_id(url: str, platform: str) -> str:
    """Extract the video/post ID from a URL."""
    url = url.strip().rstrip('/')
    
    if platform == "instagram":
        match = re.search(r'instagram\.com/(?:reel|p)/([\w-]+)', url)
        return match.group(1) if match else ""
    elif platform == "tiktok":
        match = re.search(r'tiktok\.com/@[\w.-]+/video/(\d+)', url)
        if match: return match.group(1)
        # vm.tiktok.com/ABCDEFG
        match = re.search(r'vm\.tiktok\.com/([\w]+)', url)
        return match.group(1) if match else ""
    elif platform == "twitter":
        match = re.search(r'(?:x|twitter)\.com/\w+/status/(\d+)', url)
        return match.group(1) if match else ""
    elif platform == "youtube":
        match = re.search(r'youtube\.com/watch\?v=([\w-]+)', url)
        if match: return match.group(1)
        match = re.search(r'youtube\.com/shorts/([\w-]+)', url)
        if match: return match.group(1)
        match = re.search(r'youtu\.be/([\w-]+)', url)
        return match.group(1) if match else ""
    return ""

def normalize_url(url: str) -> str:
    """Normalize a URL by ensuring https:// prefix and cleaning platform-specific quirks."""
    url = url.strip()
    if not url.startswith('http'):
        url = 'https://' + url
    
    # Strip query parameters and trailing slashes for Instagram URLs
    # This prevents duplicates (same reel with different ?igsh= params)
    # and avoids Apify issues with tracking params
    if 'instagram.com/' in url:
        url = url.split('?')[0].rstrip('/')
    
    return url

def get_platform_emoji(platform: str) -> str:
    """Get the standard emoji for a platform."""
    return {
        "instagram": "📷",
        "tiktok": "🎵",
        "twitter": "🐦",
        "youtube": "▶️"
    }.get(platform.lower(), "🌐")

def get_platform_color(platform: str) -> int:
    """Get the standard Discord embed color for a platform."""
    return {
        "instagram": 0xE1306C, # Pink
        "tiktok": 0x00F2FE,    # Cyan
        "twitter": 0x1DA1F2,   # Blue
        "youtube": 0xFF0000    # Red
    }.get(platform.lower(), 0x5865F2) # Default Discord blurple
