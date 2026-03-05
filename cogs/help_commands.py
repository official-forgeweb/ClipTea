"""Help command showing categorized command list — role-aware."""
import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import is_admin


class HelpCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available bot commands")
    async def help_command(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        try:
            # Check if the user is an admin
            user_is_admin = False
            try:
                user_is_admin = await is_admin(interaction)
            except Exception:
                pass
    
            embed = discord.Embed(
                title="📖 CAMPAIGN BOT — COMMAND GUIDE",
                description="Manage campaigns, track videos, and earn from your clips!",
                color=discord.Color.blue()
            )
    
            # ── Admin-only section (visible only to admins) ──
            if user_is_admin:
                embed.add_field(
                    name="🔧 ADMIN COMMANDS",
                    value=(
                        "`/create_campaign` — Create a new campaign\n"
                        "`/update_campaign` — Edit campaign settings\n"
                        "`/end_campaign` — End a campaign manually\n"
                        "`/delete_campaign` — Delete a campaign\n"
                        "`/settings view` — View global settings\n"
                        "`/settings update` — Update global settings\n"
                        "`/dashboard` — Admin overview of all campaigns\n"
                        "`/set_notification_channel` — Set notification channel\n"
                        "`/set_daily_summary` — Configure daily reports"
                    ),
                    inline=False
                )
    
            # ── Clipper commands (always visible) ──
            embed.add_field(
                name="👤 CLIPPER COMMANDS",
                value=(
                    "`/link_account` — Link your social media account\n"
                    "`/unlink_account` — Unlink an account\n"
                    "`/my_accounts` — View linked accounts\n"
                    "`/join` — Join a campaign\n"
                    "`/leave` — Leave a campaign\n"
                    "`/submit` — Submit a video for tracking\n"
                    "`/my_videos` — View your submitted videos\n"
                    "`/my_campaigns` — View campaigns you're in"
                ),
                inline=False
            )
    
            embed.add_field(
                name="📊 STATS COMMANDS",
                value=(
                    "`/stats` — View your complete stats\n"
                    "`/leaderboard` — Campaign leaderboard\n"
                    "`/campaign_statistics` — Campaign overview\n"
                    "`/video_details` — Detailed video metrics\n"
                    "`/list_campaigns` — List all campaigns"
                ),
                inline=False
            )
    
            embed.add_field(
                name="🗑️ OTHER COMMANDS",
                value=(
                    "`/delete_video` — Remove a video from tracking\n"
                    "`/help` — Show this help message"
                ),
                inline=False
            )
    
            embed.set_footer(text="💡 Tip: Start by linking your account with /link_account, then join a campaign with /join!")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.errors.NotFound:
            pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCommands(bot))
