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
    Standardizes social media timestamps into UTC-aware datetime objects
    and checks if they fall within the 24-hour tracking window.
    """
    if not posted_at_str:
        return {"valid": True, "message": "No timestamp available"}
        
    try:
        # 1. Handle Unix Epoch (int or float)
        if isinstance(posted_at_str, (int, float)) or (isinstance(posted_at_str, str) and posted_at_str.isdigit()):
            ts = float(posted_at_str)
            # If timestamp is very large (ms based), divide by 1000
            if ts > 10**11:
                ts /= 1000
            posted_at = datetime.fromtimestamp(ts, tz=timezone.utc)
        
        # 2. Handle ISO strings
        elif isinstance(posted_at_str, str):
            # Standardize Z to +00:00 for isoformat
            clean_str = posted_at_str.replace("Z", "+00:00")
            # Handle Twitter style 'Wed Nov 20 17:15:46 +0000 2023' or similar if needed
            # But Apify usually gives ISO. Let's stick to fromisoformat for now.
            posted_at = datetime.fromisoformat(clean_str)
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)
        else:
            return {"valid": True, "message": "Unknown timestamp type"}
            
    except Exception as e:
        print(f"[ValidityCheck] Timestamp error {posted_at_str}: {e}")
        return {"valid": True, "message": "Invalid timestamp format"}
        
    now = datetime.now(timezone.utc)
    age = now - posted_at
    
    # 24 hour limit
    if age > timedelta(hours=24):
        return {
            "valid": False,
            "is_final": True,
            "remaining": "0h 0m",
            "status": "FINAL",
            "message": "❌ This video was posted more than 24 hours ago."
        }
    
    # If age is negative (posted in "future" due to minor clock drifts)
    if age < timedelta(0):
        remaining = timedelta(hours=24)
        age_for_display = "Younger than 1 minute"
    else:
        remaining = timedelta(hours=24) - age
        age_for_display = f"{age.seconds // 3600}h {(age.seconds % 3600) // 60}m ago"

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

        try:
            # STEP 1: Process URL list
            urls = [u.strip() for u in video_urls.split(",") if u.strip()]

            # Remove duplicates while preserving order
            seen = set()
            unique_urls = []
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            urls = unique_urls

            if not urls:
                await interaction.followup.send("❌ No URLs provided.", ephemeral=True)
                return

            if len(urls) > 10:
                await interaction.followup.send(
                    f"❌ Maximum 10 videos per submission. You sent {len(urls)}.",
                    ephemeral=True,
                )
                return

            # STEP 2: Check campaign exists and is active
            campaign = await self.db.get_campaign(campaign_id)
            if not campaign:
                await interaction.followup.send(
                    f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
                )
                return

            if campaign["status"] != "active":
                await interaction.followup.send(
                    f"❌ Campaign `{campaign_id}` is not active.", ephemeral=True
                )
                return

            # STEP 3: Check membership
            user_id = str(interaction.user.id)
            if not await self.db.is_campaign_member(campaign_id, user_id):
                await interaction.followup.send(
                    f"❌ You haven't joined this campaign.\nUse `/join {campaign_id}` first.",
                    ephemeral=True,
                )
                return

            # STEP 4: Validate URLs and detect platforms
            validated_urls = []
            invalid_urls = []
            for url in urls:
                norm = normalize_url(url)
                platform = detect_platform(norm)
                if platform:
                    validated_urls.append((norm, platform))
                else:
                    invalid_urls.append(url)

            if not validated_urls:
                await interaction.followup.send(
                    "❌ No valid Instagram/TikTok/YouTube/Twitter URLs found.",
                    ephemeral=True,
                )
                return

            await self._ensure_initialized()

            # ── SINGLE VIDEO — simple flow ─────────────────
            if len(validated_urls) == 1:
                url, platform = validated_urls[0]

                # Show "fetching" message
                progress_embed = discord.Embed(
                    title="⏳ Fetching Metrics...",
                    description=f"Scraping `{url[:60]}`...\nThis may take 30-60 seconds.",
                    color=discord.Color.yellow(),
                )
                try:
                    progress_msg = await interaction.followup.send(
                        embed=progress_embed, ephemeral=True
                    )
                except Exception:
                    return

                result = await self._process_and_save_single(
                    url, platform, campaign, user_id, campaign_id
                )

                if result.get("_skip_reason"):
                    # Validation failed — show error
                    final_embed = discord.Embed(
                        title="❌ Submission Failed",
                        description=result["_skip_reason"],
                        color=discord.Color.red(),
                    )
                else:
                    views = result.get("views", 0)
                    likes = result.get("likes", 0)
                    comments = result.get("comments", 0)
                    est = " (estimated)" if result.get("estimated") else ""
                    final_embed = discord.Embed(
                        title="✅ Video Submitted",
                        description=f"🔗 `{url[:55]}`",
                        color=discord.Color.green(),
                    )
                    final_embed.add_field(
                        name="📊 Metrics",
                        value=(
                            f"👁️ {views:,} views{est}\n"
                            f"❤️ {likes:,} likes\n"
                            f"💬 {comments:,} comments"
                        ),
                        inline=False,
                    )
                    final_embed.set_footer(text=f"Campaign: {campaign_id}")

                try:
                    await progress_msg.edit(embed=final_embed)
                except discord.errors.NotFound:
                    pass
                return

            # ── MULTIPLE VIDEOS — bulk flow with live progress ──
            total = len(validated_urls)
            results = []  # list of (url, result_dict)

            # Build initial progress embed
            status_lines = []
            for k, (u, _p) in enumerate(validated_urls):
                status_lines.append(f"  ⬜ {k+1}. `{u[:45]}` — waiting...")

            progress_embed = discord.Embed(
                title=f"⏳ Processing 0/{total} videos...",
                description="\n".join(status_lines),
                color=discord.Color.yellow(),
            )
            if invalid_urls:
                invalid_list = "\n".join([f"  ❌ `{u[:50]}`" for u in invalid_urls[:5]])
                progress_embed.add_field(
                    name="Invalid URLs (skipped)", value=invalid_list, inline=False
                )

            try:
                progress_msg = await interaction.followup.send(
                    embed=progress_embed, ephemeral=True
                )
            except Exception:
                return

            # Process each video through queue
            for i, (url, platform) in enumerate(validated_urls):
                # Update progress BEFORE processing this video
                status_lines = []
                for j, (prev_url, prev_result) in enumerate(results):
                    if prev_result.get("_skip_reason") or prev_result.get("error"):
                        reason = prev_result.get("_skip_reason", prev_result.get("error", "failed"))
                        status_lines.append(
                            f"  ❌ {j+1}. `{prev_url[:45]}` — {str(reason)[:30]}"
                        )
                    else:
                        views = prev_result.get("views", 0)
                        likes = prev_result.get("likes", 0)
                        icon = "⚠️" if prev_result.get("estimated") else "✅"
                        status_lines.append(
                            f"  {icon} {j+1}. `{prev_url[:45]}` — {views:,} views, {likes:,} likes"
                        )

                status_lines.append(f"  ⏳ {i+1}. `{url[:45]}` — fetching...")

                for k in range(i + 1, total):
                    remaining_url = validated_urls[k][0]
                    status_lines.append(f"  ⬜ {k+1}. `{remaining_url[:45]}` — waiting...")

                progress_embed = discord.Embed(
                    title=f"⏳ Processing {i+1}/{total} videos...",
                    description="\n".join(status_lines),
                    color=discord.Color.yellow(),
                )
                try:
                    await progress_msg.edit(embed=progress_embed)
                except discord.errors.NotFound:
                    pass

                # Process this video
                result = await self._process_and_save_single(
                    url, platform, campaign, user_id, campaign_id
                )
                results.append((url, result))

                # Small delay before updating message (avoid Discord rate limit)
                await asyncio.sleep(1)

            # ── FINAL RESULT — summary embed ───────────────
            success_count = sum(
                1 for _, r in results
                if not r.get("_skip_reason") and not r.get("error") and not r.get("estimated")
            )
            estimated_count = sum(
                1 for _, r in results
                if r.get("estimated") and not r.get("_skip_reason") and not r.get("error")
            )
            failed_count = sum(
                1 for _, r in results if r.get("_skip_reason") or r.get("error")
            )
            total_views = sum(
                r.get("views", 0) for _, r in results if not r.get("_skip_reason")
            )
            total_likes = sum(
                r.get("likes", 0) for _, r in results if not r.get("_skip_reason")
            )

            final_lines = []
            for j, (url, result) in enumerate(results):
                if result.get("_skip_reason"):
                    final_lines.append(
                        f"❌ {j+1}. `{url[:45]}`\n"
                        f"    {result['_skip_reason'][:60]}"
                    )
                elif result.get("error"):
                    final_lines.append(
                        f"❌ {j+1}. `{url[:45]}`\n"
                        f"    Error: {str(result['error'])[:50]}"
                    )
                else:
                    views = result.get("views", 0)
                    likes = result.get("likes", 0)
                    comments = result.get("comments", 0)
                    icon = "⚠️" if result.get("estimated") else "✅"
                    est_text = " (estimated)" if result.get("estimated") else ""
                    final_lines.append(
                        f"{icon} {j+1}. `{url[:45]}`\n"
                        f"    👁️ {views:,} views{est_text} | ❤️ {likes:,} | 💬 {comments:,}"
                    )

            final_embed = discord.Embed(
                title="📋 Bulk Submission Complete",
                description="\n\n".join(final_lines),
                color=discord.Color.green() if failed_count == 0 else discord.Color.yellow(),
            )
            final_embed.add_field(
                name="📊 Summary",
                value=(
                    f"✅ Successful: {success_count}\n"
                    f"⚠️ Estimated: {estimated_count}\n"
                    f"❌ Failed: {failed_count}\n"
                    f"👁️ Total Views: {total_views:,}\n"
                    f"❤️ Total Likes: {total_likes:,}"
                ),
                inline=False,
            )
            if invalid_urls:
                final_embed.add_field(
                    name="⚠️ Invalid URLs (skipped)",
                    value="\n".join([f"• `{u[:50]}`" for u in invalid_urls[:5]]),
                    inline=False,
                )
            final_embed.set_footer(
                text=f"Campaign: {campaign_id} | Submitted by {interaction.user.display_name}"
            )

            try:
                await progress_msg.edit(embed=final_embed)
            except discord.errors.NotFound:
                try:
                    await interaction.followup.send(embed=final_embed)
                except Exception:
                    pass

            # Notification
            actual_success = success_count + estimated_count
            if actual_success > 0:
                channel_id = await self.db.get_setting("notification_channel_id")
                if channel_id:
                    try:
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            await channel.send(
                                embed=discord.Embed(
                                    title="📹 Bulk Submission",
                                    description=(
                                        f"<@{user_id}> submitted **{actual_success}** "
                                        f"videos to **{campaign['name']}**"
                                    ),
                                    color=discord.Color.blue(),
                                )
                            )
                    except Exception:
                        pass

        except Exception as e:
            try:
                await interaction.followup.send(
                    f"❌ Error during submission: {str(e)[:200]}", ephemeral=True
                )
            except Exception:
                pass

    async def _process_and_save_single(
        self, url: str, platform: str, campaign: dict, user_id: str, campaign_id: str
    ) -> dict:
        """
        Validate ownership, scrape via queue, and save to DB for one URL.
        Returns the metrics dict. If validation fails, returns dict with '_skip_reason'.
        """
        # Check platform compatibility
        campaign_platforms = campaign.get("platforms", "all")
        if campaign_platforms != "all" and platform != campaign_platforms:
            return {"_skip_reason": f"Wrong platform (only {campaign_platforms})"}

        # Check linked account(s)
        accounts = await self.db.get_user_accounts(user_id)
        platform_accounts = [
            a for a in accounts if a["platform"] == platform and a.get("verified")
        ]

        if not platform_accounts:
            unverified = [
                a for a in accounts if a["platform"] == platform and not a.get("verified")
            ]
            if unverified:
                return {
                    "_skip_reason": f"Account @{unverified[0]['platform_username']} is NOT verified"
                }
            return {"_skip_reason": f"Link {platform.title()} first"}

        # Check duplicates
        existing = await self.db.get_submitted_video_by_url(campaign_id, url)
        if existing:
            return {"_skip_reason": "Already submitted here"}

        # Scrape via queue (high priority)
        try:
            video_data = await self.bot.scrape_queue.submit_and_wait(
                video_url=url,
                discord_user_id=user_id,
                campaign_id=campaign_id,
            )
        except Exception as e:
            return {"_skip_reason": f"Scrape failed ({str(e)[:50]})"}

        if not video_data:
            return {"_skip_reason": "Scrape failed"}

        # 24-hour validity
        validity = check_video_validity(video_data.get("posted_at"))
        if not validity["valid"]:
            return {"_skip_reason": "Posted >24h ago"}

        # Verify ownership
        author = video_data.get("author_username", "").lower().strip()
        matched_account = None
        if author:
            for acc in platform_accounts:
                if acc["platform_username"].lower().strip() == author:
                    matched_account = acc
                    break
            if not matched_account:
                return {
                    "_skip_reason": f"Posted by @{author}, not your linked account(s)"
                }
        else:
            matched_account = platform_accounts[0]

        linked_username = matched_account["platform_username"]

        # Save to database
        video_id_str = extract_video_id(url, platform)
        record_id = await self.db.submit_video(
            campaign_id=campaign_id,
            discord_user_id=user_id,
            platform=platform,
            video_url=url,
            video_id=video_id_str,
            author_username=video_data.get("author_username", linked_username),
            caption=video_data.get("caption", ""),
            is_verified=True,
            posted_at=video_data.get("posted_at"),
            tracking_expires_at=validity.get("expires_at"),
        )

        if record_id:
            await self.db.save_metric_snapshot(
                video_id=record_id,
                views=video_data.get("views", 0),
                likes=video_data.get("likes", 0),
                comments=video_data.get("comments", 0),
                shares=video_data.get("shares", 0),
                extra_data=(
                    str(video_data.get("bookmarks", ""))
                    if platform == "twitter"
                    else video_data.get("title", "")
                ),
            )
            return video_data
        else:
            return {"_skip_reason": "DB Error"}

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
                if v.get('status') == 'rejected':
                    views = 0
                    likes = 0
                    status_text = "🚫 **REJECTED**"
                elif v['is_final']:
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
                                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                            
                            now_utc = datetime.now(timezone.utc)
                            remaining = exp_dt - now_utc
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
        if video.get('status') == 'rejected':
            views = 0
            likes = 0
            comments = 0
            status_text = "🚫 REJECTED (Views Zeroed)"
        elif video['is_final']:
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
