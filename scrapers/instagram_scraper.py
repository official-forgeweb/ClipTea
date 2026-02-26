import json
import re
from typing import List, Dict, Optional
from scrapers.base_scraper import BaseScraper
from config import PAGE_TIMEOUT

class InstagramScraper(BaseScraper):
    """Scraper logic specifically for Instagram public profiles."""
    
    async def scrape_user_posts(self, username: str, max_posts: int = 20) -> List[Dict]:
        await self.rate_limiter.wait("instagram.com")
        posts = []
        
        try:
            page = await self._create_optimized_page()
            
            # Setup response interception for GraphQL
            graphql_data = []
            async def handle_response(response):
                if "graphql/query" in response.url or "?query_hash=" in response.url:
                    try:
                        data = await response.json()
                        graphql_data.append(data)
                    except Exception:
                        pass
                        
            page.on("response", handle_response)
            
            profile_url = f"https://www.instagram.com/{username}/"
            response = await page.goto(profile_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            
            if response and response.status == 404:
                print(f"[IG] User {username} not found.")
                return posts
                
            await self._human_like_delay()
            
            # Check for login wall
            login_wall = await page.locator("text='Log In'").count()
            if login_wall > 0 and len(graphql_data) == 0:
                print(f"[IG] Hit login wall for {username}. Might need proxy switch.")
                
            await self._random_scroll(page)
            
            # Extract from sharedData (Method 1)
            try:
                shared_data_script = await page.evaluate("() => { "
                    "for (let s of document.getElementsByTagName('script')) {"
                    "  if (s.innerHTML.includes('window._sharedData')) return s.innerHTML;"
                    "}"
                    "return null;"
                "}")
                
                if shared_data_script:
                    match = re.search(r'window\._sharedData\s*=\s*({.+?});', shared_data_script)
                    if match:
                        data = json.loads(match.group(1))
                        # Parse out data.entry_data.ProfilePage[0].graphql.user.edge_owner_to_timeline_media.edges
                        edges = data.get('entry_data', {}).get('ProfilePage', [{}])[0].get('graphql', {}).get('user', {}).get('edge_owner_to_timeline_media', {}).get('edges', [])
                        
                        for edge in edges[:max_posts]:
                            node = edge.get('node', {})
                            shortcode = node.get('shortcode')
                            
                            if shortcode:
                                caption = ""
                                try:
                                    caption = node['edge_media_to_caption']['edges'][0]['node']['text']
                                except Exception:
                                    pass
                                    
                                posts.append({
                                    "post_url": f"https://www.instagram.com/p/{shortcode}/",
                                    "post_id": shortcode,
                                    "caption": caption,
                                    "views": node.get('video_view_count', 0),
                                    "likes": node.get('edge_liked_by', {}).get('count', 0),
                                    "comments": node.get('edge_media_to_comment', {}).get('count', 0),
                                    "shares": 0,
                                    "posted_at": str(node.get('taken_at_timestamp', ''))
                                })
            except Exception as e:
                print(f"[IG] _sharedData extraction error strings: {e}")
                
            if not posts:
                print(f"[IG] Could not extract posts for {username} via primary method")
                
            await self.rate_limiter.report_success("instagram.com")
            
        except Exception as e:
            await self.rate_limiter.report_error("instagram.com")
            print(f"[IG Error] Failed scraping user {username}: {str(e)}")
        finally:
            await self._teardown_browser()
            
        return posts[:max_posts]

    async def scrape_post_metrics(self, post_url: str) -> Optional[Dict]:
        await self.rate_limiter.wait("instagram.com")
        metrics = None
        
        try:
            page = await self._create_optimized_page()
            await page.goto(post_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            await self._human_like_delay()
            
            # Method 3: Parse meta description
            meta_desc = await page.get_attribute("meta[name='description']", "content")
            if meta_desc:
                likes_match = re.search(r'([\d,]+)\s+likes', meta_desc, re.IGNORECASE)
                comments_match = re.search(r'([\d,]+)\s+comments', meta_desc, re.IGNORECASE)
                
                likes = int(likes_match.group(1).replace(',', '')) if likes_match else 0
                comments = int(comments_match.group(1).replace(',', '')) if comments_match else 0
                
                metrics = {
                    "views": 0,
                    "likes": likes,
                    "comments": comments,
                    "shares": 0
                }
                
            await self.rate_limiter.report_success("instagram.com")
        except Exception as e:
            await self.rate_limiter.report_error("instagram.com")
            print(f"[IG Error] Failed scraping post {post_url}: {str(e)}")
        finally:
            await self._teardown_browser()
            
        return metrics
