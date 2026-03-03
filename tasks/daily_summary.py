"""Daily summary report generation and delivery."""
import asyncio
import discord
from datetime import datetime
from discord.ext import commands, tasks
from database.manager import DatabaseManager
from campaign.payment_calculator import calculate_earnings
from utils.formatters import format_number, format_currency


class DailySummary(commands.Cog):
    """Background task that sends daily campaign summary."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self._last_sent_date = None
        self.daily_check.start()

    def cog_unload(self):
        self.daily_check.cancel()

    @tasks.loop(minutes=1)
    async def daily_check(self):
        """Check every minute if it's time to send the daily summary."""
        try:
            enabled = await self.db.get_setting("daily_summary_enabled")
            if enabled != "true":
                return

            target_time = await self.db.get_setting("daily_summary_time")
            if not target_time:
                target_time = "09:00"

            now = datetime.now()
            current_time = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")

            # Check if it's time and we haven't sent today
            if current_time == target_time and self._last_sent_date != today:
                self._last_sent_date = today
                await self._send_daily_summary()

        except Exception as e:
            print(f"[DAILY] Error in daily check: {e}")

    async def _send_daily_summary(self):
        """Generate and send the daily summary to the configured channel."""
        channel_id = await self.db.get_setting("notification_channel_id")
        if not channel_id:
            return

        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return

            active_campaigns = await self.db.get_active_campaigns()
            paused_campaigns = await self.db.get_campaigns_by_status("paused")
            completed_campaigns = await self.db.get_campaigns_by_status("completed")

            embed = discord.Embed(
                title="📊 Daily Summary Report",
                description=f"**{datetime.now().strftime('%B %d, %Y')}**",
                color=discord.Color.gold()
            )

            embed.add_field(
                name="Campaign Overview",
                value=(
                    f"🟢 Active: {len(active_campaigns)}\n"
                    f"⏸️ Paused: {len(paused_campaigns)}\n"
                    f"✅ Completed: {len(completed_campaigns)}"
                ),
                inline=False
            )

            # Summary for each active campaign
            for campaign in active_campaigns[:5]:  # Limit to 5 to avoid embed limits
                stats = await self.db.get_campaign_statistics(campaign['id'])
                member_count = await self.db.get_campaign_member_count(campaign['id'])
                video_count = await self.db.get_campaign_video_count(campaign['id'])

                rate = campaign.get('rate_per_10k_views', 10.0)
                total_views = stats.get('grand_total_views', 0)
                total_earned = calculate_earnings(total_views, rate)

                budget_text = ""
                budget = campaign.get('budget')
                if budget:
                    pct = min(100, (total_earned / budget * 100)) if budget > 0 else 0
                    budget_text = f"\n💰 Budget: {format_currency(total_earned)}/{format_currency(budget)} ({pct:.1f}%)"

                embed.add_field(
                    name=f"📋 {campaign['name']}",
                    value=(
                        f"👥 {member_count} clippers │ 📹 {video_count} videos\n"
                        f"👁️ {format_number(total_views)} views │ 💵 {format_currency(total_earned)}"
                        f"{budget_text}"
                    ),
                    inline=False
                )

            if len(active_campaigns) > 5:
                embed.add_field(
                    name="",
                    value=f"*...and {len(active_campaigns) - 5} more active campaigns*",
                    inline=False
                )

            embed.set_footer(text="Daily summary • Configure with /set_daily_summary")
            await channel.send(embed=embed)

            await self.db.log_notification(
                campaign_id="",
                notif_type="daily_summary",
                message=f"Daily summary sent for {len(active_campaigns)} active campaigns",
                channel_id=channel_id
            )

        except Exception as e:
            print(f"[DAILY] Error sending daily summary: {e}")

    @daily_check.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(DailySummary(bot))
