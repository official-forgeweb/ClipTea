"""Stats commands: stats, leaderboard, campaign_statistics."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from campaign.payment_calculator import calculate_earnings
from utils.formatters import (
    format_number, format_compact, format_currency, format_timestamp,
    format_date, days_ago, platform_emoji, status_emoji, medal_emoji
)
from utils.permissions import is_admin


class StatsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    # ── USER STATS ─────────────────────────────────────
    @app_commands.command(name="stats", description="View your clipping statistics")
    @app_commands.describe(user="View another user's stats (admin only)")
    async def stats(self, interaction: discord.Interaction, user: discord.Member = None):
        # Admin check if viewing someone else
        if user and user.id != interaction.user.id:
            if not await is_admin(interaction):
                await interaction.response.send_message(
                    "❌ Only admins can view other users' stats.", ephemeral=True
                )
                return
            target_user = user
        else:
            target_user = interaction.user

        try:
            await interaction.response.defer()
        except (discord.errors.NotFound, Exception):
            return
        target_id = str(target_user.id)

        # Get accounts
        accounts = await self.db.get_user_accounts(target_id)

        # Get all-time stats
        all_stats = await self.db.get_user_all_time_stats(target_id)

        # Get first submission date
        first_sub = await self.db.get_first_submission_date(target_id)

        # Get campaigns
        user_campaigns = await self.db.get_user_campaigns(target_id)

        embed = discord.Embed(
            title="📊 CLIPPING STATS",
            color=discord.Color.purple()
        )

        embed.add_field(name="👤 Discord", value=f"{target_user}", inline=True)
        if target_user.joined_at:
            embed.add_field(
                name="📅 Joined Server",
                value=f"{target_user.joined_at.strftime('%b %d, %Y')}",
                inline=True
            )
        if first_sub:
            embed.add_field(
                name="🎬 Started Clipping",
                value=f"{format_date(first_sub)} ({days_ago(first_sub)})",
                inline=True
            )

        # Linked accounts
        embed.add_field(name="═══ 🔗 LINKED ACCOUNTS ═══", value="\u200b", inline=False)
        all_platforms = {"instagram": None, "tiktok": None, "twitter": None}
        for acc in accounts:
            all_platforms[acc['platform']] = acc

        for plat, acc in all_platforms.items():
            emoji = platform_emoji(plat)
            if acc:
                status = "✅" if acc.get('verified') else "⏳"
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value=f"@{acc['platform_username']} {status}",
                    inline=True
                )
            else:
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value="Not linked",
                    inline=True
                )

        # All-time stats
        total_views = all_stats.get('total_views', 0)
        total_videos = all_stats.get('total_videos', 0)
        total_likes = all_stats.get('total_likes', 0)
        total_comments = all_stats.get('total_comments', 0)

        # Calculate total earnings across all campaigns
        total_earned = 0
        for c in user_campaigns:
            c_stats = await self.db.get_user_campaign_stats(c['id'], target_id)
            rate = c.get('rate_per_10k_views', 10.0)
            total_earned += calculate_earnings(c_stats.get('total_views', 0), rate)

        embed.add_field(name="═══ 📈 ALL-TIME STATISTICS ═══", value="\u200b", inline=False)
        embed.add_field(name="🎬 Videos", value=format_number(total_videos), inline=True)
        embed.add_field(name="👁️ Views", value=format_number(total_views), inline=True)
        embed.add_field(name="❤️ Likes", value=format_number(total_likes), inline=True)
        embed.add_field(name="💬 Comments", value=format_number(total_comments), inline=True)
        embed.add_field(name="💰 Total Earned", value=format_currency(total_earned), inline=True)

        # Campaign history
        if user_campaigns:
            embed.add_field(name="═══ 📋 CAMPAIGN HISTORY ═══", value="\u200b", inline=False)

            for c in user_campaigns[:5]:
                c_stats = await self.db.get_user_campaign_stats(c['id'], target_id)
                rate = c.get('rate_per_10k_views', 10.0)
                earned = calculate_earnings(c_stats.get('total_views', 0), rate)

                status = status_emoji(c.get('status', 'active'))

                embed.add_field(
                    name=f"{status} {c['name']} ({c.get('status', 'active').title()})",
                    value=(
                        f"📹 {c_stats.get('total_videos', 0)} videos │ "
                        f"👁️ {format_compact(c_stats.get('total_views', 0))} views │ "
                        f"💵 {format_currency(earned)}\n"
                        f"Joined: {format_date(c.get('member_joined_at', ''))}"
                    ),
                    inline=False
                )

        # Achievements
        achievements = []
        if total_videos >= 1:
            achievements.append("🌟 First Clip Submitted")
        if total_videos >= 10:
            achievements.append("🔥 10+ Videos Submitted")
        if total_videos >= 50:
            achievements.append("⚡ 50+ Videos Submitted")
        if total_views >= 1_000_000:
            achievements.append("👑 1M+ Total Views")
        if total_views >= 5_000_000:
            achievements.append("💎 5M+ Total Views")
        if total_views >= 10_000_000:
            achievements.append("🏆 10M+ Total Views")
        if total_earned >= 100:
            achievements.append("💵 $100+ Earned")
        if total_earned >= 500:
            achievements.append("💰 $500+ Earned")

        if achievements:
            embed.add_field(
                name="═══ 🏆 ACHIEVEMENTS ═══",
                value="\n".join(achievements),
                inline=False
            )

        await interaction.followup.send(embed=embed)

    # ── LEADERBOARD ────────────────────────────────────
    @app_commands.command(name="leaderboard", description="View the campaign leaderboard")
    @app_commands.describe(
        campaign_id="Specific campaign (leave empty for global)",
        metric="Sort by metric",
    )
    @app_commands.choices(metric=[
        app_commands.Choice(name="Views", value="views"),
        app_commands.Choice(name="Likes", value="likes"),
        app_commands.Choice(name="Videos Submitted", value="videos"),
    ])
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        campaign_id: str = None,
        metric: app_commands.Choice[str] = None,
    ):
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            return  # Interaction expired before we could respond
        except Exception:
            return

        metric_value = metric.value if metric else "views"
        entries = await self.db.get_leaderboard(campaign_id, metric=metric_value, limit=10)

        if not entries:
            embed = discord.Embed(
                title="🏆 Leaderboard",
                description="No data available yet.",
                color=discord.Color.gold()
            )
            await interaction.followup.send(embed=embed)
            return

        # Determine rate for earnings
        rate = 10.0
        campaign_name = "Global"
        if campaign_id:
            campaign = await self.db.get_campaign(campaign_id)
            if campaign:
                rate = campaign.get('rate_per_10k_views', 10.0)
                campaign_name = campaign['name']

        embed = discord.Embed(
            title=f"🏆 LEADERBOARD: {campaign_name}",
            description=f"Sorted by: **{metric_value.title()}**",
            color=discord.Color.gold()
        )

        leaderboard_text = "```\n#   Clipper          Videos  Views       Earnings\n"
        leaderboard_text += "──  ──────────────── ─────── ──────────  ─────────\n"

        for i, entry in enumerate(entries, 1):
            # Get user display name
            try:
                member = interaction.guild.get_member(int(entry['discord_user_id']))
                display_name = member.display_name[:16] if member else f"User {entry['discord_user_id'][:8]}"
            except Exception:
                display_name = f"User {entry['discord_user_id'][:8]}"

            medal = medal_emoji(i)
            earned = calculate_earnings(entry['total_views'], rate)

            leaderboard_text += (
                f"{medal:3s} {display_name:16s} {entry['total_videos']:>7d}  "
                f"{format_number(entry['total_views']):>10s}  "
                f"{format_currency(earned):>9s}\n"
            )

        leaderboard_text += "```"
        embed.add_field(name="\u200b", value=leaderboard_text, inline=False)

        # Show caller's position
        all_entries = await self.db.get_leaderboard(campaign_id, metric=metric_value, limit=100)
        user_pos = None
        for i, entry in enumerate(all_entries, 1):
            if entry['discord_user_id'] == str(interaction.user.id):
                user_pos = i
                break

        if user_pos:
            embed.set_footer(text=f"Your Position: #{user_pos}")

        await interaction.followup.send(embed=embed)

    @leaderboard.autocomplete("campaign_id")
    async def leaderboard_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_all_campaigns()
            choices = [app_commands.Choice(name="Global (All Campaigns)", value="")]
            choices += [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ]
            return choices[:25]
        except discord.errors.NotFound:
            return []  # Interaction expired — autocomplete timeout
        except Exception:
            return []

    # ── CAMPAIGN STATISTICS ────────────────────────────
    @app_commands.command(name="campaign_statistics", description="View detailed statistics for a campaign")
    @app_commands.describe(campaign_id="Campaign to view stats for")
    async def campaign_statistics(self, interaction: discord.Interaction, campaign_id: str):
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.response.send_message(
                f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
            )
            return

        try:
            await interaction.response.defer()
        except (discord.errors.NotFound, Exception):
            return

        stats = await self.db.get_campaign_statistics(campaign_id)
        member_count = await self.db.get_campaign_member_count(campaign_id)
        rate = campaign.get('rate_per_10k_views', 10.0)
        total_views = stats.get('grand_total_views', 0)
        total_earned = calculate_earnings(total_views, rate)

        from utils.formatters import build_campaign_embed
        embed = build_campaign_embed(campaign, stats)
        embed.title = f"📊 Campaign Statistics: {campaign['name']}"

        embed.add_field(name="👥 Members", value=str(member_count), inline=True)
        embed.add_field(name="💰 Total Earned", value=format_currency(total_earned), inline=True)

        budget = campaign.get('budget')
        if budget:
            from utils.formatters import progress_bar
            pct = min(100, (total_earned / budget * 100)) if budget > 0 else 0
            embed.add_field(
                name="💰 Budget Progress",
                value=f"{progress_bar(total_earned, budget)} {pct:.1f}%",
                inline=False
            )

        # Platform breakdown
        breakdown = await self.db.get_campaign_platform_breakdown(campaign_id)
        if breakdown:
            plat_text = ""
            for plat in breakdown:
                emoji = platform_emoji(plat['platform'])
                pct = (plat['total_views'] / total_views * 100) if total_views > 0 else 0
                plat_text += f"{emoji} {plat['platform'].title()}: {format_number(plat['total_views'])} views ({pct:.1f}%)\n"
            embed.add_field(name="📱 Platform Breakdown", value=plat_text, inline=False)

        await interaction.followup.send(embed=embed)

    @campaign_statistics.autocomplete("campaign_id")
    async def stats_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_all_campaigns()
            return [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCommands(bot))
