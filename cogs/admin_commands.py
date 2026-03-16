"""Admin commands: create, update, end, delete campaign."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from utils.permissions import admin_only, owner_only
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
        auto_stop: bool = None
    ):
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.errors.NotFound, Exception):
            return  # Interaction expired or network error — can't respond

        # Get default rate from settings if not specified
        if rate_per_10k_views is None:
            default_rate = await self.db.get_setting("default_rate_per_10k")
            try:
                rate_per_10k_views = float(default_rate) if default_rate else 10.00
            except ValueError:
                rate_per_10k_views = 10.00

        # Get default auto-stop from settings if not specified
        if auto_stop is None:
            default_auto_stop = await self.db.get_setting("default_auto_stop")
            auto_stop = False if default_auto_stop == "false" else True

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
            await interaction.followup.send(embed=embed, ephemeral=True)

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
            try:
                await interaction.followup.send(
                    "⚠️ No changes specified.", ephemeral=True
                )
            except:
                pass
            return

        success = await self.db.update_campaign(campaign_id, **kwargs)
        if success:
            updated_campaign = await self.db.get_campaign(campaign_id)
            embed = build_campaign_embed(updated_campaign)
            embed.title = "✅ Campaign Updated"
            changes = ", ".join(f"**{k}**" for k in kwargs.keys())
            embed.description = f"Updated: {changes}"
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            try:
                await interaction.followup.send(
                    "❌ Failed to update campaign.", ephemeral=True
                )
            except:
                pass

    @update_campaign.autocomplete("campaign_id")
    async def campaign_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_all_campaigns()
            return [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

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
            
        if campaign['status'] == 'completed':
            try:
                await interaction.followup.send(
                    f"⚠️ Campaign `{campaign_id}` is already completed.", ephemeral=True
                )
            except:
                pass
            return
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

        await interaction.followup.send(embed=embed, ephemeral=True)

    @end_campaign.autocomplete("campaign_id")
    async def end_campaign_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_active_campaigns()
            return [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

    # ── DELETE CAMPAIGN ────────────────────────────────
    @app_commands.command(name="delete_campaign", description="Permanently delete a campaign")

    @app_commands.describe(campaign_id="Campaign to delete")
    @admin_only()
    async def delete_campaign(self, interaction: discord.Interaction, campaign_id: str):
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
    
        success = await self.db.delete_campaign(campaign_id)
        if success:
            embed = discord.Embed(
                title="🗑️ Campaign Deleted",
                description=f"Campaign **{campaign['name']}** (`{campaign_id}`) has been permanently deleted.",
                color=discord.Color.red()
            )
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                pass
        else:
            try:
                await interaction.followup.send(
                    "❌ Failed to delete campaign.", ephemeral=True
                )
            except:
                pass

    @delete_campaign.autocomplete("campaign_id")
    async def delete_campaign_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_all_campaigns()
            return [
                app_commands.Choice(name=f"[{c['id']}] {c['name']}", value=c['id'])
                for c in campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

    # ── API USAGE ──────────────────────────────────────
    @app_commands.command(name="api_usage", description="View API usage statistics")

    @app_commands.describe(days="Number of days to look back (default: 7)")
    @admin_only()
    async def api_usage(self, interaction: discord.Interaction, days: int = 7):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        from services.apify_instagram import ApifyInstagramService
        apify_service = ApifyInstagramService(self.db)
        stats = await apify_service.get_usage_stats(days=days)

        embed = discord.Embed(
            title="📊 API Usage",
            description=f"Statistics for the past **{days} days**",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="ApiCalls Made", 
            value=f"**{stats['total_calls']}** calls", 
            inline=True
        )
        
        # Calculate cost
        # Pricing is $2.50 per 1000 requests, so $0.0025 per request
        cost = stats['total_calls'] * 0.0025
        embed.add_field(
            name="Estimated Cost", 
            value=f"**${cost:.4f}** (at $2.50/1k)", 
            inline=True
        )

        embed.add_field(
            name="Success Rate", 
            value=f"**{stats['success_rate']:.1f}%**", 
            inline=True
        )

        embed.add_field(
            name="Cache Hits", 
            value=f"**{stats['cache_hits']}** (saved ${stats['cache_hits'] * 0.0025:.4f})", 
            inline=False
        )

        embed.set_footer(text="Data depends on local sqlite logs.")

        try:
            await interaction.followup.send(embed=embed)
        except Exception:
            pass

    @app_commands.command(name="export", description="Export campaign submission data with clipper breakdown")

    @app_commands.describe(
        campaign_id="Campaign ID to export"
    )
    @admin_only()
    async def export(self, interaction: discord.Interaction, campaign_id: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        import io
        import csv
        import aiosqlite
        from campaign.payment_calculator import calculate_earnings

        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.followup.send(f"❌ Campaign `{campaign_id}` not found.", ephemeral=True)
            return

        rate = campaign.get('rate_per_10k_views', 10.0)

        # Query to get grouped data: User -> Platform/Account -> Sum of Views
        async with aiosqlite.connect(self.db.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # 1. Get detailed records for CSV
            query = """
                SELECT 
                    sv.discord_user_id,
                    sv.platform,
                    sv.author_username,
                    sv.video_url,
                    CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE IFNULL(latest.views, 0) END as video_views,
                    up.crypto_type,
                    up.crypto_address
                FROM submitted_videos sv
                LEFT JOIN (
                    SELECT video_id, views
                    FROM metric_snapshots m1
                    WHERE m1.id = (
                        SELECT MAX(m2.id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                    )
                ) latest ON sv.id = latest.video_id
                LEFT JOIN user_payments up ON sv.discord_user_id = up.discord_user_id
                WHERE sv.campaign_id = ? AND sv.status != 'deleted'
            """
            async with db.execute(query, (campaign_id,)) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]

        if not rows:
            await interaction.followup.send("❌ No data found for this campaign.", ephemeral=True)
            return

        # 2. Process data for summary and CSV
        user_data = {}
        total_overall_views = 0
        
        # Get unique users in this campaign
        unique_uids = list(set([row['discord_user_id'] for row in rows]))
        
        for uid in unique_uids:
            # Fetch OVERALL stats for this user right from the DB as requested
            stats = await self.db.get_user_all_time_stats(uid)
            overall_views = stats.get('total_views', 0)
            overall_likes = stats.get('total_likes', 0)
            
            user_rows = [r for r in rows if r['discord_user_id'] == uid]
            first_row = user_rows[0]
            
            # Group unique accounts and unique video URLs (but ignore their counts as requested)
            account_handles = list(set([f"@{r['author_username']}" for r in user_rows if r['author_username']]))
            video_urls = [r['video_url'] for r in user_rows]
            
            member_name = f"User {uid}"
            try:
                if interaction.guild:
                    member = interaction.guild.get_member(int(uid))
                    if member:
                        member_name = member.name
                    else:
                        user = self.bot.get_user(int(uid))
                        if user:
                            member_name = user.name
            except Exception:
                pass

            user_data[uid] = {
                'discord_name': member_name,
                'overall_views': overall_views,
                'overall_likes': overall_likes,
                'account_handles': account_handles,
                'video_urls': video_urls,
                'crypto_type': first_row['crypto_type'] or "Not Set",
                'crypto_address': first_row['crypto_address'] or "N/A"
            }
            total_overall_views += overall_views


        # 3. Create Summary Embed
        embed = discord.Embed(
            title=f"📋 Export Summary: {campaign['name']}",
            description=f"**ID:** `{campaign_id}`\n**Rate:** ${rate}/10k views",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="👥 Total Clippers", value=str(len(user_data)), inline=True)
        embed.add_field(name="👁️ Total Overall Views", value=format_number(total_overall_views), inline=True)
        embed.add_field(name="💰 Total Payout (All-time)", value=format_currency(calculate_earnings(total_overall_views, rate)), inline=True)

        summary_text = ""
        # Sort users by overall views
        sorted_users = sorted(user_data.items(), key=lambda x: x[1]['overall_views'], reverse=True)
        
        for uid, data in sorted_users[:15]: # Show top 15 in embed
            earned = calculate_earnings(data['overall_views'], rate)
            handles = ", ".join(data['account_handles']) if data['account_handles'] else "None"
            
            summary_text += f"👤 <@{uid}> │ handles: `{handles}`\n"
            summary_text += f"└ 👁️ **{format_number(data['overall_views'])}** overall views │ {format_currency(earned)}\n\n"


        if not summary_text:
            summary_text = "No submission data available."
            
        if len(user_data) > 15:
            summary_text += f"\n*...and {len(user_data) - 15} more clippers in the CSV file.*"

        if len(summary_text) > 1024:
            summary_text = summary_text[:950] + "\n\n*(Summary truncated)*"
            
        embed.add_field(name="📊 Overall Views Breakdown", value=summary_text, inline=False)

        # 4. Define Download Button View
        class ExportView(discord.ui.View):
            def __init__(self, bot_instance, grouped_data, c_name, c_rate):
                super().__init__(timeout=600)
                self.bot = bot_instance
                self.data = grouped_data
                self.campaign_name = c_name
                self.rate = c_rate

            @discord.ui.button(label="📥 Download CSV Report", style=discord.ButtonStyle.success)
            async def download_csv(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.defer(ephemeral=True)
                
                output = io.StringIO()
                headers = [
                    'Discord Name', 'Discord ID', 'Overall Views', 'Overall Likes', 'Total Earnings ($)', 
                    'Crypto Type', 'Address', 'Account Handles', 'Video Links'
                ]
                writer = csv.DictWriter(output, fieldnames=headers)
                writer.writeheader()
                
                for uid_str, d in sorted(self.data.items(), key=lambda x: x[1]['overall_views'], reverse=True):
                    writer.writerow({
                        'Discord Name': d['discord_name'],
                        'Discord ID': uid_str,
                        'Overall Views': d['overall_views'],
                        'Overall Likes': d['overall_likes'],
                        'Total Earnings ($)': f"{calculate_earnings(d['overall_views'], self.rate):.2f}",
                        'Crypto Type': d['crypto_type'],
                        'Address': d['crypto_address'],
                        'Account Handles': ", ".join(d['account_handles']),
                        'Video Links': "\n".join(d['video_urls'])
                    })


                
                file_data = output.getvalue()
                file_obj = io.BytesIO(file_data.encode('utf-8'))
                filename = f"export_{self.campaign_name.lower().replace(' ', '_')}.csv"
                
                file = discord.File(file_obj, filename=filename)
                await btn_interaction.followup.send(
                    f"✅ Here is the detailed report for **{self.campaign_name}**:", 
                    file=file, ephemeral=True
                )

        view = ExportView(self.bot, user_data, campaign['name'], rate)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @export.autocomplete("campaign_id")
    async def export_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_all_campaigns()
            return [
                app_commands.Choice(name=f"[{c['id']}] {c['name']}", value=c['id'])
                for c in campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

    # ── USER INFO (Admin) ─────────────────────────────
    @app_commands.command(name="user_info", description="View a user's payment info, linked accounts, and campaigns")

    @app_commands.describe(user="The Discord user to look up")
    @admin_only()
    async def user_info(self, interaction: discord.Interaction, user: discord.User):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        try:
            uid = str(user.id)

            # 1. Payment info
            payment = await self.db.get_user_payment(uid)

            # 2. Linked accounts
            accounts = await self.db.get_user_accounts(uid)

            # 3. Campaign memberships
            campaigns = await self.db.get_user_campaigns(uid)

            embed = discord.Embed(
                title=f"👤 User Info: {user}",
                description=f"**Discord ID:** `{uid}`",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else "")

            # Payment section
            if payment:
                embed.add_field(
                    name="💳 Payment Info",
                    value=(
                        f"**Type:** {payment.get('crypto_type', 'N/A')}\n"
                        f"**Address:** `{payment.get('crypto_address', 'N/A')}`\n"
                        f"**Updated:** {payment.get('updated_at', 'N/A')}"
                    ),
                    inline=False
                )
            else:
                embed.add_field(
                    name="💳 Payment Info",
                    value="❌ No payment info set",
                    inline=False
                )

            # Linked accounts section
            if accounts:
                acc_lines = []
                for acc in accounts:
                    emoji = {"instagram": "📷", "tiktok": "🎵", "twitter": "🐦"}.get(acc['platform'], "🌐")
                    verified = "✅" if acc.get('verified') else "⏳"
                    acc_lines.append(f"{emoji} @{acc['platform_username']} {verified}")
                embed.add_field(
                    name=f"🔗 Linked Accounts ({len(accounts)})",
                    value="\n".join(acc_lines),
                    inline=False
                )
            else:
                embed.add_field(
                    name="🔗 Linked Accounts",
                    value="❌ No accounts linked",
                    inline=False
                )

            # Campaigns section
            if campaigns:
                camp_lines = []
                from campaign.payment_calculator import calculate_earnings
                for c in campaigns[:10]:
                    status_icon = {"active": "🟢", "left": "🔴", "paused": "🟡"}.get(
                        c.get('member_status', 'active'), "⚪"
                    )
                    stats = await self.db.get_user_campaign_stats(c['id'], uid)
                    rate = c.get('rate_per_10k_views', 10.0)
                    earned = calculate_earnings(stats.get('total_views', 0), rate)
                    camp_lines.append(
                        f"{status_icon} **{c['name']}** (`{c['id']}`)\n"
                        f"   Views: {format_number(stats.get('total_views', 0))} │ "
                        f"Earned: {format_currency(earned)}"
                    )
                embed.add_field(
                    name=f"📋 Campaigns ({len(campaigns)})",
                    value="\n".join(camp_lines),
                    inline=False
                )
            else:
                embed.add_field(
                    name="📋 Campaigns",
                    value="❌ Not in any campaigns",
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except discord.errors.NotFound:
            pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass


    # ── FORCE UPDATE VIEWS ────────────────────────────
    @app_commands.command(name="force_update", description="Force update views for all videos in active campaigns")

    @app_commands.describe(user="Optional: update only this user's videos")
    @admin_only()
    async def force_update(self, interaction: discord.Interaction, user: discord.User = None):
        try:
            await interaction.response.defer(ephemeral=False)
        except discord.errors.NotFound:
            return

        scraper_cog = self.bot.get_cog('PeriodicScraper')
        if not scraper_cog:
            await interaction.followup.send("❌ PeriodicScraper module not loaded.", ephemeral=True)
            return

        if user:
            await interaction.followup.send(
                f"⏳ **Starting force update** for <@{user.id}>'s videos... This may take a while.",
                ephemeral=False
            )
        else:
            await interaction.followup.send(
                "⏳ **Starting force update.** Scraping all tracked videos... This may take a while.",
                ephemeral=False
            )
        
        try:
            if user:
                summary = await scraper_cog.scrape_user_tracking_videos(str(user.id))
            else:
                summary = await scraper_cog.scrape_all_tracking_videos()

            title = f"✅ Force Update Complete — <@{user.id}>" if user else "✅ Force Update Complete"
            embed = discord.Embed(
                title=title,
                color=discord.Color.green()
            )
            embed.add_field(
                name="Results",
                value=(
                    f"✅ Successful: {summary['successful']}\n"
                    f"❌ Failed: {summary['failed']}\n"
                    f"📹 Total Videos: {summary.get('total_videos', summary['successful'] + summary['failed'])}"
                ),
                inline=False
            )
            if summary.get('errors') and summary['errors'][:3]:
                embed.add_field(
                    name="Recent Errors",
                    value="\n".join(summary['errors'][:3]),
                    inline=False
                )
            await interaction.followup.send(content=f"<@{interaction.user.id}>", embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Error during force update: {e}", ephemeral=False)

    # ── REJECT VIDEO ──────────────────────────────────
    @app_commands.command(name="reject_video", description="Admin: Reject a specific video from a user (stops tracking and zeros views)")

    @app_commands.describe(
        user="The Discord user whose video to reject",
        video_url="The URL of the video to reject"
    )
    @admin_only()
    async def reject_video(self, interaction: discord.Interaction, user: discord.User, video_url: str):
        try:
            await interaction.response.defer(ephemeral=False)
        except discord.errors.NotFound:
            return

        from utils.platform_detector import normalize_url
        norm_url = normalize_url(video_url)

        # Confirm the video exists for this user
        existing_video = await self.db.get_video_by_url(norm_url)
        if not existing_video:
            await interaction.followup.send(f"❌ Could not find video with URL: {video_url}", ephemeral=True)
            return

        if existing_video['discord_user_id'] != str(user.id):
            await interaction.followup.send(f"❌ That video was submitted by <@{existing_video['discord_user_id']}>, not <@{user.id}>.", ephemeral=True)
            return

        if existing_video['status'] == 'rejected':
            await interaction.followup.send("⚠️ This video is already rejected.", ephemeral=True)
            return

        # Reject it
        success = await self.db.reject_video(str(user.id), norm_url)
        
        if success:
            embed = discord.Embed(
                title="🚫 Video Rejected",
                description=f"Successfully rejected video submitted by <@{user.id}>.\n\n**Video:** [Link]({norm_url})\n\n*(Tracking stopped and views zeroed out)*",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=False)

            # Attempt to DM the user
            try:
                dm_embed = discord.Embed(
                    title="🚫 Video Rejected",
                    description=f"Your submitted video has been rejected by an administrator. It will no longer be tracked for campaign rewards.\n\n**Video:** {norm_url}",
                    color=discord.Color.red()
                )
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                pass
        else:
            await interaction.followup.send("❌ Failed to reject the video. This could be a database error.", ephemeral=True)

    # ── REJECT USER ──────────────────────────────────
    @app_commands.command(name="reject_user", description="Admin: Ban a user from a campaign and zero their video views")

    @app_commands.describe(
        user="The Discord user to ban",
        campaign_id="The ID of the campaign to ban them from"
    )
    @admin_only()
    async def reject_user(self, interaction: discord.Interaction, user: discord.User, campaign_id: str):
        try:
            await interaction.response.defer(ephemeral=False)
        except discord.errors.NotFound:
            return

        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.followup.send(f"❌ Campaign `{campaign_id}` not found.", ephemeral=True)
            return

        success = await self.db.reject_user(campaign_id, str(user.id))
        
        if success:
            embed = discord.Embed(
                title="🚫 User Rejected from Campaign",
                description=f"Successfully banned <@{user.id}> from **{campaign['name']}**.\n\n*(Their membership is removed, tracking stopped, and views zeroed out)*",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=False)

            # Attempt to DM the user
            try:
                dm_embed = discord.Embed(
                    title="🚫 Campaign Ban",
                    description=f"You have been removed from the campaign **{campaign['name']}**.\n\nYour submitted videos will no longer be tracked, and all views have been voided for this campaign.",
                    color=discord.Color.red()
                )
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                pass
        else:
            await interaction.followup.send("❌ Failed to reject the user. Database error.", ephemeral=True)

    @reject_user.autocomplete("campaign_id")
    async def reject_user_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_all_campaigns()
            return [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in campaigns if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

    # ── UNREJECT USER ────────────────────────────────
    @app_commands.command(name="unreject_user", description="Admin: Unban a user from a campaign and restore their video tracking")

    @app_commands.describe(
        user="The Discord user to unban",
        campaign_id="The ID of the campaign"
    )
    @admin_only()
    async def unreject_user(self, interaction: discord.Interaction, user: discord.User, campaign_id: str):
        try:
            await interaction.response.defer(ephemeral=False)
        except discord.errors.NotFound:
            return

        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.followup.send(f"❌ Campaign `{campaign_id}` not found.", ephemeral=True)
            return

        success = await self.db.unreject_user(campaign_id, str(user.id))
        
        if success:
            embed = discord.Embed(
                title="✅ User Unbanned",
                description=f"Successfully unbanned <@{user.id}> from **{campaign['name']}**.\n\n*(Their rejected videos are now active again and views will update on the next tracking cycle)*",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=False)
        else:
            await interaction.followup.send("❌ Failed to unreject the user.", ephemeral=True)

    @unreject_user.autocomplete("campaign_id")
    async def unreject_user_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_all_campaigns()
            return [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in campaigns if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

    # ── QUEUE STATS ───────────────────────────────────
    @app_commands.command(name="queue_stats", description="Admin: View scrape queue health")

    @admin_only()
    async def queue_stats(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        queue = getattr(self.bot, 'scrape_queue', None)
        if not queue:
            await interaction.followup.send("❌ Queue not initialized yet.", ephemeral=True)
            return

        stats = queue.get_stats()

        embed = discord.Embed(
            title="📊 Scrape Queue Status",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📥 Queue",
            value=(
                f"**Main queue:** {stats['queue_size']} jobs\n"
                f"**Retry queue:** {stats['retry_queue_size']} jobs"
            ),
            inline=True
        )
        embed.add_field(
            name="📈 Performance",
            value=(
                f"**Processed:** {stats['jobs_processed']}\n"
                f"**Succeeded:** {stats['jobs_succeeded']}\n"
                f"**Failed:** {stats['jobs_failed']}\n"
                f"**Success rate:** {stats['success_rate']}"
            ),
            inline=True
        )
        embed.add_field(
            name="⏱️ Timing",
            value=(
                f"**Current delay:** {stats['current_delay']}\n"
                f"**Consecutive errors:** {stats['consecutive_errors']}\n"
                f"**Last request:** {stats['last_request']}"
            ),
            inline=False
        )

        # Backoff level indicator
        level = stats['consecutive_errors']
        if level == 0:
            status_icon = "🟢 Normal"
        elif level <= 2:
            status_icon = "🟡 Elevated"
        else:
            status_icon = "🔴 High Backoff"

        embed.add_field(
            name="🚦 Status",
            value=status_icon,
            inline=True
        )

        # ── Token Rotation Stats ──
        if hasattr(queue, 'apify') and hasattr(queue.apify, 'token_rotator'):
            token_stats = queue.apify.token_rotator.get_all_stats()
            if token_stats:
                token_lines = []
                for ts in token_stats:
                    status = "✅ Ready"
                    if ts['cooldown'] != "None":
                        status = f"⏳ Cooling ({ts['cooldown']})"
                    
                    token_lines.append(
                        f"**{ts['name']}**: Sucl: {ts['success_rate']} │ Fail: {ts['errors'] + ts['restrictions']} │ {status}"
                    )
                
                if token_lines:
                    embed.add_field(
                        name="🔑 Apify Token Rotation",
                        value="\n".join(token_lines),
                        inline=False
                    )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── EDIT VIEWS (Manual) ───────────────────────────
    @app_commands.command(name="edit_views", description="Admin: Manually edit views for a user's video")

    @app_commands.describe(user="The user whose video views to edit")
    @owner_only()
    @app_commands.default_permissions(administrator=True)
    async def edit_views(self, interaction: discord.Interaction, user: discord.User):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        # Permission is handled by @owner_only() decorator

        # Fetch all videos for this user (not just tracking — include all)
        print(f"[DEBUG edit_views] Fetching videos for user {user.id} ({type(user.id)})")
        videos = await self.db.get_user_videos(str(user.id))
        print(f"[DEBUG edit_views] Fetched {len(videos)} videos")
        if not videos:
            await interaction.followup.send(
                f"❌ No videos found for <@{user.id}>.", ephemeral=True
            )
            return

        # Build video list with current views
        import aiosqlite
        video_options = []
        video_data = {}  # Map value -> video info

        for v in videos[:25]:  # Discord select max 25 options
            video_id = v['id']
            url = v['video_url']
            status = v.get('status', 'unknown')

            # Get current views from latest snapshot
            latest = await self.db.get_latest_metrics(video_id)
            current_views = latest.get('views', 0) if latest else 0
            current_likes = latest.get('likes', 0) if latest else 0
            current_comments = latest.get('comments', 0) if latest else 0

            # Also check final views if it somehow got marked as such
            if v.get('is_final'):
                current_views = v.get('final_views', current_views) or current_views
                current_likes = v.get('final_likes', current_likes) or current_likes
                current_comments = v.get('final_comments', current_comments) or current_comments

            # Extract shortcode for display
            shortcode = url.split('/reel/')[-1].split('/')[0].split('?')[0] if '/reel/' in url else url[-25:]
            label = f"📊 {current_views:,} views — .../{shortcode}"
            if len(label) > 100:
                label = label[:97] + "..."

            description = f"👍 {current_likes:,} likes │ 💬 {current_comments:,} comments │ {status}"
            if len(description) > 100:
                description = description[:97] + "..."

            key = str(video_id)
            video_data[key] = {
                'id': video_id,
                'url': url,
                'shortcode': shortcode,
                'views': current_views,
                'likes': current_likes,
                'comments': current_comments,
                'status': status,
            }
            video_options.append(
                discord.SelectOption(
                    label=label,
                    description=description,
                    value=key
                )
            )

        # Create the select view
        view = VideoSelectView(self.db, user, video_data, video_options)
        embed = discord.Embed(
            title=f"✏️ Edit Views — {user.display_name}",
            description=f"Select a video from <@{user.id}> to edit its views.\n\n"
                        f"**{len(video_options)}** video(s) found.",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class VideoSelectView(discord.ui.View):
    """Dropdown to select which video to edit, and button for overall totals."""

    def __init__(self, db, user: discord.User, video_data: dict, options: list):
        super().__init__(timeout=120)
        self.db = db
        self.user = user
        self.video_data = video_data

        select = discord.ui.Select(
            placeholder="Select a specific video to edit...",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )
        select.callback = self.on_select
        self.add_item(select)

    @discord.ui.button(label="✏️ Edit Overall Totals (All-time)", style=discord.ButtonStyle.secondary, row=1)
    async def edit_overall(self, interaction: discord.Interaction, button: discord.ui.Button):
        stats = await self.db.get_user_all_time_stats(str(self.user.id))
        modal = EditOverallStatsModal(self.db, self.user, stats)
        await interaction.response.send_modal(modal)

    async def on_select(self, interaction: discord.Interaction):
        selected_key = interaction.data['values'][0]
        video = self.video_data.get(selected_key)
        if not video:
            await interaction.response.send_message("❌ Video not found.", ephemeral=True)
            return

        # Open modal with current values pre-filled
        modal = EditViewsModal(self.db, video, self.user)
        await interaction.response.send_modal(modal)


class EditOverallStatsModal(discord.ui.Modal):
    """Modal to edit the user's total counts across everywhere."""

    def __init__(self, db, user: discord.User, stats: dict):
        super().__init__(title=f"Edit Overall — {user.display_name}")
        self.db = db
        self.user = user

        self.views_input = discord.ui.TextInput(
            label="Total All-time Views",
            placeholder="Enter desired total overall views",
            default=str(stats['total_views']),
            required=True
        )
        self.likes_input = discord.ui.TextInput(
            label="Total All-time Likes",
            placeholder="Enter desired total overall likes",
            default=str(stats['total_likes']),
            required=True
        )
        self.add_item(self.views_input)
        self.add_item(self.likes_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_total_views = int(self.views_input.value.replace(',', '').strip())
            new_total_likes = int(self.likes_input.value.replace(',', '').strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid number.", ephemeral=True)
            return

        success = await self.db.set_user_overall_stats(str(self.user.id), new_total_views, new_total_likes)
        
        if success:
            embed = discord.Embed(
                title="✅ Overall Stats Adjusted",
                description=f"User <@{self.user.id}> stats updated directly in database.\n"
                            f"Leaderboards and exports will reflect this immediately.",
                color=discord.Color.gold()
            )
            embed.add_field(name="New Total Views", value=f"{new_total_views:,}")
            embed.add_field(name="New Total Likes", value=f"{new_total_likes:,}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to update stats. User must be in at least one campaign.", ephemeral=True)



class EditViewsModal(discord.ui.Modal):
    """Modal to type new views/likes/comments values."""

    def __init__(self, db, video: dict, user: discord.User):
        super().__init__(title=f"Edit Views — .../{video['shortcode'][:30]}")
        self.db = db
        self.video = video
        self.user = user

        self.views_input = discord.ui.TextInput(
            label="Views",
            placeholder="Enter new view count",
            default=str(video['views']),
            required=True,
            style=discord.TextStyle.short
        )
        self.likes_input = discord.ui.TextInput(
            label="Likes",
            placeholder="Enter new likes count",
            default=str(video['likes']),
            required=False,
            style=discord.TextStyle.short
        )
        self.comments_input = discord.ui.TextInput(
            label="Comments",
            placeholder="Enter new comments count",
            default=str(video['comments']),
            required=False,
            style=discord.TextStyle.short
        )

        self.add_item(self.views_input)
        self.add_item(self.likes_input)
        self.add_item(self.comments_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_views = int(self.views_input.value.replace(',', '').strip())
            new_likes = int((self.likes_input.value or str(self.video['likes'])).replace(',', '').strip())
            new_comments = int((self.comments_input.value or str(self.video['comments'])).replace(',', '').strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number. Please enter numeric values only.", ephemeral=True
            )
            return

        old_views = self.video['views']
        old_likes = self.video['likes']
        old_comments = self.video['comments']

        # Save new snapshot
        await self.db.save_metric_snapshot(
            video_id=self.video['id'],
            views=new_views,
            likes=new_likes,
            comments=new_comments,
            extra_data="admin_manual_edit"
        )

        # IMPORTANT: Force update the video record metrics so it reflects in all-time stats/leaderboard
        await self.db.update_video_metrics(
            video_id=self.video['id'],
            views=new_views,
            likes=new_likes,
            comments=new_comments
        )


        print(f"[ADMIN] ✏️ Manual edit for video {self.video['id']} ({self.video['shortcode']}): "
              f"views {old_views:,} → {new_views:,}, "
              f"likes {old_likes:,} → {new_likes:,}, "
              f"comments {old_comments:,} → {new_comments:,}")

        embed = discord.Embed(
            title="✅ Views Updated",
            description=f"Video for <@{self.user.id}>: `.../{self.video['shortcode']}`",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Views",
            value=f"{old_views:,} → **{new_views:,}**",
            inline=True
        )
        embed.add_field(
            name="Likes",
            value=f"{old_likes:,} → **{new_likes:,}**",
            inline=True
        )
        embed.add_field(
            name="Comments",
            value=f"{old_comments:,} → **{new_comments:,}**",
            inline=True
        )
        embed.set_footer(text="Saved as new metric snapshot (admin_manual_edit)")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCommands(bot))

