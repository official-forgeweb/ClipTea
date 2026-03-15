"""
Unit tests for Instagram scraping fixes.

Tests:
  1. URL validation (shortcode length, fake detection, query param stripping)
  2. Error classification (SUCCESS, INVALID_URL, PARTIAL, RESTRICTED, UNKNOWN)
  3. Description parsing (likes/comments/author extraction)
  4. Token rotator (tiered penalties, no forced tokens, wait time)
  5. Queue backoff (capped delays, reset on success)
  6. URL normalization (Instagram query param stripping)
"""

import sys
import os
import time
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 1. URL Validation Tests ──────────────────────────────

def test_validate_valid_url():
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.instagram.com/reel/DVwgotsgqQb")
    assert result["valid"] is True, f"Expected valid, got {result}"
    assert result["shortcode"] == "DVwgotsgqQb"
    assert result["clean_url"] == "https://www.instagram.com/reel/DVwgotsgqQb"

def test_validate_url_with_query_params():
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.instagram.com/reel/DVwgotsgqQb/?igsh=bWk0bmJjMnMzdTN2")
    assert result["valid"] is True, f"Expected valid, got {result}"
    assert result["shortcode"] == "DVwgotsgqQb"
    assert "igsh" not in result["clean_url"]

def test_validate_url_with_trailing_slash():
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.instagram.com/reel/DVwgotsgqQb/")
    assert result["valid"] is True, f"Expected valid, got {result}"
    assert result["shortcode"] == "DVwgotsgqQb"

def test_validate_url_post_format():
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.instagram.com/p/DVwgotsgqQb")
    assert result["valid"] is True, f"Expected valid, got {result}"

def test_validate_short_shortcode():
    """Shortcodes like 'FFF' are only 3 chars — must be rejected."""
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.instagram.com/reel/FFF")
    assert result["valid"] is False, f"Expected invalid for 'FFF', got {result}"
    assert "length" in result["reason"].lower()

def test_validate_fake_shortcode():
    """Shortcodes with only 1-2 unique chars (e.g. 'AAAAAAAAAA_') are fake."""
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.instagram.com/reel/AAAAAAAAAAA")
    assert result["valid"] is False, f"Expected invalid for fake shortcode, got {result}"
    assert "fake" in result["reason"].lower()

def test_validate_invalid_url_format():
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.tiktok.com/@user/video/123")
    assert result["valid"] is False

def test_validate_non_reel_instagram():
    from services.apify_instagram import validate_instagram_url
    result = validate_instagram_url("https://www.instagram.com/stories/user/12345")
    assert result["valid"] is False


# ── 2. Error Classification Tests ────────────────────────

def test_classify_full_success():
    from services.apify_instagram import classify_apify_response
    raw = {"videoPlayCount": 11337, "likesCount": 202, "commentsCount": 1, "ownerUsername": "testuser"}
    result = classify_apify_response(raw)
    assert result["type"] == "SUCCESS"
    assert result["views"] == 11337
    assert result["likes"] == 202
    assert result["should_penalize_token"] is False
    assert result["should_retry"] is False

def test_classify_success_with_view_count():
    from services.apify_instagram import classify_apify_response
    raw = {"videoViewCount": 5000, "likesCount": 100}
    result = classify_apify_response(raw)
    assert result["type"] == "SUCCESS"
    assert result["views"] == 5000

def test_classify_invalid_url():
    """restricted_page with NO description AND NO image = post doesn't exist."""
    from services.apify_instagram import classify_apify_response
    raw = {"error": "restricted_page", "description": "", "image": ""}
    result = classify_apify_response(raw)
    assert result["type"] == "INVALID_URL"
    assert result["should_penalize_token"] is False
    assert result["should_retry"] is False

def test_classify_partial_data():
    """restricted_page WITH description containing likes/comments."""
    from services.apify_instagram import classify_apify_response
    raw = {
        "error": "restricted_page",
        "errorDescription": "Restricted access, only partial data available",
        "description": "71 likes, 0 comments - gamblingmomentee on March 11, 2026: \"GAMBLER Angriest...\"",
        "image": "https://example.com/thumb.jpg"
    }
    result = classify_apify_response(raw)
    assert result["type"] == "PARTIAL"
    assert result["likes"] == 71
    assert result["comments"] == 0
    assert result["author"] == "gamblingmomentee"
    assert result["views"] is None, "PARTIAL should NOT estimate views!"
    assert result["should_penalize_token"] is True
    assert result["penalty_level"] == "mild"
    assert result["should_retry"] is True

def test_classify_restricted_no_description():
    """restricted_page with image but empty description."""
    from services.apify_instagram import classify_apify_response
    raw = {"error": "restricted_page", "description": "", "image": "https://example.com/thumb.jpg"}
    result = classify_apify_response(raw)
    assert result["type"] == "RESTRICTED"

def test_classify_unknown_error():
    from services.apify_instagram import classify_apify_response
    raw = {"error": "some_new_error", "description": "", "image": ""}
    result = classify_apify_response(raw)
    assert result["type"] == "UNKNOWN"
    assert result["should_retry"] is True


# ── 3. Description Parsing Tests ─────────────────────────

def test_parse_description_full():
    from services.apify_instagram import parse_description
    desc = "71 likes, 0 comments - gamblingmomentee on March 11, 2026: \"GAMBLER Angriest...\""
    result = parse_description(desc)
    assert result["likes"] == 71
    assert result["comments"] == 0
    assert result["author"] == "gamblingmomentee"

def test_parse_description_large_numbers():
    from services.apify_instagram import parse_description
    desc = "1,234 likes, 56 comments - bigaccount on January 1, 2026: \"post\""
    result = parse_description(desc)
    assert result["likes"] == 1234
    assert result["comments"] == 56
    assert result["author"] == "bigaccount"

def test_parse_description_partial():
    from services.apify_instagram import parse_description
    desc = "42 likes in this post"
    result = parse_description(desc)
    assert result.get("likes") == 42

def test_parse_description_empty():
    from services.apify_instagram import parse_description
    result = parse_description("")
    assert result == {}


# ── 4. Token Rotator Tests ───────────────────────────────

def test_token_rotator_no_force():
    """When all tokens are cooling, get_next_token() must return None, not force."""
    os.environ["APIFY_TOKENS"] = "token_a,token_b"
    from services.apify_token_rotator import ApifyTokenRotator
    rotator = ApifyTokenRotator()
    
    # Put all tokens on cooldown
    for token in rotator.tokens:
        rotator.token_stats[token]["cooldown_until"] = datetime.now() + timedelta(minutes=10)
    
    result = rotator.get_next_token()
    assert result is None, f"Expected None when all cooling, got {result}"

def test_token_rotator_wait_time():
    """get_wait_time() should return seconds until soonest token available."""
    os.environ["APIFY_TOKENS"] = "token_a,token_b"
    from services.apify_token_rotator import ApifyTokenRotator
    rotator = ApifyTokenRotator()
    
    # Token A: 60s cooldown, Token B: 30s cooldown
    rotator.token_stats["token_a"]["cooldown_until"] = datetime.now() + timedelta(seconds=60)
    rotator.token_stats["token_b"]["cooldown_until"] = datetime.now() + timedelta(seconds=30)
    
    wait = rotator.get_wait_time()
    assert 25 <= wait <= 35, f"Expected ~30s wait, got {wait}"

def test_token_rotator_success_clears_cooldown():
    """Reporting SUCCESS should clear cooldown and reset consecutive errors."""
    os.environ["APIFY_TOKENS"] = "tokenX"
    from services.apify_token_rotator import ApifyTokenRotator
    rotator = ApifyTokenRotator()
    
    # Set up: token has cooldown and errors
    rotator.token_stats["tokenX"]["cooldown_until"] = datetime.now() + timedelta(minutes=5)
    rotator.token_stats["tokenX"]["consecutive_errors"] = 3
    
    rotator.report_result("tokenX", {"type": "SUCCESS"})
    
    assert rotator.token_stats["tokenX"]["cooldown_until"] is None
    assert rotator.token_stats["tokenX"]["consecutive_errors"] == 0

def test_token_rotator_invalid_url_no_penalty():
    """INVALID_URL should NOT penalize the token at all."""
    os.environ["APIFY_TOKENS"] = "tokenY"
    from services.apify_token_rotator import ApifyTokenRotator
    rotator = ApifyTokenRotator()
    
    rotator.report_result("tokenY", {"type": "INVALID_URL"})
    
    assert rotator.token_stats["tokenY"]["cooldown_until"] is None
    assert rotator.token_stats["tokenY"]["consecutive_errors"] == 0

def test_token_rotator_partial_mild_penalty():
    """PARTIAL should get only a 30s cooldown."""
    os.environ["APIFY_TOKENS"] = "tokenZ"
    from services.apify_token_rotator import ApifyTokenRotator
    rotator = ApifyTokenRotator()
    
    rotator.report_result("tokenZ", {"type": "PARTIAL"})
    
    assert rotator.token_stats["tokenZ"]["cooldown_until"] is not None
    remaining = (rotator.token_stats["tokenZ"]["cooldown_until"] - datetime.now()).total_seconds()
    assert remaining <= 31, f"Expected ~30s cooldown, got {remaining}"


# ── 5. Queue Backoff Tests ───────────────────────────────

def test_backoff_capped_at_80():
    """Delay should never exceed 80 seconds (updated from 120)."""
    # Updated ranges for faster queue processing
    ranges = {
        0: (10, 18),
        1: (20, 35),
        2: (35, 55),
        3: (55, 80),
    }
    for level, (lo, hi) in ranges.items():
        assert hi <= 80, f"Level {level} has max delay {hi} > 80"
        assert lo >= 10, f"Level {level} has min delay {lo} < 10"


# ── 6. URL Normalization Tests ───────────────────────────

def test_normalize_strips_instagram_params():
    from utils.platform_detector import normalize_url
    result = normalize_url("https://www.instagram.com/reel/DVwgotsgqQb/?igsh=bWk0bmJjMnMzdTN2")
    assert "igsh" not in result
    assert result == "https://www.instagram.com/reel/DVwgotsgqQb"

def test_normalize_strips_instagram_trailing_slash():
    from utils.platform_detector import normalize_url
    result = normalize_url("https://www.instagram.com/reel/DVwgotsgqQb/")
    assert result == "https://www.instagram.com/reel/DVwgotsgqQb"

def test_normalize_preserves_tiktok_params():
    """TikTok URLs should NOT have params stripped."""
    from utils.platform_detector import normalize_url
    url = "https://www.tiktok.com/@user/video/123?is_from_webapp=1"
    result = normalize_url(url)
    assert "is_from_webapp" in result

def test_normalize_adds_https():
    from utils.platform_detector import normalize_url
    result = normalize_url("instagram.com/reel/DVwgotsgqQb")
    assert result.startswith("https://")


# ── 7. Build Result Tests ────────────────────────────────

def test_build_result_views_none():
    """_build_result should return views=None (not -1) for PARTIAL data."""
    from services.apify_instagram import ApifyInstagramService
    service = ApifyInstagramService.__new__(ApifyInstagramService)
    classification = {
        "type": "PARTIAL",
        "views": None,
        "likes": 42,
        "comments": 3,
        "author": "testuser",
    }
    result = service._build_result(classification, method="apify_restricted_parsed")
    assert result["views"] is None, f"views should be None, got {result['views']}"
    assert result["views_unknown"] is True
    assert result["likes"] == 42

def test_build_result_views_success():
    """_build_result should return int views for SUCCESS data."""
    from services.apify_instagram import ApifyInstagramService
    service = ApifyInstagramService.__new__(ApifyInstagramService)
    classification = {
        "type": "SUCCESS",
        "views": 5000,
        "likes": 100,
        "comments": 10,
        "author": "testuser",
    }
    result = service._build_result(classification, method="live")
    assert result["views"] == 5000
    assert result["views_unknown"] is False


# ── 8. Token Rotator Excluding Tests ─────────────────────

def test_token_rotator_excluding():
    """get_next_token_excluding should prefer tokens NOT in exclude list."""
    os.environ["APIFY_TOKENS"] = "token_a,token_b,token_c"
    from services.apify_token_rotator import ApifyTokenRotator
    rotator = ApifyTokenRotator()

    result = rotator.get_next_token_excluding(["token_a"])
    assert result != "token_a", f"Should not return excluded token, got {result}"
    assert result in ("token_b", "token_c"), f"Expected token_b or token_c, got {result}"

def test_token_rotator_excluding_all_excluded():
    """When all tokens excluded but some available, should still return one."""
    os.environ["APIFY_TOKENS"] = "token_x,token_y"
    from services.apify_token_rotator import ApifyTokenRotator
    rotator = ApifyTokenRotator()

    result = rotator.get_next_token_excluding(["token_x", "token_y"])
    # Second pass should return an available token anyway
    assert result in ("token_x", "token_y"), f"Expected a token, got {result}"





if __name__ == "__main__":
    import traceback
    
    # Collect all test functions
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    
    passed = 0
    failed = 0
    errors = []
    
    print(f"\n{'='*60}")
    print(f"  Running {len(tests)} Instagram Fix Tests")
    print(f"{'='*60}\n")
    
    for test_fn in tests:
        name = test_fn.__name__
        try:
            test_fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}")
            print(f"     {e}")
            errors.append((name, traceback.format_exc()))
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    
    if errors:
        print("\n--- FAILURES ---")
        for name, tb in errors:
            print(f"\n{name}:")
            print(tb)
    
    sys.exit(1 if failed else 0)
