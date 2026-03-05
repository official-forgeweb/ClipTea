"""Dashboard command for admins showing overview of all campaigns."""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from database.manager import DatabaseManager
from campaign.payment_calculator import calculate_earnings, budget_percentage_used
from utils.permissions import admin_only
from utils.formatters import (
    format_number, format_currency, format_timestamp, status_emoji, progress_bar
)


class DashboardCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    @app_commands.command(name="dashboard", description="Admin overview of all campaigns")
    @admin_only()
    async def dashboard(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            return
            
        try:
            active = await self.db.get_campaigns_by_status("active")
            paused = await self.db.get_campaigns_by_status("paused")
            completed = await self.db.get_campaigns_by_status("completed")
    
            embed = discord.Embed(
                title="📊 ADMIN DASHBOARD",
                color=discord.Color.gold()
            )
    
            embed.add_field(
                name="Campaign Overview",
                value=(
                    f"🟢 Active: **{len(active)}**\n"
                    f"⏸️ Paused: **{len(paused)}**\n"
                    f"✅ Completed: **{len(completed)}**"
                ),
                inline=False
            )
    
            # Active campaigns detail
            for campaign in active[:5]:
                stats = await self.db.get_campaign_statistics(campaign['id'])
                member_count = await self.db.get_campaign_member_count(campaign['id'])
                video_count = await self.db.get_campaign_video_count(campaign['id'])
    
                rate = campaign.get('rate_per_10k_views', 10.0)
                total_views = stats.get('grand_total_views', 0)
                total_earned = calculate_earnings(total_views, rate)
    
                info = (
                    f"👥 {member_count} clippers │ 📹 {video_count} videos │ "
                    f"👁️ {format_number(total_views)} views\n"
                )
    
                # Budget info
                budget = campaign.get('budget')
                if budget:
                    pct = budget_percentage_used(budget, total_views, rate)
                    info += f"💰 Budget: {format_currency(total_earned)}/{format_currency(budget)} ({pct:.1f}%) {progress_bar(total_earned, budget, 12)}\n"
    
                    if pct >= 90:
                        info += "⚠️ Budget almost exhausted!\n"
                else:
                    info += "💰 Budget: Unlimited\n"
    
                # Duration info
                duration_days = campaign.get('duration_days')
                if duration_days:
                    try:
                        created = datetime.fromisoformat(campaign['created_at'].replace('Z', '+00:00'))
                        elapsed = (datetime.now() - created.replace(tzinfo=None)).days
                        info += f"⏱️ Duration: Day {elapsed}/{duration_days}\n"
                    except (ValueError, AttributeError):
                        info += f"⏱️ Duration: {duration_days} days\n"
                else:
                    try:
                        created = datetime.fromisoformat(campaign['created_at'].replace('Z', '+00:00'))
                        elapsed = (datetime.now() - created.replace(tzinfo=None)).days
                        info += f"⏱️ Duration: Day {elapsed}/∞\n"
                    except (ValueError, AttributeError):
                        info += "⏱️ Duration: Unlimited\n"
    
                embed.add_field(
                    name=f"🟢 {campaign['name']} (`{campaign['id']}`)",
                    value=info,
                    inline=False
                )
    
            if len(active) > 5:
                embed.add_field(
                    name="",
                    value=f"*...and {len(active) - 5} more active campaigns*",
                    inline=False
                )
    
            # Scrape info
            interval = await self.db.get_setting("scrape_interval_minutes") or "60"
            notifications = await self.db.get_recent_notifications(limit=1)
            last_scrape = "Never"
            if notifications:
                for n in notifications:
                    if n.get('type') == 'scrape_complete':
                        last_scrape = format_timestamp(n.get('sent_at', ''))
                        break
    
            embed.add_field(
                name="🔧 System Info",
                value=(
                    f"📡 Last scrape: {last_scrape}\n"
                    f"🔄 Scrape interval: {interval} minutes\n"
                ),
                inline=False
            )
    
            embed.set_footer(text=f"Dashboard generated: {datetime.now().strftime('%I:%M %p')}")
            await interaction.followup.send(embed=embed)
        except discord.errors.NotFound:
            pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(DashboardCommands(bot))
