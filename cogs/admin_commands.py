"""Admin commands: create, update, end, delete campaign."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from utils.permissions import admin_only
from utils.id_generator import generate_campaign_id
from utils.formatters import (
    format_currency, format_number, format_duration, format_timestamp,
    status_emoji, build_campaign_embed
)


class AdminCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    # ── CREATE CAMPAIGN ────────────────────────────────
    @app_commands.command(name="create_campaign", description="Create a new tracking campaign")
    @app_commands.describe(
        name="Campaign display name",
        duration_days="Campaign duration in days (default: unlimited)",
        budget="Total budget in USD (default: unlimited)",
        min_views_to_join="Minimum views required to join (default: 0)",
        max_views_cap="Maximum total views cap (default: unlimited)",
        rate_per_10k_views="Payment rate per 10K views",
        platforms="Platforms to track",
        auto_stop="Automatically stop when limits are reached"
    )
    @app_commands.choices(platforms=[
        app_commands.Choice(name="All Platforms", value="all"),
        app_commands.Choice(name="Instagram Only", value="instagram"),
        app_commands.Choice(name="TikTok Only", value="tiktok"),
        app_commands.Choice(name="Twitter/X Only", value="twitter"),
    ])
    @admin_only()
    async def create_campaign(
        self,
        interaction: discord.Interaction,
        name: str,
        duration_days: int = None,
        budget: float = None,
        min_views_to_join: int = 0,
        max_views_cap: int = None,
        rate_per_10k_views: float = None,
        platforms: app_commands.Choice[str] = None,
        auto_stop: bool = True
    ):
        await interaction.response.defer()

        # Get default rate from settings if not specified
        if rate_per_10k_views is None:
            default_rate = await self.db.get_setting("default_rate_per_10k")
            try:
                rate_per_10k_views = float(default_rate) if default_rate else 10.00
            except ValueError:
                rate_per_10k_views = 10.00

        platform_value = platforms.value if platforms else "all"
        campaign_id = generate_campaign_id()

        # Ensure unique ID
        while await self.db.get_campaign(campaign_id):
            campaign_id = generate_campaign_id()

        success = await self.db.create_campaign(
            campaign_id=campaign_id,
            name=name,
            created_by=str(interaction.user.id),
            duration_days=duration_days,
            budget=budget,
            min_views_to_join=min_views_to_join,
            max_views_cap=max_views_cap,
            rate_per_10k_views=rate_per_10k_views,
            platforms=platform_value,
            auto_stop=auto_stop,
        )

        if success:
            campaign = await self.db.get_campaign(campaign_id)
            embed = build_campaign_embed(campaign)
            embed.title = "✅ Campaign Created"
            embed.add_field(
                name="📢 Share with clippers",
                value=f"`/join {campaign_id}`",
                inline=False
            )
            await interaction.followup.send(embed=embed)

            # Send notification
            channel_id = await self.db.get_setting("notification_channel_id")
            if channel_id:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        notif_embed = discord.Embed(
                            title="📋 New Campaign Created",
                            description=f"**{name}** (`{campaign_id}`) by <@{interaction.user.id}>",
                            color=discord.Color.green()
                        )
                        await channel.send(embed=notif_embed)
                except Exception:
                    pass
        else:
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to create campaign. Please try again.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── UPDATE CAMPAIGN ────────────────────────────────
    @app_commands.command(name="update_campaign", description="Update an existing campaign's settings")
    @app_commands.describe(
        campaign_id="Campaign to update",
        name="New campaign name",
        duration_days="New duration in days",
        budget="New budget in USD",
        min_views_to_join="New minimum views to join",
        max_views_cap="New max views cap",
        rate_per_10k_views="New rate per 10K views",
        status="New campaign status"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="Active", value="active"),
        app_commands.Choice(name="Paused", value="paused"),
        app_commands.Choice(name="Completed", value="completed"),
    ])
    @admin_only()
    async def update_campaign(
        self,
        interaction: discord.Interaction,
        campaign_id: str,
        name: str = None,
        duration_days: int = None,
        budget: float = None,
        min_views_to_join: int = None,
        max_views_cap: int = None,
        rate_per_10k_views: float = None,
        status: app_commands.Choice[str] = None,
    ):
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.response.send_message(
                f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
            )
            return

        kwargs = {}
        if name is not None:
            kwargs['name'] = name
        if duration_days is not None:
            kwargs['duration_days'] = duration_days
        if budget is not None:
            kwargs['budget'] = budget
        if min_views_to_join is not None:
            kwargs['min_views_to_join'] = min_views_to_join
        if max_views_cap is not None:
            kwargs['max_views_cap'] = max_views_cap
        if rate_per_10k_views is not None:
            kwargs['rate_per_10k_views'] = rate_per_10k_views
        if status is not None:
            kwargs['status'] = status.value

        if not kwargs:
            await interaction.response.send_message(
                "⚠️ No changes specified.", ephemeral=True
            )
            return

        success = await self.db.update_campaign(campaign_id, **kwargs)
        if success:
            updated_campaign = await self.db.get_campaign(campaign_id)
            embed = build_campaign_embed(updated_campaign)
            embed.title = "✅ Campaign Updated"
            changes = ", ".join(f"**{k}**" for k in kwargs.keys())
            embed.description = f"Updated: {changes}"
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(
                "❌ Failed to update campaign.", ephemeral=True
            )

    @update_campaign.autocomplete("campaign_id")
    async def campaign_autocomplete(self, interaction: discord.Interaction, current: str):
        campaigns = await self.db.get_all_campaigns()
        return [
            app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
            for c in campaigns
            if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
        ][:25]

    # ── END CAMPAIGN ───────────────────────────────────
    @app_commands.command(name="end_campaign", description="Manually end a campaign")
    @app_commands.describe(
        campaign_id="Campaign to end",
        reason="Reason for ending the campaign"
    )
    @admin_only()
    async def end_campaign(
        self,
        interaction: discord.Interaction,
        campaign_id: str,
        reason: str = "Manually ended by admin"
    ):
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.response.send_message(
                f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
            )
            return

        if campaign['status'] == 'completed':
            await interaction.response.send_message(
                f"⚠️ Campaign `{campaign_id}` is already completed.", ephemeral=True
            )
            return

        await interaction.response.defer()
        await self.db.update_campaign_status(campaign_id, 'completed', reason)

        # Get final stats
        stats = await self.db.get_campaign_statistics(campaign_id)
        member_count = await self.db.get_campaign_member_count(campaign_id)
        video_count = await self.db.get_campaign_video_count(campaign_id)
        rate = campaign.get('rate_per_10k_views', 10.0)
        total_views = stats.get('grand_total_views', 0)

        from campaign.payment_calculator import calculate_earnings
        total_earned = calculate_earnings(total_views, rate)

        embed = discord.Embed(
            title=f"🏁 CAMPAIGN ENDED: {campaign['name']}",
            description=f"**ID:** `{campaign_id}`\n**Reason:** {reason}",
            color=discord.Color.red()
        )

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

        embed.add_field(name="💵 Rate", value=f"{format_currency(rate)} per 10K views", inline=True)

        # Leaderboard
        leaderboard = await self.db.get_leaderboard(campaign_id, metric="views", limit=10)
        if leaderboard:
            lb_text = ""
            medals = {0: "🥇", 1: "🥈", 2: "🥉"}
            for i, entry in enumerate(leaderboard):
                medal = medals.get(i, f"#{i + 1}")
                earned = calculate_earnings(entry['total_views'], rate)
                lb_text += (
                    f"{medal} <@{entry['discord_user_id']}>\n"
                    f"   Videos: {entry['total_videos']} │ "
                    f"Views: {format_number(entry['total_views'])} │ "
                    f"Earned: {format_currency(earned)}\n"
                )
            embed.add_field(name="💰 PAYMENT BREAKDOWN", value=lb_text, inline=False)

        # Platform breakdown
        breakdown = await self.db.get_campaign_platform_breakdown(campaign_id)
        if breakdown:
            plat_emojis = {"instagram": "📷", "tiktok": "🎵", "twitter": "🐦"}
            plat_text = ""
            for plat in breakdown:
                emoji = plat_emojis.get(plat['platform'], "🌐")
                pct = (plat['total_views'] / total_views * 100) if total_views > 0 else 0
                plat_text += f"{emoji} {plat['platform'].title()}: {format_number(plat['total_views'])} views ({pct:.1f}%)\n"
            embed.add_field(name="📱 PLATFORM BREAKDOWN", value=plat_text, inline=False)

        await interaction.followup.send(embed=embed)

    @end_campaign.autocomplete("campaign_id")
    async def end_campaign_autocomplete(self, interaction: discord.Interaction, current: str):
        campaigns = await self.db.get_active_campaigns()
        return [
            app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
            for c in campaigns
            if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
        ][:25]

    # ── DELETE CAMPAIGN ────────────────────────────────
    @app_commands.command(name="delete_campaign", description="Permanently delete a campaign")
    @app_commands.describe(campaign_id="Campaign to delete")
    @admin_only()
    async def delete_campaign(self, interaction: discord.Interaction, campaign_id: str):
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.response.send_message(
                f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
            )
            return

        success = await self.db.delete_campaign(campaign_id)
        if success:
            embed = discord.Embed(
                title="🗑️ Campaign Deleted",
                description=f"Campaign **{campaign['name']}** (`{campaign_id}`) has been permanently deleted.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(
                "❌ Failed to delete campaign.", ephemeral=True
            )

    @delete_campaign.autocomplete("campaign_id")
    async def delete_campaign_autocomplete(self, interaction: discord.Interaction, current: str):
        campaigns = await self.db.get_all_campaigns()
        return [
            app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
            for c in campaigns
            if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCommands(bot))
