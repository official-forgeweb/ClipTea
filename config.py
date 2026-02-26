import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Discord Bot Token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Database Path
DATABASE_PATH = "campaign_data.db"

# Proxies
PROXY_FILE = "proxies.txt"
ROTATING_PROXY_URL = os.getenv("ROTATING_PROXY_URL", None)  # For future paid proxy usage

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
REQUESTS_PER_PROXY = 5  # Lower number of requests for free proxies before rotation

# Free proxy sources
FREE_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]

PROXY_TEST_URL = "http://httpbin.org/ip"
PROXY_TEST_TIMEOUT = 5
PROXY_REFRESH_INTERVAL = 1800  # Reload proxies every 30 minutes
