"""Periodic scraping background task — uses the smart scrape queue."""
import asyncio
import discord
from datetime import datetime, timezone
from discord.ext import commands, tasks
from database.manager import DatabaseManager


class PeriodicScraper(commands.Cog):
    """Background task that adds tracked videos to the scrape queue
    with smart intervals based on video age."""

    # ── Scrape interval: every 6 hours for all videos ──
    SCRAPE_EVERY_HOURS = 6

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self._initialized = False
        self.periodic_scrape.start()

    def cog_unload(self):
        self.periodic_scrape.cancel()

    # ── Main loop ─────────────────────────────────────

    @tasks.loop(minutes=360)  # 6 hours
    async def periodic_scrape(self):
        """Check all tracked videos and add due ones to the scrape queue."""
        print("[SCRAPER] Starting periodic check cycle...")

        try:
            # Get configured interval and adjust loop if needed
            interval_str = await self.db.get_setting("scrape_interval_minutes")
            if interval_str:
                try:
                    interval = int(interval_str)
                    if interval != self.periodic_scrape.minutes:
                        self.periodic_scrape.change_interval(minutes=interval)
                        print(f"[SCRAPER] Updated check interval to {interval} minutes")
                except ValueError:
                    pass

            # No startup skip — _is_due_for_scrape() uses last_scraped_at
            # so recently scraped videos won't be re-queued on restart
            if not self._initialized:
                self._initialized = True
                print("[SCRAPER] First cycle — checking which videos are due...")

            # Get the scrape queue from the bot
            queue = getattr(self.bot, 'scrape_queue', None)
            if not queue:
                print("[SCRAPER] ⚠️ Scrape queue not available yet, skipping cycle")
                return

            # Process all active tracking videos
            summary = await self._check_and_enqueue(queue)

            print(
                f"[SCRAPER] Check cycle complete: "
                f"queued={summary['queued']}, "
                f"skipped={summary['skipped']}, "
                f"expired={summary['expired']}, "
                f"total={summary['total']}"
            )

            # Send notification to admin channel if configured
            channel_id = await self.db.get_setting("notification_channel_id")
            if channel_id and summary['total'] > 0:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        embed = discord.Embed(
                            title="🔄 Periodic Queue Update",
                            color=discord.Color.blue()
                        )
                        embed.add_field(
                            name="Results",
                            value=(
                                f"📥 Added to queue: {summary['queued']}\n"
                                f"⏭️ Skipped (not due): {summary['skipped']}\n"
                                f"🏁 Expired/finalized: {summary['expired']}\n"
                                f"📹 Total videos: {summary['total']}"
                            ),
                            inline=False
                        )
                        q_stats = queue.get_stats()
                        embed.add_field(
                            name="Queue Status",
                            value=(
                                f"📊 Queue size: {q_stats['queue_size']}\n"
                                f"🔄 Retry queue: {q_stats['retry_queue_size']}\n"
                                f"📈 Success rate: {q_stats['success_rate']}\n"
                                f"⏱️ Current delay: {q_stats['current_delay']}"
                            ),
                            inline=False
                        )
                        await channel.send(embed=embed)
                except discord.Forbidden:
                    print(f"[SCRAPER] Permission error for notification channel ({channel_id})")
                except Exception as e:
                    print(f"[SCRAPER] Error sending notification: {e}")

            # Log notification
            if summary['total'] > 0:
                await self.db.log_notification(
                    campaign_id="",
                    notif_type="scrape_queued",
                    message=f"Queued {summary['queued']}/{summary['total']} videos",
                    channel_id=channel_id or ""
                )

        except Exception as e:
            print(f"[SCRAPER] Error in periodic check: {e}")

            channel_id = await self.db.get_setting("notification_channel_id")
            if channel_id:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        embed = discord.Embed(
                            title="⚠️ Scraper Error",
                            description=f"```{str(e)[:500]}```",
                            color=discord.Color.red()
                        )
                        await channel.send(embed=embed)
                except Exception:
                    pass

    async def _check_and_enqueue(self, queue) -> dict:
        """Check all tracked videos and add due ones to the scrape queue."""
        videos = await self.db.get_all_tracking_videos()
        summary = {"total": len(videos), "queued": 0, "skipped": 0, "expired": 0}
        now = datetime.now(timezone.utc)

        for video in videos:
            video_url = video["video_url"]
            video_id = video["id"]

            # ── Expiration removed ────────────────────
            # Videos track indefinitely until admin stops campaign.

            # ── Smart interval check ──────────────────
            if not self._is_due_for_scrape(video, now):
                summary["skipped"] += 1
                continue

            # ── Add to queue ──────────────────────────
            queue.add_periodic_job(
                video_url=video_url,
                shortcode=video.get('video_id', ''),
                discord_user_id=video.get('discord_user_id', ''),
                campaign_id=video.get('campaign_id', ''),
            )
            summary["queued"] += 1

        return summary

    def _is_due_for_scrape(self, video: dict, now: datetime) -> bool:
        """Check if a video is due for re-scraping (every 6 hours)."""
        # Check last_scraped_at
        last_scraped_str = video.get('last_scraped_at', '')
        if not last_scraped_str:
            return True  # Never scraped → definitely due

        try:
            last_scraped = datetime.fromisoformat(last_scraped_str.replace("Z", "+00:00"))
            if last_scraped.tzinfo is None:
                last_scraped = last_scraped.replace(tzinfo=timezone.utc)
            hours_since = (now - last_scraped).total_seconds() / 3600
            return hours_since >= self.SCRAPE_EVERY_HOURS
        except Exception:
            return True  # If we can't parse, scrape it

    async def scrape_all_tracking_videos(self) -> dict:
        """Force scrape all currently tracking videos immediately via the queue."""
        videos = await self.db.get_all_tracking_videos()
        if not videos:
            return {"successful": 0, "failed": 0, "total_videos": 0, "errors": []}

        queue = getattr(self.bot, 'scrape_queue', None)
        if not queue:
            print("[SCRAPER] ⚠️ Scrape queue not available for force update")
            return {"successful": 0, "failed": 0, "total_videos": len(videos), "errors": ["Scrape queue not ready"]}

        print(f"[SCRAPER] 🚀 Force update requested for {len(videos)} videos")
        
        video_urls = [v['video_url'] for v in videos]
        
        # We use the queue's bulk submission
        # Note: This will WAIT for all jobs to finish.
        results = await queue.submit_bulk_and_track(video_urls)

        successful = 0
        failed = 0
        errors = []
        
        for res in results:
            if res.get("error") and res.get("views", 0) == 0:
                failed += 1
                errors.append(str(res.get("error")))
            else:
                successful += 1
                
        return {
            "successful": successful,
            "failed": failed,
            "total_videos": len(videos),
            "errors": list(set(errors))[:10]  # Limit error list
        }

    async def scrape_user_tracking_videos(self, discord_user_id: str) -> dict:
        """Force scrape only a specific user's tracked videos via the queue."""
        videos = await self.db.get_user_tracking_videos(discord_user_id)
        if not videos:
            return {"successful": 0, "failed": 0, "total_videos": 0, "errors": []}

        queue = getattr(self.bot, 'scrape_queue', None)
        if not queue:
            print("[SCRAPER] ⚠️ Scrape queue not available for user force update")
            return {"successful": 0, "failed": 0, "total_videos": len(videos), "errors": ["Scrape queue not ready"]}

        print(f"[SCRAPER] 🚀 Force update for user {discord_user_id}: {len(videos)} videos")

        video_urls = [v['video_url'] for v in videos]
        results = await queue.submit_bulk_and_track(video_urls)

        successful = 0
        failed = 0
        errors = []

        for res in results:
            if res.get("error") and res.get("views", 0) == 0:
                failed += 1
                errors.append(str(res.get("error")))
            else:
                successful += 1

        return {
            "successful": successful,
            "failed": failed,
            "total_videos": len(videos),
            "errors": list(set(errors))[:10]
        }

    @periodic_scrape.before_loop

    async def before_scrape(self):
        """Wait for bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)


async def setup(bot: commands.Bot):
    await bot.add_cog(PeriodicScraper(bot))

