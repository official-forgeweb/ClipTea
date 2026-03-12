"""Stats commands: stats, leaderboard, campaign_statistics."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from campaign.payment_calculator import calculate_earnings
from utils.formatters import (
    format_number, format_compact, format_currency, format_timestamp,
    format_date, days_ago, platform_emoji, status_emoji, medal_emoji,
    build_campaign_embed
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
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        # Admin check if viewing someone else
        if user and user.id != interaction.user.id:
            if not await is_admin(interaction):
                try:
                    await interaction.followup.send(
                        "❌ Only admins can view other users' stats.", ephemeral=True
                    )
                except:
                    pass
                return
            target_user = user
        else:
            target_user = interaction.user
    
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
            title="📊 CLIPPER PERFORMANCE PROFILE",
            description=f"Reviewing performance for **{target_user.display_name}**",
            color=discord.Color.from_rgb(88, 101, 242) # Discord blurple
        )

        embed.set_thumbnail(url=target_user.display_avatar.url)

        # Basic Info
        started_text = f"{format_date(first_sub)} ({days_ago(first_sub)})" if first_sub else "Not started yet"
        embed.add_field(name="👤 Clipper", value=f"**{target_user.mention}**", inline=True)
        embed.add_field(name="📅 Joined", value=started_text, inline=True)
        embed.add_field(name="🏅 Status", value=self._get_performance_rank(all_stats.get('total_views', 0)), inline=True)

        # Linked accounts
        embed.add_field(name="🔗 LINKED ACCOUNTS", value="\u200b", inline=False)
        all_platforms = {"instagram": None, "tiktok": None, "twitter": None}
        for acc in accounts:
            all_platforms[acc['platform']] = acc

        for plat, acc in all_platforms.items():
            emoji = platform_emoji(plat)
            if acc:
                status = "✅" if acc.get('verified') else "⏳"
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value=f"[`@{acc['platform_username']}`](https://{plat}.com/{acc['platform_username']}) {status}",
                    inline=True
                )
            else:
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value="*Not linked*",
                    inline=True
                )

        # All-time stats
        total_views = all_stats.get('total_views', 0)
        total_videos = all_stats.get('total_videos', 0)
        total_likes = all_stats.get('total_likes', 0)
        total_comments = all_stats.get('total_comments', 0)
        
        avg_views = total_views / total_videos if total_videos > 0 else 0
        engagement_rate = (total_likes / total_views * 100) if total_views > 0 else 0

        # Calculate total earnings across all campaigns
        total_earned = 0
        for c in user_campaigns:
            c_stats = await self.db.get_user_campaign_stats(c['id'], target_id)
            rate = c.get('rate_per_10k_views', 10.0)
            total_earned += calculate_earnings(c_stats.get('total_views', 0), rate)

        embed.add_field(name="📈 GLOBAL STATISTICS", value="\u200b", inline=False)
        embed.add_field(name="🎬 Content", value=f"**{format_number(total_videos)}** videos", inline=True)
        embed.add_field(name="👁️ reach", value=f"**{format_compact(total_views)}** views", inline=True)
        embed.add_field(name="💰 Revenue", value=f"**{format_currency(total_earned)}**", inline=True)
        
        embed.add_field(name="❤️ Engagement", value=f"**{engagement_rate:.1f}%** rate", inline=True)
        embed.add_field(name="📊 Average", value=f"**{format_compact(avg_views)}** /vid", inline=True)
        embed.add_field(name="💬 Feedback", value=f"**{format_number(total_comments)}** comments", inline=True)

        # Campaign history
        if user_campaigns:
            embed.add_field(name="📋 CAMPAIGN ACTIVITY (Recent)", value="\u200b", inline=False)

            for c in user_campaigns[:3]: # Show top 3 most recent
                c_stats = await self.db.get_user_campaign_stats(c['id'], target_id)
                rate = c.get('rate_per_10k_views', 10.0)
                earned = calculate_earnings(c_stats.get('total_views', 0), rate)
                status = status_emoji(c.get('status', 'active'))

                embed.add_field(
                    name=f"{status} {c['name']}",
                    value=(
                        f"📹 {c_stats.get('total_videos', 0)} vids │ 👁️ {format_compact(c_stats.get('total_views', 0))} │ 💵 **{format_currency(earned)}**\n"
                    ),
                    inline=False
                )

        # Achievements (as medals)
        ach_emojis = []
        if total_videos >= 1: ach_emojis.append("🥉")
        if total_videos >= 10: ach_emojis.append("🥈")
        if total_videos >= 50: ach_emojis.append("🥇")
        if total_views >= 1_000_000: ach_emojis.append("🔥")
        if total_views >= 5_000_000: ach_emojis.append("⚡")
        if total_views >= 10_000_000: ach_emojis.append("👑")
        if total_earned >= 100: ach_emojis.append("💵")
        if total_earned >= 500: ach_emojis.append("💰")

        if ach_emojis:
            embed.add_field(
                name="📅 MILESTONES",
                value=" ".join(ach_emojis),
                inline=False
            )
    
        try:
            await interaction.followup.send(embed=embed)
        except:
            pass

    def _get_performance_rank(self, views: int) -> str:
        if views >= 10_000_000: return "💎 Diamond"
        if views >= 5_000_000: return "👑 Platinum"
        if views >= 1_000_000: return "🌟 Gold"
        if views >= 100_000: return "🔥 Silver"
        if views >= 10_000: return "⚡ Bronze"
        return "🌱 Novice"

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
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
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

        campaign_name = "Global"
        if campaign_id:
            campaign = await self.db.get_campaign(campaign_id)
            if campaign:
                campaign_name = campaign['name']

        # ── Resolve usernames ──────────────────────────
        resolved_names = {}
        for entry in entries:
            uid = entry['discord_user_id']
            name = None
            # Try guild member cache first
            if interaction.guild:
                member = interaction.guild.get_member(int(uid))
                if member:
                    name = member.display_name
            # Fallback: fetch from Discord API
            if not name:
                try:
                    user = await self.bot.fetch_user(int(uid))
                    name = user.display_name if user else uid
                except Exception:
                    name = uid
            resolved_names[uid] = name

        # ── Build table ────────────────────────────────
        # Column headers based on metric
        if metric_value == "videos":
            col_headers = ("#", "Clipper", "Videos", "Views", "Likes")
        elif metric_value == "likes":
            col_headers = ("#", "Clipper", "Likes", "Views", "Videos")
        else:
            col_headers = ("#", "Clipper", "Views", "Videos", "Likes")

        # Build rows
        rows = []
        for i, entry in enumerate(entries, 1):
            uid = entry['discord_user_id']
            name = resolved_names.get(uid, uid)[:14]  # Truncate long names
            views = format_compact(entry['total_views'])
            likes = format_compact(entry['total_likes']) if 'total_likes' in entry else "0"
            videos = str(entry['total_videos'])

            if metric_value == "videos":
                rows.append((medal_emoji(i), name, videos, views, likes))
            elif metric_value == "likes":
                rows.append((medal_emoji(i), name, likes, views, videos))
            else:
                rows.append((medal_emoji(i), name, views, videos, likes))

        # Calculate column widths
        col_widths = [
            max(len(str(col_headers[0])), max(len(str(r[0])) for r in rows)),
            max(len(col_headers[1]), max(len(r[1]) for r in rows)),
            max(len(col_headers[2]), max(len(r[2]) for r in rows)),
            max(len(col_headers[3]), max(len(r[3]) for r in rows)),
            max(len(col_headers[4]), max(len(r[4]) for r in rows)),
        ]

        # Build the table string
        header = (
            f"{col_headers[0]:<{col_widths[0]}}  "
            f"{col_headers[1]:<{col_widths[1]}}  "
            f"{col_headers[2]:>{col_widths[2]}}  "
            f"{col_headers[3]:>{col_widths[3]}}  "
            f"{col_headers[4]:>{col_widths[4]}}"
        )
        separator = "─" * len(header)

        table = f"```\n{header}\n{separator}\n"
        for row in rows:
            table += (
                f"{row[0]:<{col_widths[0]}}  "
                f"{row[1]:<{col_widths[1]}}  "
                f"{row[2]:>{col_widths[2]}}  "
                f"{row[3]:>{col_widths[3]}}  "
                f"{row[4]:>{col_widths[4]}}\n"
            )
        table += "```"

        embed = discord.Embed(
            title=f"🏆 LEADERBOARD — {campaign_name}",
            description=f"Sorted by: **{metric_value.title()}**\n{table}",
            color=discord.Color.gold()
        )

        # Find user's position
        all_entries = await self.db.get_leaderboard(campaign_id, metric=metric_value, limit=100)
        user_pos = None
        for i, entry in enumerate(all_entries, 1):
            if entry['discord_user_id'] == str(interaction.user.id):
                user_pos = i
                break

        if user_pos:
            embed.set_footer(text=f"📍 Your Position: #{user_pos}")
    
        try:
            await interaction.followup.send(embed=embed)
        except:
            pass


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
        except:
            return []

    # ── CAMPAIGN STATISTICS ────────────────────────────
    @app_commands.command(name="campaign_statistics", description="View detailed statistics for a campaign")
    @app_commands.describe(campaign_id="Campaign to view stats for")
    async def campaign_statistics(self, interaction: discord.Interaction, campaign_id: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            try:
                await interaction.followup.send(
                    f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
                )
            except:
                pass
            return

        stats = await self.db.get_campaign_statistics(campaign_id)
        member_count = await self.db.get_campaign_member_count(campaign_id)
        rate = campaign.get('rate_per_10k_views', 10.0)
        total_views = stats.get('grand_total_views', 0)
        total_earned = calculate_earnings(total_views, rate)

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

        breakdown = await self.db.get_campaign_platform_breakdown(campaign_id)
        if breakdown:
            plat_text = ""
            for plat in breakdown:
                emoji = platform_emoji(plat['platform'])
                pct = (plat['total_views'] / total_views * 100) if total_views > 0 else 0
                plat_text += f"{emoji} {plat['platform'].title()}: {format_number(plat['total_views'])} views ({pct:.1f}%)\n"
            embed.add_field(name="📱 Platform Breakdown", value=plat_text, inline=False)
    
        try:
            await interaction.followup.send(embed=embed)
        except:
            pass

    @campaign_statistics.autocomplete("campaign_id")
    async def stats_campaign_autocomplete(self, interaction: discord.Interaction, current: str):
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
