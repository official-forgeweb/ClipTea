"""Campaign auto-stop monitoring background task."""
import discord
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from database.manager import DatabaseManager
from campaign.payment_calculator import (
    calculate_earnings, is_budget_exhausted, budget_percentage_used
)
from utils.formatters import format_currency, format_number


class CampaignMonitor(commands.Cog):
    """Background task that monitors campaigns for auto-stop conditions."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self._warned_campaigns = set()  # Track campaigns we've already sent 80% warnings for
        self.monitor_campaigns.start()

    def cog_unload(self):
        self.monitor_campaigns.cancel()

    @tasks.loop(minutes=5)
    async def monitor_campaigns(self):
        """Check all active campaigns for auto-stop conditions every 5 minutes."""
        try:
            active_campaigns = await self.db.get_active_campaigns()

            for campaign in active_campaigns:
                if not campaign.get('auto_stop', True):
                    continue

                campaign_id = campaign['id']
                stats = await self.db.get_campaign_statistics(campaign_id)

                should_stop = False
                reason = ""

                # Check budget
                budget = campaign.get('budget')
                if budget is not None:
                    total_views = stats.get('grand_total_views', 0)
                    rate = campaign.get('rate_per_10k_views', 10.0)

                    if is_budget_exhausted(budget, total_views, rate):
                        should_stop = True
                        reason = f"💰 Budget limit reached ({format_currency(budget)})"

                    # Send 80% warning
                    elif campaign_id not in self._warned_campaigns:
                        pct = budget_percentage_used(budget, total_views, rate)
                        if pct >= 80:
                            self._warned_campaigns.add(campaign_id)
                            await self._send_budget_warning(campaign, pct)

                # Check duration
                if not should_stop and campaign.get('duration_days') is not None:
                    try:
                        created_str = campaign.get('created_at', '')
                        created_at = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                        end_date = created_at + timedelta(days=campaign['duration_days'])
                        if datetime.now() >= end_date.replace(tzinfo=None):
                            should_stop = True
                            reason = f"⏱️ Duration expired ({campaign['duration_days']} days)"
                    except (ValueError, AttributeError):
                        pass

                # Check max views
                if not should_stop and campaign.get('max_views_cap') is not None:
                    total_views = stats.get('grand_total_views', 0)
                    if total_views >= campaign['max_views_cap']:
                        should_stop = True
                        reason = f"👁️ Max views reached ({format_number(campaign['max_views_cap'])})"

                # Auto-stop if needed
                if should_stop:
                    await self.db.update_campaign_status(campaign_id, 'completed', reason)
                    await self._send_campaign_ended(campaign, stats, reason)

        except Exception as e:
            print(f"[MONITOR] Error in campaign monitor: {e}")

    async def _send_budget_warning(self, campaign: dict, percentage: float):
        """Send a budget warning notification."""
        channel_id = await self.db.get_setting("notification_channel_id")
        if not channel_id:
            return

        try:
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                embed = discord.Embed(
                    title=f"⚠️ Budget Warning: {campaign['name']}",
                    description=f"Campaign `{campaign['id']}` has used **{percentage:.1f}%** of its budget!",
                    color=discord.Color.orange()
                )
                embed.add_field(
                    name="Budget",
                    value=format_currency(campaign.get('budget', 0)),
                    inline=True
                )
                await channel.send(embed=embed)

            await self.db.log_notification(
                campaign_id=campaign['id'],
                notif_type="budget_warning",
                message=f"Budget {percentage:.1f}% used",
                channel_id=channel_id
            )
        except Exception as e:
            print(f"[MONITOR] Error sending budget warning: {e}")

    async def _send_campaign_ended(self, campaign: dict, stats: dict, reason: str):
        """Send a campaign ended notification with full summary."""
        channel_id = await self.db.get_setting("notification_channel_id")
        if not channel_id:
            return

        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return

            rate = campaign.get('rate_per_10k_views', 10.0)
            total_views = stats.get('grand_total_views', 0)
            total_earned = calculate_earnings(total_views, rate)

            embed = discord.Embed(
                title=f"🏁 CAMPAIGN ENDED: {campaign['name']}",
                description=f"**ID:** `{campaign['id']}`\n**Reason:** {reason}",
                color=discord.Color.red()
            )

            # Campaign stats
            member_count = await self.db.get_campaign_member_count(campaign['id'])
            video_count = await self.db.get_campaign_video_count(campaign['id'])

            embed.add_field(name="👥 Total Clippers", value=str(member_count), inline=True)
            embed.add_field(name="📹 Total Videos", value=str(video_count), inline=True)
            embed.add_field(name="👁️ Total Views", value=format_number(total_views), inline=True)
            embed.add_field(name="❤️ Total Likes", value=format_number(stats.get('total_likes', 0)), inline=True)

            budget = campaign.get('budget')
            if budget:
                embed.add_field(
                    name="💰 Budget Used",
                    value=f"{format_currency(total_earned)} of {format_currency(budget)}",
                    inline=True
                )

            # Top performers
            leaderboard = await self.db.get_leaderboard(campaign['id'], metric="views", limit=5)
            if leaderboard:
                lb_text = ""
                medals = {0: "🥇", 1: "🥈", 2: "🥉"}
                for i, entry in enumerate(leaderboard):
                    medal = medals.get(i, f"#{i + 1}")
                    user_id = entry['discord_user_id']
                    earned = calculate_earnings(entry['total_views'], rate)
                    lb_text += (
                        f"{medal} <@{user_id}> — "
                        f"{entry['total_videos']} videos │ "
                        f"{format_number(entry['total_views'])} views │ "
                        f"{format_currency(earned)}\n"
                    )
                embed.add_field(name="🏆 Top Performers", value=lb_text, inline=False)

            # Platform breakdown
            breakdown = await self.db.get_campaign_platform_breakdown(campaign['id'])
            if breakdown:
                plat_emojis = {"instagram": "📷", "tiktok": "🎵", "twitter": "🐦"}
                plat_text = ""
                for plat in breakdown:
                    emoji = plat_emojis.get(plat['platform'], "🌐")
                    pct = (plat['total_views'] / total_views * 100) if total_views > 0 else 0
                    plat_text += f"{emoji} {plat['platform'].title()}: {format_number(plat['total_views'])} views ({pct:.1f}%)\n"
                embed.add_field(name="📱 Platform Breakdown", value=plat_text, inline=False)

            await channel.send(embed=embed)

            await self.db.log_notification(
                campaign_id=campaign['id'],
                notif_type="ended",
                message=reason,
                channel_id=channel_id
            )

        except Exception as e:
            print(f"[MONITOR] Error sending campaign end notification: {e}")

    @monitor_campaigns.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(CampaignMonitor(bot))
