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
    @app_commands.default_permissions(administrator=True)
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
    @app_commands.default_permissions(administrator=True)
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
    @app_commands.default_permissions(administrator=True)
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
    @app_commands.default_permissions(administrator=True)
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
    @app_commands.default_permissions(administrator=True)
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
    @app_commands.default_permissions(administrator=True)
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
                    SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE IFNULL(latest.views, 0) END) as account_views,
                    up.crypto_type,
                    up.crypto_address
                FROM submitted_videos sv
                LEFT JOIN (
                    SELECT video_id, views, MAX(id)
                    FROM metric_snapshots
                    GROUP BY video_id
                ) latest ON sv.id = latest.video_id
                LEFT JOIN user_payments up ON sv.discord_user_id = up.discord_user_id
                WHERE sv.campaign_id = ? AND sv.status != 'deleted'
                GROUP BY sv.discord_user_id, sv.platform, sv.author_username
                ORDER BY sv.discord_user_id, account_views DESC
            """
            async with db.execute(query, (campaign_id,)) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]

        if not rows:
            await interaction.followup.send("❌ No data found for this campaign.", ephemeral=True)
            return

        # 2. Process data for summary and CSV
        user_data = {}
        total_campaign_views = 0
        
        for row in rows:
            uid = row['discord_user_id']
            views = row['account_views']
            total_campaign_views += views
            
            if uid not in user_data:
                user_data[uid] = {
                    'accounts': [],
                    'total_views': 0,
                    'crypto_type': row['crypto_type'] or "Not Set",
                    'crypto_address': row['crypto_address'] or "N/A"
                }
            
            user_data[uid]['accounts'].append({
                'platform': row['platform'],
                'username': row['author_username'],
                'views': views
            })
            user_data[uid]['total_views'] += views

        # 3. Create Summary Embed
        embed = discord.Embed(
            title=f"📋 Export Summary: {campaign['name']}",
            description=f"**ID:** `{campaign_id}`\n**Rate:** ${rate}/10k views",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="👥 Total Clippers", value=str(len(user_data)), inline=True)
        embed.add_field(name="👁️ Total Views", value=format_number(total_campaign_views), inline=True)
        embed.add_field(name="💰 Total Payout", value=format_currency(calculate_earnings(total_campaign_views, rate)), inline=True)

        # Show top users or first few if many
        summary_text = ""
        # Sort users by total views
        sorted_users = sorted(user_data.items(), key=lambda x: x[1]['total_views'], reverse=True)
        
        for uid, data in sorted_users[:15]: # Show top 15 in embed
            earned = calculate_earnings(data['total_views'], rate)
            acc_list = ", ".join([f"@{a['username']} ({format_number(a['views'])})" for a in data['accounts']])
            
            summary_text += f"👤 <@{uid}>\n"
            summary_text += f"└ 🔗 {acc_list}\n"
            summary_text += f"└ 💵 Earned: **{format_currency(earned)}** ({format_number(data['total_views'])} views)\n\n"

        if not summary_text:
            summary_text = "No submission data available."
            
        if len(user_data) > 15:
            summary_text += f"*...and {len(user_data) - 15} more clippers in the CSV file.*"

        # Discord embed limits
        if len(summary_text) > 4000:
            summary_text = summary_text[:3900] + "\n\n*(Summary truncated, see CSV for full details)*"
            
        embed.add_field(name="📊 Clipper Breakdown", value=summary_text, inline=False)

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
                    'Discord ID', 'Total Views', 'Earnings ($)', 
                    'Crypto Type', 'Address', 'Account Breakdown'
                ]
                writer = csv.DictWriter(output, fieldnames=headers)
                writer.writeheader()
                
                for uid_str, d in sorted(self.data.items(), key=lambda x: x[1]['total_views'], reverse=True):
                    # Format accounts for CSV: "IG: @user (50k), TT: @user2 (20k)"
                    breakdown = ", ".join([
                        f"{a['platform'].upper()}: @{a['username']} ({a['views']})" 
                        for a in d['accounts']
                    ])
                    
                    writer.writerow({
                        'Discord ID': uid_str,
                        'Total Views': d['total_views'],
                        'Earnings ($)': f"{calculate_earnings(d['total_views'], self.rate):.2f}",
                        'Crypto Type': d['crypto_type'],
                        'Address': d['crypto_address'],
                        'Account Breakdown': breakdown
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

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCommands(bot))
