import json
from typing import List, Dict, Optional
from scrapers.base_scraper import BaseScraper
from config import PAGE_TIMEOUT

class TikTokScraper(BaseScraper):
    """Scraper logic specifically for TikTok public profiles."""
    
    async def scrape_user_posts(self, username: str, max_posts: int = 20) -> List[Dict]:
        await self.rate_limiter.wait("tiktok.com")
        posts = []
        
        try:
            page = await self._create_optimized_page()
            profile_url = f"https://www.tiktok.com/@{username}"
            
            response = await page.goto(profile_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            if response and response.status == 404:
                print(f"[TikTok] User {username} not found.")
                return posts
                
            await self._human_like_delay()
            
            # Scroll to load more videos if needed
            for _ in range(3):
                await self._random_scroll(page)
                
            # Method 1: <script id="SIGI_STATE">
            try:
                sigi_state = await page.evaluate("() => { "
                    "const el = document.getElementById('SIGI_STATE');"
                    "return el ? el.innerHTML : null;"
                "}")
                
                if sigi_state:
                    data = json.loads(sigi_state)
                    item_module = data.get('ItemModule', {})
                    
                    for video_id, video_data in item_module.items():
                        if len(posts) >= max_posts:
                            break
                            
                        stats = video_data.get('stats', {})
                        posts.append({
                            "post_url": f"https://www.tiktok.com/@{username}/video/{video_id}",
                            "post_id": video_id,
                            "caption": video_data.get('desc', ''),
                            "views": stats.get('playCount', 0),
                            "likes": stats.get('diggCount', 0),
                            "comments": stats.get('commentCount', 0),
                            "shares": stats.get('shareCount', 0),
                            "posted_at": str(video_data.get('createTime', ''))
                        })
                        
            except Exception as e:
                print(f"[TikTok] SIGI_STATE extraction error: {e}")
                
            # Method 2 fallback
            if not posts:
                try:
                    rehyd_state = await page.evaluate("() => { "
                        "const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');"
                        "return el ? el.innerHTML : null;"
                    "}")
                    print("[TikTok] SIGI_STATE was empty, fallback __UNIVERSAL_DATA_FOR_REHYDRATION__ available.")
                except Exception:
                    pass
                    
            await self.rate_limiter.report_success("tiktok.com")
            
        except Exception as e:
            await self.rate_limiter.report_error("tiktok.com")
            print(f"[TikTok Error] Failed scraping user {username}: {str(e)}")
        finally:
            await self._teardown_browser()
            
        return posts[:max_posts]

    async def scrape_post_metrics(self, post_url: str) -> Optional[Dict]:
        await self.rate_limiter.wait("tiktok.com")
        metrics = None
        
        try:
            page = await self._create_optimized_page()
            await page.goto(post_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            await self._human_like_delay()
            
            sigi_state = await page.evaluate("() => { "
                "const el = document.getElementById('SIGI_STATE');"
                "return el ? el.innerHTML : null;"
            "}")
            
            if sigi_state:
                data = json.loads(sigi_state)
                item_module = data.get('ItemModule', {})
                
                for _, video_data in item_module.items():
                    stats = video_data.get('stats', {})
                    metrics = {
                        "views": stats.get('playCount', 0),
                        "likes": stats.get('diggCount', 0),
                        "comments": stats.get('commentCount', 0),
                        "shares": stats.get('shareCount', 0)
                    }
                    break
                    
            await self.rate_limiter.report_success("tiktok.com")
        except Exception as e:
            await self.rate_limiter.report_error("tiktok.com")
            print(f"[TikTok Error] Failed scraping post {post_url}: {str(e)}")
        finally:
            await self._teardown_browser()
            
        return metrics
