"""Campaign ID generator using camp_XXXXXXXX format."""
import random
import string


def generate_campaign_id() -> str:
    """Generate a unique campaign ID in format camp_XXXXXXXX (8 random alphanumeric chars)."""
    chars = string.ascii_lowercase + string.digits
    random_part = ''.join(random.choices(chars, k=8))
    return f"camp_{random_part}"
