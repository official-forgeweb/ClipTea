"""Periodic scraping background task using discord.ext.tasks."""
import discord
from discord.ext import commands, tasks
from database.manager import DatabaseManager
from campaign.manager import CampaignManager


class PeriodicScraper(commands.Cog):
    """Background task that periodically re-scrapes all tracked videos."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.campaign_mgr = CampaignManager(self.db)
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

            # Initialize proxy rotator if not yet done
            if not self._initialized:
                await self.campaign_mgr.initialize()
                self._initialized = True

            # Scrape all active tracking videos
            summary = await self.campaign_mgr.scrape_all_tracking_videos()

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

    @periodic_scrape.before_loop
    async def before_scrape(self):
        """Wait for bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()
        # Small initial delay to let everything initialize
        import asyncio
        await asyncio.sleep(10)


async def setup(bot: commands.Bot):
    await bot.add_cog(PeriodicScraper(bot))
