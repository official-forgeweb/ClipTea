import aiohttp
from typing import List, Dict, Optional
from scrapers.base_scraper import BaseScraper
from config import TWITTER_BEARER_TOKEN, PAGE_TIMEOUT

class TwitterScraper(BaseScraper):
    """Scraper logic specifically for Twitter/X. Uses API if available, falls back to scraping."""
    
    async def scrape_user_posts(self, username: str, max_posts: int = 20) -> List[Dict]:
        await self.rate_limiter.wait("x.com")
        posts = []
        
        # Method 1: Official API (Preferred)
        if TWITTER_BEARER_TOKEN:
            try:
                headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
                async with aiohttp.ClientSession() as session:
                    # Get user ID
                    async with session.get(f"https://api.twitter.com/2/users/by/username/{username}", headers=headers) as resp:
                        if resp.status == 200:
                            user_data = await resp.json()
                            user_id = user_data.get('data', {}).get('id')
                            
                            if user_id:
                                # Get tweets
                                tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets?tweet.fields=public_metrics,created_at&max_results={max_posts}"
                                async with session.get(tweets_url, headers=headers) as tw_resp:
                                    if tw_resp.status == 200:
                                        tweets_data = await tw_resp.json()
                                        for tweet in tweets_data.get('data', []):
                                            metrics = tweet.get('public_metrics', {})
                                            posts.append({
                                                "post_url": f"https://x.com/{username}/status/{tweet['id']}",
                                                "post_id": tweet['id'],
                                                "caption": tweet.get('text', ''),
                                                "views": metrics.get('impression_count', 0),
                                                "likes": metrics.get('like_count', 0),
                                                "comments": metrics.get('reply_count', 0),
                                                "shares": metrics.get('retweet_count', 0),
                                                "posted_at": tweet.get('created_at', '')
                                            })
                                        return posts
            except Exception as e:
                print(f"[Twitter API Error] {e}")
                
        # Method 2: Browser Scraping Fallback
        try:
            page = await self._create_optimized_page()
            
            tweets_data = []
            async def handle_response(response):
                if "UserTweets" in response.url:
                    try:
                        data = await response.json()
                        tweets_data.append(data)
                    except Exception:
                        pass
                        
            page.on("response", handle_response)
            
            profile_url = f"https://x.com/{username}"
            await page.goto(profile_url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
            
            await self._human_like_delay()
            for _ in range(2):
                await self._random_scroll(page)
                
            if not posts and len(tweets_data) == 0:
                print(f"[Twitter Scraper] No intercepted UserTweets for {username}")
                
            await self.rate_limiter.report_success("x.com")
            
        except Exception as e:
            await self.rate_limiter.report_error("x.com")
            print(f"[Twitter Scraper Error] Failed scraping user {username}: {str(e)}")
        finally:
            await self._teardown_browser()
            
        return posts[:max_posts]

    async def scrape_post_metrics(self, post_url: str) -> Optional[Dict]:
        await self.rate_limiter.wait("x.com")
        # Extract ID from url
        try:
            tweet_id = post_url.split('/')[-1]
            if TWITTER_BEARER_TOKEN:
                headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=public_metrics"
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            metrics = data.get('data', {}).get('public_metrics', {})
                            return {
                                "views": metrics.get('impression_count', 0),
                                "likes": metrics.get('like_count', 0),
                                "comments": metrics.get('reply_count', 0),
                                "shares": metrics.get('retweet_count', 0)
                            }
        except Exception as e:
            print(f"[Twitter] Error getting metrics for {post_url}: {e}")
        return None
