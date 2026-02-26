import random
try:
    from fake_useragent import UserAgent
except ImportError:
    UserAgent = None

class FingerprintGenerator:
    """Generates random browser fingerprints."""
    def __init__(self):
        if UserAgent:
            try:
                self.ua = UserAgent(os='windows', browsers=['chrome', 'firefox', 'safari'])
            except Exception:
                self.ua = None
        else:
            self.ua = None
            
        self.viewports = [
            {"width": 1920, "height": 1080},
            {"width": 1366, "height": 768},
            {"width": 1440, "height": 900},
            {"width": 1536, "height": 864},
            {"width": 2560, "height": 1440},
            {"width": 1680, "height": 1050},
            {"width": 1280, "height": 720},
            {"width": 1280, "height": 800}
        ]
        
        self.timezones = [
            "America/New_York", "America/Chicago", "America/Los_Angeles", 
            "Europe/London", "Europe/Paris", "Europe/Berlin", 
            "Asia/Tokyo", "Australia/Sydney", "Asia/Dubai", "Asia/Singapore"
        ]
        
        self.locales = ["en-US", "en-GB", "en-CA", "en-AU"]
        self.scale_factors = [1, 1.25, 1.5, 2]
        self.color_depths = [24, 32]
        
        self.hardcoded_uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ]

    def get_fingerprint(self) -> dict:
        """Returns a random browser fingerprint profile."""
        if self.ua:
            try:
                user_agent = self.ua.random
            except Exception:
                user_agent = random.choice(self.hardcoded_uas)
        else:
            user_agent = random.choice(self.hardcoded_uas)
            
        return {
            "user_agent": user_agent,
            "viewport": random.choice(self.viewports),
            "timezone_id": random.choice(self.timezones),
            "locale": random.choice(self.locales),
            "device_scale_factor": random.choice(self.scale_factors),
            "color_depth": random.choice(self.color_depths)
        }
