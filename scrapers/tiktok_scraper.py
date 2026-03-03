import json
import re
from typing import List, Dict, Optional
from scrapers.base_scraper import BaseScraper
from config import PAGE_TIMEOUT


class TikTokScraper(BaseScraper):
    """Scraper logic specifically for TikTok public profiles and individual videos."""

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
                            "author_username": username,
                            "caption": video_data.get('desc', ''),
                            "views": stats.get('playCount', 0),
                            "likes": stats.get('diggCount', 0),
                            "comments": stats.get('commentCount', 0),
                            "shares": stats.get('shareCount', 0),
                            "posted_at": str(video_data.get('createTime', '')),
                            "platform": "tiktok"
                        })

            except Exception as e:
                print(f"[TikTok] SIGI_STATE extraction error: {e}")

            # Method 2: __UNIVERSAL_DATA_FOR_REHYDRATION__
            if not posts:
                try:
                    rehyd_state = await page.evaluate("() => { "
                        "const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');"
                        "return el ? el.innerHTML : null;"
                    "}")
                    if rehyd_state:
                        data = json.loads(rehyd_state)
                        # Navigate the rehydration data structure
                        default_scope = data.get('__DEFAULT_SCOPE__', {})
                        webapp = default_scope.get('webapp.user-detail', {})
                        user_info = webapp.get('userInfo', {})
                        item_list = default_scope.get('webapp.video-detail', {})
                        print("[TikTok] Parsed __UNIVERSAL_DATA_FOR_REHYDRATION__ fallback.")
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

            # fallback: __UNIVERSAL_DATA__
            if not metrics:
                rehyd = await page.evaluate("() => { "
                    "const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');"
                    "return el ? el.innerHTML : null;"
                "}")
                if rehyd:
                    data = json.loads(rehyd)
                    default_scope = data.get('__DEFAULT_SCOPE__', {})
                    video_detail = default_scope.get('webapp.video-detail', {})
                    item_info = video_detail.get('itemInfo', {}).get('itemStruct', {})
                    stats = item_info.get('stats', {})
                    if stats:
                        metrics = {
                            "views": stats.get('playCount', 0),
                            "likes": stats.get('diggCount', 0),
                            "comments": stats.get('commentCount', 0),
                            "shares": stats.get('shareCount', 0)
                        }

            await self.rate_limiter.report_success("tiktok.com")
        except Exception as e:
            await self.rate_limiter.report_error("tiktok.com")
            print(f"[TikTok Error] Failed scraping post {post_url}: {str(e)}")
        finally:
            await self._teardown_browser()

        return metrics

    async def scrape_single_video(self, video_url: str) -> Optional[Dict]:
        """Scrape a single TikTok video and extract author + metrics.
        Tries with proxy first, falls back to direct connection."""
        await self.rate_limiter.wait("tiktok.com")

        for attempt, use_proxy in enumerate([True, False]):
            result = await self._attempt_scrape_video(video_url, use_proxy=use_proxy)
            if result is not None:
                return result
            if attempt == 0:
                print(f"[TikTok] Proxy failed for {video_url}, retrying with direct connection...")

        return None

    async def _attempt_scrape_video(self, video_url: str, use_proxy: bool = True) -> Optional[Dict]:
        """Single attempt to scrape a TikTok video."""
        result = None

        try:
            page = await self._create_optimized_page(use_proxy=use_proxy)
            await page.goto(video_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            await self._human_like_delay()

            author_username = ""
            views = 0
            likes = 0
            comments = 0
            shares = 0
            caption = ""
            video_id = ""

            # Extract video ID from URL
            match = re.search(r'tiktok\.com/@[\w.-]+/video/(\d+)', video_url)
            if match:
                video_id = match.group(1)

            # Method 1: SIGI_STATE
            try:
                sigi_state = await page.evaluate("() => { "
                    "const el = document.getElementById('SIGI_STATE');"
                    "return el ? el.innerHTML : null;"
                "}")

                if sigi_state:
                    data = json.loads(sigi_state)
                    item_module = data.get('ItemModule', {})

                    for vid, video_data in item_module.items():
                        author_username = video_data.get('author', '')
                        if not author_username:
                            author_info = data.get('UserModule', {}).get('users', {})
                            if author_info:
                                author_username = list(author_info.keys())[0]

                        stats = video_data.get('stats', {})
                        views = stats.get('playCount', 0)
                        likes = stats.get('diggCount', 0)
                        comments = stats.get('commentCount', 0)
                        shares = stats.get('shareCount', 0)
                        caption = video_data.get('desc', '')
                        break
            except Exception as e:
                print(f"[TikTok] SIGI_STATE video extraction error: {e}")

            # Method 2: __UNIVERSAL_DATA_FOR_REHYDRATION__
            if not author_username:
                try:
                    rehyd = await page.evaluate("() => { "
                        "const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');"
                        "return el ? el.innerHTML : null;"
                    "}")
                    if rehyd:
                        data = json.loads(rehyd)
                        default_scope = data.get('__DEFAULT_SCOPE__', {})
                        video_detail = default_scope.get('webapp.video-detail', {})
                        item_info = video_detail.get('itemInfo', {}).get('itemStruct', {})

                        author_obj = item_info.get('author', {})
                        author_username = author_obj.get('uniqueId', '') or author_obj.get('nickname', '')

                        stats = item_info.get('stats', {})
                        views = views or stats.get('playCount', 0)
                        likes = likes or stats.get('diggCount', 0)
                        comments = comments or stats.get('commentCount', 0)
                        shares = shares or stats.get('shareCount', 0)
                        caption = caption or item_info.get('desc', '')
                except Exception as e:
                    print(f"[TikTok] Rehydration video extraction error: {e}")

            # Method 3: Extract from URL and meta tags
            if not author_username:
                url_match = re.search(r'tiktok\.com/@([\w.-]+)/', video_url)
                if url_match:
                    author_username = url_match.group(1)

            result = {
                "video_url": video_url,
                "video_id": video_id,
                "author_username": author_username,
                "caption": caption,
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "posted_at": "",
                "is_video": True,
                "platform": "tiktok"
            }

            await self.rate_limiter.report_success("tiktok.com")

        except Exception as e:
            await self.rate_limiter.report_error("tiktok.com")
            print(f"[TikTok Error] Failed scraping video {video_url} (proxy={use_proxy}): {str(e)}")
        finally:
            await self._teardown_browser()

        return result

