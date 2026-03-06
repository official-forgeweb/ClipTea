import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Discord Bot Token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Database Path
DATABASE_PATH = "campaign_data.db"

# Server lock
ALLOWED_GUILD_IDS = [
    g.strip() for g in os.getenv("ALLOWED_GUILD_IDS", "").split(",") 
    if g.strip()
]

# Proxies
PROXY_FILE = "proxies.txt"
ROTATING_PROXY_URL = os.getenv("ROTATING_PROXY_URL", None)

# Twitter API (Optional)
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", None)

# Rate Limits (Random delay bounds per platform)
RATE_LIMIT = {
    "instagram.com": {"min_delay": 5, "max_delay": 12},
    "tiktok.com": {"min_delay": 3, "max_delay": 8},
    "x.com": {"min_delay": 2, "max_delay": 5},
}

# Scraping constraints
MAX_POSTS_PER_USER = 20
HEADLESS = True
PAGE_TIMEOUT = 30000
REQUESTS_PER_PROXY = 5

# Default scrape interval (can be overridden by bot_settings)
SCRAPE_INTERVAL_MINUTES = 60

# Instagram session storage directory (for cookie-based login)
IG_SESSION_DIR = os.path.join(os.path.dirname(__file__), "ig_user_data")

FREE_PROXY_SOURCES = [
    # Disabled free proxies to let Webshare proxies work exclusively without getting mixed with banned ones
]

PROXY_TEST_URL = "http://httpbin.org/ip"
PROXY_TEST_TIMEOUT = 5
PROXY_REFRESH_INTERVAL = 1800
