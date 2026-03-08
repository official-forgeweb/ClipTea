"""URL validation and platform detection utilities."""
import re
from typing import Optional, Tuple
from .platform_detector import (
    PLATFORM_PATTERNS, detect_platform, is_valid_video_url, 
    extract_video_id, normalize_url
)


def validate_username(username: str) -> str:
    """Clean and validate a social media username."""
    username = username.strip().lstrip('@')
    # Remove any URL parts if someone pastes a full URL
    if '/' in username:
        username = username.split('/')[-1]
    return username
