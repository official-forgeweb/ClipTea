import asyncio
import time
import random
from typing import Dict
from config import RATE_LIMIT

class RateLimiter:
    """Manages request timing with random jitter and exponential backoff."""
    def __init__(self):
        self._domain_last_request: Dict[str, float] = {}
        self._domain_backoff: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        
    def _get_domain_config(self, domain: str) -> dict:
        for limit_domain, config in RATE_LIMIT.items():
            if limit_domain in domain:
                return config
        return {"min_delay": 2, "max_delay": 5}

    async def wait(self, domain: str):
        """Enforces a delay before the next request to a domain."""
        config = self._get_domain_config(domain)
        
        async with self._lock:
            now = time.time()
            last_request = self._domain_last_request.get(domain, 0)
            backoff = self._domain_backoff.get(domain, 0)
            
            base_delay = random.uniform(config["min_delay"], config["max_delay"])
            total_delay = base_delay + backoff
            
            time_since_last = now - last_request
            if time_since_last < total_delay:
                wait_time = total_delay - time_since_last
                await asyncio.sleep(wait_time)
                
            self._domain_last_request[domain] = time.time()
            
    async def report_error(self, domain: str):
        """Increases backoff for a domain (exponential to max 60s)."""
        async with self._lock:
            current_backoff = self._domain_backoff.get(domain, 0)
            if current_backoff == 0:
                new_backoff = 2
            else:
                new_backoff = min(current_backoff * 2, 60)
            self._domain_backoff[domain] = new_backoff
            
    async def report_success(self, domain: str):
        """Resets backoff for a domain."""
        async with self._lock:
            if domain in self._domain_backoff:
                self._domain_backoff[domain] = 0
