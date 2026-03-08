"""Submission commands: submit, my_videos, video_details, delete_video."""
import discord
import asyncio
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from database.manager import DatabaseManager
from campaign.manager import CampaignManager
from campaign.payment_calculator import calculate_earnings
from utils.formatters import (
    format_number, format_currency, format_timestamp, format_date, platform_emoji
)
from utils.platform_detector import (
    detect_platform, is_valid_video_url, extract_video_id, 
    normalize_url, get_platform_color
)
from utils.permissions import is_admin


def check_video_validity(posted_at_str: str) -> dict:
    """
    Check if video is within 24-hour window.
    posted_at_str format: "2026-03-04T17:15:46.000Z"
    """
    if not posted_at_str:
        return {"valid": True, "message": "No timestamp available"}
        
    try:
        if "Z" in posted_at_str:
            posted_at = datetime.fromisoformat(posted_at_str.replace("Z", "+00:00"))
        else:
            posted_at = datetime.fromisoformat(posted_at_str)
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)
    except Exception:
        return {"valid": True, "message": "Invalid timestamp format"}
        
    now = datetime.now(timezone.utc)
    age = now - posted_at
    
    if age > timedelta(hours=24):
        return {
            "valid": False,
            "is_final": True,
            "remaining": "0h 0m",
            "status": "FINAL",
            "message": "❌ This video was posted more than 24 hours ago and cannot be submitted."
        }
    
    remaining = timedelta(hours=24) - age
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    
    return {
        "valid": True,
        "is_final": False,
        "remaining": f"{hours}h {minutes}m",
        "status": "TRACKING",
        "expires_at": (posted_at + timedelta(hours=24)).isoformat()
    }


class SubmissionCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.campaign_mgr = CampaignManager(self.db)
        self._initialized = False

    async def _ensure_initialized(self):
        if not self._initialized:
            await self.campaign_mgr.initialize()
            from services.unified_scraper import UnifiedScraper
            self.scraper = UnifiedScraper(self.db)
            self._initialized = True

    # ── SUBMIT VIDEO ───────────────────────────────────
    @app_commands.command(name="submit", description="Submit video URL(s) for campaign tracking")
    @app_commands.describe(
        campaign_id="Campaign to submit to",
        video_urls="Video URL(s) — separate multiple with commas (max 10)"
    )
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id)
    async def submit(
        self,
        interaction: discord.Interaction,
        campaign_id: str,
        video_urls: str
    ):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        # STEP 1: Process URL list
        urls = [u.strip() for u in video_urls.split(",") if u.strip()]
        if not urls:
            await interaction.followup.send("❌ No URLs provided.", ephemeral=True)
            return
            
        if len(urls) > 10:
            await interaction.followup.send(f"❌ Maximum 10 videos per submission. You sent {len(urls)}.", ephemeral=True)
            return

        # STEP 2: Check campaign exists and is active
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.followup.send(f"❌ Campaign `{campaign_id}` not found.", ephemeral=True)
            return

        if campaign['status'] != 'active':
            await interaction.followup.send(f"❌ Campaign `{campaign_id}` is not active.", ephemeral=True)
            return

        # STEP 3: Check membership
        user_id = str(interaction.user.id)
        if not await self.db.is_campaign_member(campaign_id, user_id):
            await interaction.followup.send(f"❌ You haven't joined this campaign.\nUse `/join {campaign_id}` first.", ephemeral=True)
            return

        # Prepare results
        results = []
        progress_embed = discord.Embed(
            title=f"⏳ Processing 0/{len(urls)} videos...",
            color=discord.Color.gold()
        )
        try:
            progress_msg = await interaction.followup.send(embed=progress_embed, ephemeral=True)
        except:
            return

        await self._ensure_initialized()
        
        for i, url in enumerate(urls):
            # Update progress
            current_url_display = url[:50] + ("..." if len(url) > 50 else "")
            progress_embed.title = f"⏳ Processing {i+1}/{len(urls)} videos..."
            progress_embed.description = f"Current: {current_url_display}"
            try:
                await progress_msg.edit(embed=progress_embed)
            except:
                pass

            # Validate each URL
            norm_url = normalize_url(url)
            platform = detect_platform(norm_url)
            
            if not platform:
                results.append(f"❌ `{url[:30]}...` — Invalid URL")
                continue

            # Check platform compatibility
            campaign_platforms = campaign.get('platforms', 'all')
            if campaign_platforms != 'all' and platform != campaign_platforms:
                results.append(f"❌ `{url[:30]}...` — Wrong platform (only {campaign_platforms})")
                continue

            # Check linked account
            account = await self.db.get_user_account(user_id, platform)
            if not account:
                results.append(f"❌ `{url[:30]}...` — Link {platform.title()} first")
                continue
                
            if not account.get('verified'):
                results.append(f"❌ `{url[:30]}...` — Account @{account['platform_username']} is NOT verified")
                continue

            # Check duplicates (same campaign + url)
            existing = await self.db.get_submitted_video_by_url(campaign_id, norm_url)
            if existing:
                results.append(f"❌ `{url[:30]}...` — Already submitted here")
                continue
                
            # Check global duplicate (different campaign)
            global_existing = await self.db.get_video_by_url(norm_url)
            if global_existing and global_existing['campaign_id'] != campaign_id:
                # We allow it but note it in results
                dup_notice = f" (Note: already in {global_existing['campaign_id']})"
            else:
                dup_notice = ""

            # Scrape
            try:
                video_data = await self.scraper.get_video_metrics(norm_url, platform=platform)
            except Exception as e:
                results.append(f"❌ `{url[:30]}...` — Scrape failed ({str(e)[:50]})")
                continue

            if not video_data:
                results.append(f"❌ `{url[:30]}...` — Scrape failed")
                continue

            # Check 24-hour validity
            validity = check_video_validity(video_data.get('posted_at'))
            if not validity['valid']:
                results.append(f"❌ `{url[:30]}...` — Posted >24h ago")
                continue

            # Verify ownership
            author = video_data.get('author_username', '').lower().strip()
            linked_username = account['platform_username'].lower().strip()
            if author and author != linked_username:
                results.append(f"❌ `{url[:30]}...` — Posted by @{author}, not you")
                continue

            # Save to database
            video_id_str = extract_video_id(norm_url, platform)
            record_id = await self.db.submit_video(
                campaign_id=campaign_id,
                discord_user_id=user_id,
                platform=platform,
                video_url=norm_url,
                video_id=video_id_str,
                author_username=video_data.get('author_username', linked_username),
                caption=video_data.get('caption', ''),
                is_verified=True,
                posted_at=video_data.get('posted_at'),
                tracking_expires_at=validity.get('expires_at')
            )

            if record_id:
                # Save initial metrics
                await self.db.save_metric_snapshot(
                    video_id=record_id,
                    views=video_data.get('views', 0),
                    likes=video_data.get('likes', 0),
                    comments=video_data.get('comments', 0),
                    shares=video_data.get('shares', 0),
                    extra_data=str(video_data.get('bookmarks', '')) if platform == 'twitter' else video_data.get('title', '')
                )
                results.append(f"✅ `{url[:30]}...` — Submitted{dup_notice}")
            else:
                results.append(f"❌ `{url[:30]}...` — DB Error")

            # Delay to save credits/avoid rate limit
            if i < len(urls) - 1:
                await asyncio.sleep(2)

        # Final Result Embed
        success_count = sum(1 for r in results if r.startswith("✅"))
        fail_count = len(results) - success_count
        
        final_embed = discord.Embed(
            title="📋 Bulk Submission Results",
            description="\n".join(results),
            color=discord.Color.green() if success_count > 0 else discord.Color.red()
        )
        final_embed.set_footer(text=f"📊 Result: {success_count} submitted, {fail_count} failed")
        
        try:
            await progress_msg.edit(embed=final_embed)
        except:
            pass

        # Notifications (only if successful)
        if success_count > 0:
            channel_id = await self.db.get_setting("notification_channel_id")
            if channel_id:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        await channel.send(embed=discord.Embed(
                            title="📹 Bulk Submission",
                            description=f"<@{user_id}> submitted **{success_count}** videos to **{campaign['name']}**",
                            color=discord.Color.blue()
                        ))
                except: pass

    @submit.error
    async def submit_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Please wait **{error.retry_after:.1f}s** before submitting again.",
                ephemeral=True
            )
        else:
            print(f"Submit error: {error}")

    @submit.autocomplete("campaign_id")
    async def submit_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            user_campaigns = await self.db.get_user_campaigns(str(interaction.user.id))
            return [
                app_commands.Choice(name=f"[{c['id']}] {c['name']}", value=c['id'])
                for c in user_campaigns
                if c.get('member_status') == 'active' and c.get('status') == 'active'
                and (current.lower() in c['name'].lower() or current.lower() in c['id'].lower())
            ][:25]
        except Exception:
            return []

    # ── MY VIDEOS ──────────────────────────────────────
    @app_commands.command(name="my_videos", description="View submitted videos")
    @app_commands.describe(
        campaign_id="Filter by campaign",
        user="View another user's videos (admin only)"
    )
    async def my_videos(
        self,
        interaction: discord.Interaction,
        campaign_id: str = None,
        user: discord.Member = None
    ):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        target_user = user or interaction.user
        user_id = str(target_user.id)
        
        # Admin check if viewing someone else
        if user and user.id != interaction.user.id:
            if not await is_admin(interaction):
                await interaction.followup.send("❌ Only admins can view other users' videos.", ephemeral=True)
                return

        videos = await self.db.get_user_videos(user_id, campaign_id)
        if not videos:
            await interaction.followup.send(f"❌ No videos found for <@{user_id}>.", ephemeral=True)
            return

        # Payment info (if admin viewing someone else)
        payment_info = ""
        if user and await is_admin(interaction):
            pay = await self.db.get_user_payment(user_id)
            if pay:
                payment_info = f"💰 **Payment:** {pay['crypto_type']} — `{pay['crypto_address']}`\n\n"

        # Groups videos for pagination
        chunk_size = 5
        pages = [videos[i:i + chunk_size] for i in range(0, len(videos), chunk_size)]
        
        async def build_page(page_idx):
            embed = discord.Embed(
                title=f"📹 Videos by {target_user.display_name} ({len(videos)} total)",
                description=payment_info,
                color=discord.Color.blue()
            )
            
            total_views = 0
            for v in pages[page_idx]:
                if v['is_final']:
                    views = v['final_views']
                    likes = v['final_likes']
                    status_text = "🔴 **FINAL** (24h elapsed)"
                else:
                    metrics = await self.db.get_latest_metrics(v['id'])
                    views = metrics.get('views', 0) if metrics else 0
                    likes = metrics.get('likes', 0) if metrics else 0
                    # Time remaining
                    exp = v.get('tracking_expires_at')
                    if exp:
                        try:
                            from datetime import timezone as tz
                            exp_dt = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                            if exp_dt.tzinfo is None:
                                exp_dt = exp_dt.replace(tzinfo=tz.utc)
                            remaining = exp_dt - datetime.now(tz.utc)
                            if remaining.total_seconds() > 0:
                                hours = int(remaining.total_seconds() // 3600)
                                minutes = int((remaining.total_seconds() % 3600) // 60)
                                rem = f"{hours}h {minutes}m"
                            else:
                                rem = "0h 0m"
                        except Exception:
                            rem = "N/A"
                        status_text = f"🟢 **TRACKING** — {rem} remaining"
                    else:
                        status_text = "🟢 **TRACKING**"

                total_views += views
                embed.add_field(
                    name=f"{platform_emoji(v['platform'])} {v.get('campaign_name', v['campaign_id'])}",
                    value=(
                        f"🔗 [Link]({v['video_url']})\n"
                        f"👁️ {format_number(views)} views │ ❤️ {format_number(likes)} likes\n"
                        f"{status_text}"
                    ),
                    inline=False
                )
            
            summary_stats = await self.db.get_user_all_time_stats(user_id)
            embed.set_footer(text=f"Page {page_idx+1}/{len(pages)} │ Total All-Time Views: {format_number(summary_stats.get('total_views', 0))}")
            return embed

        # Pagination View
        class Paginator(discord.ui.View):
            def __init__(self, current_page):
                super().__init__(timeout=60)
                self.current_page = current_page
                self.update_buttons()

            def update_buttons(self):
                self.prev_btn.disabled = self.current_page == 0
                self.next_btn.disabled = self.current_page == len(pages) - 1

            @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.gray)
            async def prev_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page -= 1
                self.update_buttons()
                await btn_interaction.response.edit_message(embed=await build_page(self.current_page), view=self)

            @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.gray)
            async def next_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page += 1
                self.update_buttons()
                await btn_interaction.response.edit_message(embed=await build_page(self.current_page), view=self)

        if len(pages) > 1:
            view = Paginator(0)
            await interaction.followup.send(embed=await build_page(0), view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=await build_page(0), ephemeral=True)

    @my_videos.autocomplete("campaign_id")
    async def my_videos_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            user_campaigns = await self.db.get_user_campaigns(str(interaction.user.id))
            return [
                app_commands.Choice(name=f"[{c['id']}] {c['name']}", value=c['id'])
                for c in user_campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

    # ── VIDEO DETAILS ──────────────────────────────────
    @app_commands.command(name="video_details", description="View detailed metrics for a specific video")
    @app_commands.describe(video_url="URL of the submitted video")
    async def video_details(self, interaction: discord.Interaction, video_url: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        video_url = normalize_url(video_url)
        video = await self.db.get_video_by_url(video_url)
    
        if not video:
            await interaction.followup.send("❌ Video not found.", ephemeral=True)
            return

        # Ownership check
        if video['discord_user_id'] != str(interaction.user.id) and not await is_admin(interaction):
            await interaction.followup.send("❌ You can only view details for your own videos.", ephemeral=True)
            return

        history = await self.db.get_metric_history(video['id'])
        campaign = await self.db.get_campaign(video['campaign_id'])
        rate = campaign.get('rate_per_10k_views', 10.0) if campaign else 10.0

        latest = {}  # Initialize so it's always defined
        if video['is_final']:
            views = video['final_views']
            likes = video['final_likes']
            comments = video['final_comments']
            status_text = "🔴 FINAL (24h Window Elapsed)"
        else:
            latest = history[-1] if history else {}
            views = latest.get('views', 0)
            likes = latest.get('likes', 0)
            comments = latest.get('comments', 0)
            exp = video.get('tracking_expires_at')
            rem = check_video_validity(exp).get('remaining', 'N/A')
            status_text = f"🟢 TRACKING ({rem} remaining)"

        earned = calculate_earnings(views, rate)

        embed = discord.Embed(title="📹 VIDEO DETAILS", color=get_platform_color(video.get('platform', 'instagram')))
        
        # Add title if YouTube
        if video.get('platform') == 'youtube' and video.get('caption'):
            embed.description = f"**{video.get('caption')}**"
            
        embed.add_field(name="🔗 URL", value=video_url, inline=False)
        embed.add_field(name="📊 Campaign", value=video.get('campaign_name', video['campaign_id']), inline=True)
        embed.add_field(name="📅 Status", value=status_text, inline=True)
        embed.add_field(name="👤 Author", value=f"@{video.get('author_username', 'N/A')}", inline=True)

        embed.add_field(name="━━━ Current Metrics ━━━", value="\u200b", inline=False)
        embed.add_field(name="👁️ Views", value=format_number(views), inline=True)
        embed.add_field(name="❤️ Likes", value=format_number(likes), inline=True)
        embed.add_field(name="💬 Comments", value=format_number(comments), inline=True)
        
        # Add platform specific stats
        shares = latest.get('shares', 0) if latest else 0
        if video.get('platform') == 'twitter':
            embed.add_field(name="🔁 Retweets/Quotes", value=format_number(shares), inline=True)
            # extra_data holds bookmarks if available
            bookmarks = latest.get('extra_data', '0') if latest else '0'
            if bookmarks and bookmarks.isdigit():
                embed.add_field(name="🔖 Bookmarks", value=format_number(int(bookmarks)), inline=True)
        elif video.get('platform') == 'tiktok':
            embed.add_field(name="🔁 Shares", value=format_number(shares), inline=True)
            
        embed.add_field(name="💰 Earnings", value=format_currency(earned), inline=True)

        # Growth history (if not final yet or just for record)
        if len(history) > 1:
            history_text = "```\nDate         Views       Likes    Comments\n"
            for h in history[-7:]:
                d = format_date(h.get('fetched_at', ''))[:10]
                history_text += f"{d:12s} {format_number(h.get('views', 0)):>10s} {format_number(h.get('likes', 0)):>8s} {format_number(h.get('comments', 0)):>8s}\n"
            history_text += "```"
            embed.add_field(name="📈 Growth History", value=history_text, inline=False)

        # Anti-fraud warning (Admin only)
        if await is_admin(interaction):
            from utils.anti_fraud import check_fraud
            # We don't have follower_count here easily, but let's pass 0
            warnings = check_fraud(views, likes, comments)
            if warnings:
                embed.add_field(name="🚨 ADMIN WARNINGS", value="\n".join(warnings), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── DELETE VIDEO ───────────────────────────────────
    @app_commands.command(name="delete_video", description="Delete a submitted video from tracking")
    @app_commands.describe(video_url="URL of the video to delete", reason="Reason for deletion")
    async def delete_video(self, interaction: discord.Interaction, video_url: str, reason: str = "Deleted by user"):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        video_url = normalize_url(video_url)
        video = await self.db.get_video_by_url(video_url)
    
        if not video:
            await interaction.followup.send("❌ Video not found.", ephemeral=True)
            return

        if video['discord_user_id'] != str(interaction.user.id) and not await is_admin(interaction):
            await interaction.followup.send("❌ You can only delete your own videos.", ephemeral=True)
            return

        success = await self.db.delete_video(video_url)
        if success:
            await interaction.followup.send(embed=discord.Embed(
                title="🗑️ Video Deleted",
                description=f"Video has been removed from tracking.\n**Reason:** {reason}",
                color=discord.Color.red()
            ), ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to delete video.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SubmissionCommands(bot))
