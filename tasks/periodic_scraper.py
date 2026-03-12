"""Periodic scraping background task — uses the smart scrape queue."""
import asyncio
import discord
from datetime import datetime, timezone
from discord.ext import commands, tasks
from database.manager import DatabaseManager


class PeriodicScraper(commands.Cog):
    """Background task that adds tracked videos to the scrape queue
    with smart intervals based on video age."""

    # ── Smart interval table ─────────────────────────
    # age_hours_max → scrape_every_hours
    INTERVALS = [
        (24, 3),      # 0-24 h old  → every 3 hours
        (72, 6),      # 24-72 h old → every 6 hours
        (168, 12),    # 72-168 h    → every 12 hours
        (float('inf'), 24),  # 168+ h → every 24 hours
    ]

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self._initialized = False
        self.periodic_scrape.start()

    def cog_unload(self):
        self.periodic_scrape.cancel()

    # ── Main loop ─────────────────────────────────────

    @tasks.loop(minutes=60)
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

            # Skip the very first run on startup
            if not self._initialized:
                self._initialized = True
                print("[SCRAPER] Startup complete. First scheduled check will run later.")
                return

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

            # ── Check for expiration ──────────────────
            exp_at_str = video.get('tracking_expires_at')
            if exp_at_str:
                try:
                    exp_at = datetime.fromisoformat(exp_at_str.replace("Z", "+00:00"))
                    if exp_at.tzinfo is None:
                        exp_at = exp_at.replace(tzinfo=timezone.utc)

                    if now > exp_at:
                        # Add a final scrape job (high priority so it runs sooner)
                        queue.add_periodic_job(
                            video_url=video_url,
                            discord_user_id=video.get('discord_user_id', ''),
                            campaign_id=video.get('campaign_id', ''),
                        )

                        # Get the latest known metrics for marking final
                        latest = await self.db.get_latest_metrics(video_id)
                        final_v = latest.get('views', 0) if latest else 0
                        final_l = latest.get('likes', 0) if latest else 0
                        final_c = latest.get('comments', 0) if latest else 0

                        await self.db.mark_video_final(video_id, final_v, final_l, final_c)
                        summary["expired"] += 1
                        continue
                except Exception as e:
                    print(f"[SCRAPER] Expiration error for {video_id}: {e}")

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
        """Check if a video is due for re-scraping based on its age."""
        # Determine video age
        posted_at_str = video.get('posted_at') or video.get('submitted_at', '')
        if posted_at_str:
            try:
                posted_at = datetime.fromisoformat(posted_at_str.replace("Z", "+00:00"))
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
                age_hours = (now - posted_at).total_seconds() / 3600
            except Exception:
                age_hours = 48  # Default if unparseable
        else:
            age_hours = 48  # Default

        # Determine scrape interval for this video's age
        scrape_every_hours = 24  # default fallback
        for max_age, interval in self.INTERVALS:
            if age_hours <= max_age:
                scrape_every_hours = interval
                break

        # Check last_scraped_at
        last_scraped_str = video.get('last_scraped_at', '')
        if not last_scraped_str:
            return True  # Never scraped → definitely due

        try:
            last_scraped = datetime.fromisoformat(last_scraped_str.replace("Z", "+00:00"))
            if last_scraped.tzinfo is None:
                last_scraped = last_scraped.replace(tzinfo=timezone.utc)
            hours_since = (now - last_scraped).total_seconds() / 3600
            return hours_since >= scrape_every_hours
        except Exception:
            return True  # If we can't parse, scrape it

    @periodic_scrape.before_loop
    async def before_scrape(self):
        """Wait for bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)


async def setup(bot: commands.Bot):
    await bot.add_cog(PeriodicScraper(bot))

