"""Periodic scraping background task using discord.ext.tasks."""
import discord
from discord.ext import commands, tasks
from database.manager import DatabaseManager
from services.unified_scraper import UnifiedScraper


class PeriodicScraper(commands.Cog):
    """Background task that periodically re-scrapes all tracked videos."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.scraper = UnifiedScraper(self.db)
        self._initialized = False
        self.periodic_scrape.start()

    def cog_unload(self):
        self.periodic_scrape.cancel()

    @tasks.loop(minutes=60)
    async def periodic_scrape(self):
        """Re-scrape all tracked videos at the configured interval."""
        print("[SCRAPER] Starting periodic scrape cycle...")

        try:
            # Get configured interval and adjust loop if needed
            interval_str = await self.db.get_setting("scrape_interval_minutes")
            if interval_str:
                try:
                    interval = int(interval_str)
                    if interval != self.periodic_scrape.minutes:
                        self.periodic_scrape.change_interval(minutes=interval)
                        print(f"[SCRAPER] Updated scrape interval to {interval} minutes")
                except ValueError:
                    pass

            # Skip the very first run on startup to avoid "testing" delay
            if not self._initialized:
                self._initialized = True
                print("[SCRAPER] Startup complete. First scheduled scrape will run later.")
                return

            # Scrape all active tracking videos
            summary = await self.scrape_all_tracking_videos()

            print(
                f"[SCRAPER] Scrape cycle complete: "
                f"{summary['successful']}/{summary['total_videos']} successful, "
                f"{summary['failed']} failed"
            )

            # Send notification to admin channel if configured
            channel_id = await self.db.get_setting("notification_channel_id")
            if channel_id and summary['total_videos'] > 0:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        embed = discord.Embed(
                            title="🔄 Periodic Scrape Complete",
                            color=discord.Color.blue()
                        )
                        embed.add_field(
                            name="Results",
                            value=(
                                f"✅ Successful: {summary['successful']}\n"
                                f"❌ Failed: {summary['failed']}\n"
                                f"📹 Total Videos: {summary['total_videos']}"
                            ),
                            inline=False
                        )
                        if summary['errors'][:3]:
                            embed.add_field(
                                name="Recent Errors",
                                value="\n".join(summary['errors'][:3]),
                                inline=False
                            )
                        await channel.send(embed=embed)
                except discord.Forbidden:
                    print(f"[SCRAPER] Permission error: Bot cannot send messages in notification channel ({channel_id}). Please check channel permissions.")
                except Exception as e:
                    print(f"[SCRAPER] Error sending notification: {e}")

            # Log notification
            if summary['total_videos'] > 0:
                await self.db.log_notification(
                    campaign_id="",
                    notif_type="scrape_complete",
                    message=f"Scraped {summary['successful']}/{summary['total_videos']} videos",
                    channel_id=channel_id or ""
                )

        except Exception as e:
            print(f"[SCRAPER] Error in periodic scrape: {e}")

            channel_id = await self.db.get_setting("notification_channel_id")
            if channel_id:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        embed = discord.Embed(
                            title="⚠️ Scrape Error",
                            description=f"```{str(e)[:500]}```",
                            color=discord.Color.red()
                        )
                        await channel.send(embed=embed)
                except Exception:
                    pass

    async def scrape_all_tracking_videos(self) -> dict:
        """Scrape metrics for all actively tracked videos across all active campaigns."""
        import asyncio
        from datetime import datetime, timezone
        
        videos = await self.db.get_all_tracking_videos()
        summary = {"total_videos": len(videos), "successful": 0, "failed": 0, "errors": []}

        for i, video in enumerate(videos):
            video_url = video["video_url"]
            platform = video["platform"]
            video_id = video["id"]

            # Check for 24h expiration
            exp_at_str = video.get('tracking_expires_at')
            if exp_at_str:
                try:
                    exp_at = datetime.fromisoformat(exp_at_str.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) > exp_at:
                        metrics = await self.db.get_latest_metrics(video_id)
                        await self.db.mark_video_final(
                            video_id,
                            metrics.get('views', 0) if metrics else 0,
                            metrics.get('likes', 0) if metrics else 0,
                            metrics.get('comments', 0) if metrics else 0
                        )
                        continue
                except Exception as e:
                    pass

            try:
                metrics = await self.scraper.get_video_metrics(video_url, platform)
                if metrics and not metrics.get("error"):
                    await self.db.save_metric_snapshot(
                        video_id=video_id,
                        views=metrics.get("views", 0),
                        likes=metrics.get("likes", 0),
                        comments=metrics.get("comments", 0),
                        shares=metrics.get("shares", 0),
                        extra_data=str(metrics.get("bookmarks", "")) if platform == "twitter" else metrics.get("title", "")
                    )
                    summary["successful"] += 1
                else:
                    summary["failed"] += 1
                    summary["errors"].append(metrics.get("error", f"No metrics returned for {video_url}"))
            except Exception as e:
                summary["failed"] += 1
                summary["errors"].append(f"Error for {video_url}: {str(e)}")

            # Small delay between videos to prevent aggressive scraping
            await asyncio.sleep(1.5)

        return summary

    @periodic_scrape.before_loop
    async def before_scrape(self):
        """Wait for bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()
        # Small initial delay to let everything initialize
        import asyncio
        await asyncio.sleep(10)


async def setup(bot: commands.Bot):
    await bot.add_cog(PeriodicScraper(bot))
