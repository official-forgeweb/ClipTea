"""Submission commands: submit, my_videos, video_details, delete_video."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from campaign.manager import CampaignManager
from campaign.payment_calculator import calculate_earnings
from utils.formatters import (
    format_number, format_currency, format_timestamp, format_date, platform_emoji
)
from utils.validators import detect_platform, is_valid_video_url, extract_video_id, normalize_url


class SubmissionCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.campaign_mgr = CampaignManager(self.db)
        self._initialized = False

    async def _ensure_initialized(self):
        if not self._initialized:
            await self.campaign_mgr.initialize()
            self._initialized = True

    # ── SUBMIT VIDEO ───────────────────────────────────
    @app_commands.command(name="submit", description="Submit a video for campaign tracking")
    @app_commands.describe(
        campaign_id="Campaign to submit to",
        video_url="URL of your posted video/reel/clip"
    )
    async def submit(
        self,
        interaction: discord.Interaction,
        campaign_id: str,
        video_url: str
    ):
        await interaction.response.defer()

        # STEP 1: Validate URL
        video_url = normalize_url(video_url)
        platform = detect_platform(video_url)

        if not platform:
            embed = discord.Embed(
                title="❌ Invalid URL",
                description=(
                    "Could not detect platform from URL.\n"
                    "Supported formats:\n"
                    "• `instagram.com/reel/...` or `instagram.com/p/...`\n"
                    "• `tiktok.com/@.../video/...`\n"
                    "• `x.com/.../status/...`"
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # STEP 2: Check campaign exists and is active
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.followup.send(
                f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
            )
            return

        if campaign['status'] != 'active':
            await interaction.followup.send(
                f"❌ Campaign `{campaign_id}` is not active.", ephemeral=True
            )
            return

        # Check platform compatibility
        campaign_platforms = campaign.get('platforms', 'all')
        if campaign_platforms != 'all' and platform != campaign_platforms:
            await interaction.followup.send(
                f"❌ This campaign only accepts **{campaign_platforms.title()}** videos, "
                f"but your URL is from **{platform.title()}**.",
                ephemeral=True
            )
            return

        # STEP 3: Check linked account
        user_id = str(interaction.user.id)
        account = await self.db.get_user_account(user_id, platform)
        if not account:
            await interaction.followup.send(
                f"❌ You haven't linked your **{platform.title()}** account.\n"
                f"Use `/link_account` first.",
                ephemeral=True
            )
            return

        # STEP 4: Check membership
        if not await self.db.is_campaign_member(campaign_id, user_id):
            await interaction.followup.send(
                f"❌ You haven't joined this campaign.\nUse `/join {campaign_id}` first.",
                ephemeral=True
            )
            return

        # STEP 5: Check duplicates
        existing = await self.db.get_submitted_video_by_url(campaign_id, video_url)
        if existing:
            await interaction.followup.send(
                f"⚠️ This video was already submitted on {format_date(existing.get('submitted_at', ''))}.",
                ephemeral=True
            )
            return

        # STEP 6: Check campaign limits
        stats = await self.db.get_campaign_statistics(campaign_id)
        budget = campaign.get('budget')
        if budget:
            total_views = stats.get('grand_total_views', 0)
            rate = campaign.get('rate_per_10k_views', 10.0)
            earned = calculate_earnings(total_views, rate)
            if earned >= budget:
                await interaction.followup.send(
                    "❌ This campaign's budget has been exhausted.", ephemeral=True
                )
                return

        max_views = campaign.get('max_views_cap')
        if max_views and stats.get('grand_total_views', 0) >= max_views:
            await interaction.followup.send(
                "❌ This campaign has reached its maximum views cap.", ephemeral=True
            )
            return

        # STEP 7: Scrape the video
        progress_msg = await interaction.followup.send(
            embed=discord.Embed(
                title="⏳ Scraping Video...",
                description=f"Fetching data from {platform.title()}...\nThis may take a moment.",
                color=discord.Color.gold()
            ),
            wait=True
        )

        await self._ensure_initialized()
        video_data = await self.campaign_mgr.scrape_video(video_url, platform)

        if not video_data:
            await progress_msg.edit(
                embed=discord.Embed(
                    title="❌ Scrape Failed",
                    description="Could not fetch video data. The URL may be invalid or the post may be private.",
                    color=discord.Color.red()
                )
            )
            return

        # STEP 8: Verify ownership
        author = video_data.get('author_username', '').lower().strip()
        linked_username = account['platform_username'].lower().strip()

        if author and author != linked_username:
            await progress_msg.edit(
                embed=discord.Embed(
                    title="❌ Ownership Verification Failed",
                    description=(
                        f"This video was posted by **@{video_data.get('author_username', 'unknown')}**, "
                        f"but your linked {platform.title()} account is **@{account['platform_username']}**.\n\n"
                        f"You can only submit your own videos."
                    ),
                    color=discord.Color.red()
                )
            )
            return

        # STEP 9: Save to database
        video_id_str = extract_video_id(video_url, platform)
        record_id = await self.db.submit_video(
            campaign_id=campaign_id,
            discord_user_id=user_id,
            platform=platform,
            video_url=video_url,
            video_id=video_id_str,
            author_username=video_data.get('author_username', linked_username),
            caption=video_data.get('caption', ''),
            is_verified=bool(author and author == linked_username)
        )

        if not record_id:
            await progress_msg.edit(
                embed=discord.Embed(
                    title="⚠️ Already Submitted",
                    description="This video was already submitted to this campaign.",
                    color=discord.Color.orange()
                )
            )
            return

        # Save initial metrics
        await self.db.save_metric_snapshot(
            video_id=record_id,
            views=video_data.get('views', 0),
            likes=video_data.get('likes', 0),
            comments=video_data.get('comments', 0),
            shares=video_data.get('shares', 0),
        )

        # STEP 10: Confirmation embed
        verified_text = "✅ Verified" if author and author == linked_username else "⏳ Pending"

        embed = discord.Embed(
            title="✅ Video Submitted Successfully",
            color=discord.Color.green()
        )
        embed.add_field(
            name=f"{platform_emoji(platform)} Video",
            value=video_url,
            inline=False
        )
        embed.add_field(name="📊 Campaign", value=campaign['name'], inline=True)
        embed.add_field(
            name="👤 Author",
            value=f"@{video_data.get('author_username', linked_username)} {verified_text}",
            inline=True
        )

        embed.add_field(name="━━━ Current Metrics ━━━", value="\u200b", inline=False)
        embed.add_field(name="👁️ Views", value=format_number(video_data.get('views', 0)), inline=True)
        embed.add_field(name="❤️ Likes", value=format_number(video_data.get('likes', 0)), inline=True)
        embed.add_field(name="💬 Comments", value=format_number(video_data.get('comments', 0)), inline=True)

        embed.add_field(
            name="⏱️ Tracking",
            value="Metrics will be tracked automatically.\nUse `/stats` to check progress.",
            inline=False
        )

        await progress_msg.edit(embed=embed)

        # Send notification
        channel_id = await self.db.get_setting("notification_channel_id")
        if channel_id:
            try:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    notif = discord.Embed(
                        title="📹 New Video Submitted",
                        description=(
                            f"<@{user_id}> submitted a video to **{campaign['name']}**\n"
                            f"{platform_emoji(platform)} {video_url}"
                        ),
                        color=discord.Color.blue()
                    )
                    await channel.send(embed=notif)
            except Exception:
                pass

        await self.db.log_notification(
            campaign_id=campaign_id,
            notif_type="submit",
            message=f"{interaction.user} submitted {video_url}"
        )

    @submit.autocomplete("campaign_id")
    async def submit_autocomplete(self, interaction: discord.Interaction, current: str):
        user_campaigns = await self.db.get_user_campaigns(str(interaction.user.id))
        return [
            app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
            for c in user_campaigns
            if c.get('member_status') == 'active' and c.get('status') == 'active'
            and (current.lower() in c['name'].lower() or current.lower() in c['id'].lower())
        ][:25]

    # ── MY VIDEOS ──────────────────────────────────────
    @app_commands.command(name="my_videos", description="View your submitted videos")
    @app_commands.describe(campaign_id="Filter by campaign (optional)")
    async def my_videos(
        self,
        interaction: discord.Interaction,
        campaign_id: str = None
    ):
        videos = await self.db.get_user_videos(str(interaction.user.id), campaign_id)

        if not videos:
            embed = discord.Embed(
                title="📹 My Videos",
                description="You haven't submitted any videos yet.\nUse `/submit` to submit a video!",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            title="📹 My Submitted Videos",
            color=discord.Color.blue()
        )

        for v in videos[:10]:
            metrics = await self.db.get_latest_metrics(v['id'])
            views = metrics.get('views', 0) if metrics else 0
            likes = metrics.get('likes', 0) if metrics else 0

            rate_campaign = await self.db.get_campaign(v['campaign_id'])
            rate = rate_campaign.get('rate_per_10k_views', 10.0) if rate_campaign else 10.0
            earned = calculate_earnings(views, rate)

            embed.add_field(
                name=f"{platform_emoji(v['platform'])} {v.get('campaign_name', v['campaign_id'])}",
                value=(
                    f"🔗 [Video Link]({v['video_url']})\n"
                    f"👁️ {format_number(views)} views │ "
                    f"❤️ {format_number(likes)} likes │ "
                    f"💵 {format_currency(earned)}\n"
                    f"📅 Submitted: {format_date(v.get('submitted_at', ''))}"
                ),
                inline=False
            )

        if len(videos) > 10:
            embed.set_footer(text=f"Showing 10 of {len(videos)} videos")

        await interaction.response.send_message(embed=embed)

    @my_videos.autocomplete("campaign_id")
    async def my_videos_autocomplete(self, interaction: discord.Interaction, current: str):
        user_campaigns = await self.db.get_user_campaigns(str(interaction.user.id))
        return [
            app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
            for c in user_campaigns
            if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
        ][:25]

    # ── VIDEO DETAILS ──────────────────────────────────
    @app_commands.command(name="video_details", description="View detailed metrics for a specific video")
    @app_commands.describe(video_url="URL of the submitted video")
    async def video_details(self, interaction: discord.Interaction, video_url: str):
        video_url = normalize_url(video_url)
        video = await self.db.get_video_by_url(video_url)

        if not video:
            await interaction.response.send_message(
                "❌ Video not found. Make sure the URL was submitted to a campaign.",
                ephemeral=True
            )
            return

        history = await self.db.get_metric_history(video['id'])

        campaign = await self.db.get_campaign(video['campaign_id'])
        rate = campaign.get('rate_per_10k_views', 10.0) if campaign else 10.0

        latest = history[-1] if history else {}
        views = latest.get('views', 0)
        earned = calculate_earnings(views, rate)

        embed = discord.Embed(
            title="📹 VIDEO DETAILS",
            color=discord.Color.purple()
        )
        embed.add_field(name="🔗 URL", value=video_url, inline=False)
        embed.add_field(name="📊 Campaign", value=video.get('campaign_name', video['campaign_id']), inline=True)
        embed.add_field(name="📅 Submitted", value=format_date(video.get('submitted_at', '')), inline=True)
        embed.add_field(name="👤 Author", value=f"@{video.get('author_username', 'N/A')}", inline=True)

        # Current metrics
        embed.add_field(name="━━━ Current Metrics ━━━", value="\u200b", inline=False)
        embed.add_field(name="👁️ Views", value=format_number(views), inline=True)
        embed.add_field(name="❤️ Likes", value=format_number(latest.get('likes', 0)), inline=True)
        embed.add_field(name="💬 Comments", value=format_number(latest.get('comments', 0)), inline=True)
        embed.add_field(name="💰 Earnings", value=format_currency(earned), inline=True)

        # Growth history
        if len(history) > 1:
            history_text = "```\nDate         Views       Likes    Comments\n"
            for h in history[-7:]:  # Last 7 snapshots
                date = format_date(h.get('fetched_at', ''))[:10]
                history_text += (
                    f"{date:12s} {format_number(h.get('views', 0)):>10s} "
                    f"{format_number(h.get('likes', 0)):>8s} "
                    f"{format_number(h.get('comments', 0)):>8s}\n"
                )
            history_text += "```"
            embed.add_field(name="📈 Growth History", value=history_text, inline=False)

            # Daily avg growth
            if len(history) >= 2:
                first_views = history[0].get('views', 0)
                last_views = history[-1].get('views', 0)
                days = max(1, len(history) - 1)
                daily_avg = (last_views - first_views) / days
                embed.add_field(
                    name="📊 Avg Daily Growth",
                    value=f"+{format_number(int(daily_avg))} views/day",
                    inline=True
                )

        await interaction.response.send_message(embed=embed)

    # ── DELETE VIDEO ───────────────────────────────────
    @app_commands.command(name="delete_video", description="Delete a submitted video from tracking")
    @app_commands.describe(
        video_url="URL of the video to delete",
        reason="Reason for deletion (optional)"
    )
    async def delete_video(
        self,
        interaction: discord.Interaction,
        video_url: str,
        reason: str = "Deleted by user"
    ):
        video_url = normalize_url(video_url)
        video = await self.db.get_video_by_url(video_url)

        if not video:
            await interaction.response.send_message(
                "❌ Video not found.", ephemeral=True
            )
            return

        # Check permission: must be video owner or admin
        from utils.permissions import is_admin
        user_is_admin = await is_admin(interaction)
        is_owner = video['discord_user_id'] == str(interaction.user.id)

        if not is_owner and not user_is_admin:
            await interaction.response.send_message(
                "❌ You can only delete your own videos.", ephemeral=True
            )
            return

        success = await self.db.delete_video(video_url)
        if success:
            embed = discord.Embed(
                title="🗑️ Video Deleted",
                description=f"Video has been removed from tracking.\n**Reason:** {reason}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(
                "❌ Failed to delete video.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(SubmissionCommands(bot))
