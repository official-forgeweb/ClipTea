"""URL validation and platform detection utilities."""
import re
from typing import Optional, Tuple


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
}


def detect_platform(url: str) -> Optional[str]:
    """Detect the social media platform from a URL.
    
    Returns: 'instagram', 'tiktok', 'twitter', or None if unrecognized.
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
        # instagram.com/reel/ABC123/ or instagram.com/p/ABC123/
        match = re.search(r'instagram\.com/(?:reel|p)/([\w-]+)', url)
        return match.group(1) if match else ""
    
    elif platform == "tiktok":
        # tiktok.com/@user/video/1234567890
        match = re.search(r'tiktok\.com/@[\w.-]+/video/(\d+)', url)
        return match.group(1) if match else ""
    
    elif platform == "twitter":
        # x.com/user/status/1234567890
        match = re.search(r'(?:x|twitter)\.com/\w+/status/(\d+)', url)
        return match.group(1) if match else ""
    
    return ""


def normalize_url(url: str) -> str:
    """Normalize a URL by ensuring https:// prefix and removing trailing slash."""
    url = url.strip().rstrip('/')
    if not url.startswith('http'):
        url = 'https://' + url
    return url


def validate_username(username: str) -> str:
    """Clean and validate a social media username."""
    username = username.strip().lstrip('@')
    # Remove any URL parts if someone pastes a full URL
    if '/' in username:
        username = username.split('/')[-1]
    return username
