import asyncio
import aiohttp
import os
from typing import Optional, List
from config import FREE_PROXY_SOURCES, PROXY_TEST_URL, PROXY_TEST_TIMEOUT, PROXY_REFRESH_INTERVAL, ROTATING_PROXY_URL, PROXY_FILE

class ProxyRotator:
    def __init__(self):
        self._working_proxies: List[str] = []
        self._dead_proxies: set[str] = set()
        self._current_index: int = 0
        self._lock = asyncio.Lock()
        self._initialized = False
        
    async def initialize(self):
        """Fetch and test free proxies on startup."""
        if self._initialized and self._working_proxies:
            return
            
        print("[PROXY] Fetching fresh proxies from internet sources...")
        raw_proxies = await self._fetch_free_proxies()
        self._working_proxies = await self._test_proxies(raw_proxies)
        
        if not self._working_proxies:
            print("[PROXY] Critical: No working proxies found. Retrying with a larger sample...")
            # Try a larger sample if first one failed
            self._working_proxies = await self._test_proxies(raw_proxies, max_concurrent=30)
            
        self._initialized = True
        print(f"[PROXY] {len(self._working_proxies)} working proxies found")

    async def _fetch_free_proxies(self) -> List[str]:
        """Download proxy lists from free public sources."""
        proxies = set()
        
        # Load local proxies if available
        if os.path.exists(PROXY_FILE):
            try:
                with open(PROXY_FILE, 'r') as f:
                    local_proxies = [line.strip() for line in f if line.strip()]
                    proxies.update(local_proxies)
                    print(f"[PROXY] Loaded {len(local_proxies)} proxies from {PROXY_FILE}")
            except Exception as e:
                print(f"[PROXY] Error reading {PROXY_FILE}: {e}")

        # Fetch from remote sources
        async with aiohttp.ClientSession() as session:
            for url in FREE_PROXY_SOURCES:
                try:
                    async with session.get(url, timeout=10) as response:
                        if response.status == 200:
                            text = await response.text()
                            fetched = [p.strip() for p in text.splitlines() if p.strip()]
                            proxies.update(fetched)
                except Exception as e:
                    print(f"[PROXY] Failed to fetch from {url}: {e}")
        
        return list(proxies)

    async def _test_proxies(self, proxies: List[str], max_concurrent: int = 20, timeout: int = PROXY_TEST_TIMEOUT) -> List[str]:
        """Test proxies concurrently, keep only working ones."""
        working = []
        
        # Testing thousands of proxies clogs the asyncio event loop.
        # We've increased the sample size to 500 to ensure a healthier pool of working proxies.
        import random
        proxies_to_test = random.sample(proxies, min(500, len(proxies)))
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def test_and_add(proxy):
            async with semaphore:
                await asyncio.sleep(0.05)  # Yield explicitly to the event loop
                if await self._test_single_proxy(proxy, timeout):
                    working.append(proxy)
                    
        # Group tasks into chunks to prevent overwhelming the event loop
        chunk_size = 50
        for i in range(0, len(proxies_to_test), chunk_size):
            chunk = proxies_to_test[i:i + chunk_size]
            tasks = [asyncio.create_task(test_and_add(p)) for p in chunk]
            await asyncio.gather(*tasks)
            await asyncio.sleep(0.2)  # Give Discord gateway time to respond to pings
            
        return working

    async def _test_single_proxy(self, proxy: str, timeout: int) -> bool:
        """Test if a single proxy works."""
        if not proxy.startswith("http://") and not proxy.startswith("https://"):
            proxy_url = f"http://{proxy}"
        else:
            proxy_url = proxy

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(PROXY_TEST_URL, proxy=proxy_url, timeout=timeout) as response:
                    return response.status == 200
        except Exception:
            return False

    async def get_proxy(self) -> Optional[dict]:
        """Get next working proxy in Playwright format."""
        if ROTATING_PROXY_URL:
            from urllib.parse import urlparse
            p = urlparse(ROTATING_PROXY_URL if ROTATING_PROXY_URL.startswith('http') else f"http://{ROTATING_PROXY_URL}")
            d = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
            if p.username and p.password:
                d["username"] = p.username
                d["password"] = p.password
            return d
            
        async with self._lock:
            if not self._working_proxies:
                print("[PROXY] Warning: No working free proxies available.")
                return None
                
            proxy = self._working_proxies[self._current_index]
            self._current_index = (self._current_index + 1) % len(self._working_proxies)
            
            if not proxy.startswith("http://") and not proxy.startswith("https://"):
                proxy = f"http://{proxy}"
            
            # Parse credentials if present (e.g., http://user:pass@ip:port)
            from urllib.parse import urlparse
            parsed = urlparse(proxy)
            
            proxy_dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
            if parsed.username and parsed.password:
                proxy_dict["username"] = parsed.username
                proxy_dict["password"] = parsed.password
                
            return proxy_dict

    async def mark_failed(self, proxy_server: str):
        """Mark proxy as dead, remove from working pool."""
        clean_proxy = proxy_server.replace("http://", "").replace("https://", "")
        async with self._lock:
            # Check without scheme
            if clean_proxy in self._working_proxies:
                self._working_proxies.remove(clean_proxy)
                self._dead_proxies.add(clean_proxy)
                if self._current_index >= len(self._working_proxies) and self._working_proxies:
                    self._current_index = 0
            
            # Check with scheme
            if proxy_server in self._working_proxies:
                self._working_proxies.remove(proxy_server)
                self._dead_proxies.add(proxy_server)
                if self._current_index >= len(self._working_proxies) and self._working_proxies:
                    self._current_index = 0

    async def refresh_proxies(self):
        """Fetch fresh proxy list. Call periodically."""
        print("[PROXY] Refreshing proxy list...")
        raw_proxies = await self._fetch_free_proxies()
        
        # Filter dead proxies
        raw_proxies = [p for p in raw_proxies if p not in self._dead_proxies and f"http://{p}" not in self._dead_proxies]
        working = await self._test_proxies(raw_proxies)
        
        async with self._lock:
            self._working_proxies = list(set(self._working_proxies + working))
