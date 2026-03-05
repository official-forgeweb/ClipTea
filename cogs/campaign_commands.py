"""Campaign commands for clippers: join, leave, my_campaigns."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from utils.formatters import (
    format_number, format_currency, format_timestamp, status_emoji, platform_emoji
)
from campaign.payment_calculator import calculate_earnings


class CampaignCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    @app_commands.command(name="join", description="Join a campaign as a clipper")
    @app_commands.describe(campaign_id="Campaign to join")
    async def join_campaign(self, interaction: discord.Interaction, campaign_id: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        try:
            # Check campaign exists and is active
            campaign = await self.db.get_campaign(campaign_id)
            if not campaign:
                await interaction.followup.send(
                    f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
                )
                return
    
            if campaign['status'] != 'active':
                await interaction.followup.send(
                    f"❌ Campaign `{campaign_id}` is not active (status: {campaign['status']}).",
                    ephemeral=True
                )
                return
    
            # Check if user has at least one linked account
            accounts = await self.db.get_user_accounts(str(interaction.user.id))
            if not accounts:
                await interaction.followup.send(
                    "❌ You need to link at least one social media account first.\n"
                    "Use `/link_account` to get started.",
                    ephemeral=True
                )
                return
    
            # Check platform compatibility
            campaign_platforms = campaign.get('platforms', 'all')
            if campaign_platforms != 'all':
                has_matching = any(acc['platform'] == campaign_platforms for acc in accounts)
                if not has_matching:
                    await interaction.followup.send(
                        f"❌ This campaign requires a **{campaign_platforms.title()}** account, "
                        f"but you don't have one linked.\nUse `/link_account` to link your {campaign_platforms.title()} account.",
                        ephemeral=True
                    )
                    return
    
            # Check already joined
            if await self.db.is_campaign_member(campaign_id, str(interaction.user.id)):
                await interaction.followup.send(
                    f"⚠️ You've already joined this campaign!", ephemeral=True
                )
                return
    
            # Join the campaign
            success = await self.db.join_campaign(campaign_id, str(interaction.user.id))
            if success:
                embed = discord.Embed(
                    title="✅ Joined Campaign!",
                    color=discord.Color.green()
                )
                embed.add_field(name="📋 Campaign", value=campaign['name'], inline=True)
                embed.add_field(name="🆔 ID", value=f"`{campaign_id}`", inline=True)
                embed.add_field(
                    name="💵 Rate",
                    value=f"{format_currency(campaign.get('rate_per_10k_views', 10))} per 10K views",
                    inline=True
                )
                embed.add_field(
                    name="📱 Platforms",
                    value=campaign.get('platforms', 'all').title(),
                    inline=True
                )
    
                linked = ", ".join([
                    f"{platform_emoji(a['platform'])} @{a['platform_username']}"
                    for a in accounts
                ])
                embed.add_field(name="🔗 Your Accounts", value=linked, inline=False)
                embed.add_field(
                    name="📹 Next Step",
                    value="Submit videos with `/submit`",
                    inline=False
                )
    
                await interaction.followup.send(embed=embed)
    
                # Send notification
                channel_id = await self.db.get_setting("notification_channel_id")
                if channel_id:
                    try:
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            notif = discord.Embed(
                                title="👋 New Clipper Joined",
                                description=f"<@{interaction.user.id}> joined **{campaign['name']}**",
                                color=discord.Color.green()
                            )
                            await channel.send(embed=notif)
                    except Exception:
                        pass
    
                await self.db.log_notification(
                    campaign_id=campaign_id,
                    notif_type="join",
                    message=f"{interaction.user} joined campaign"
                )
            else:
                await interaction.followup.send(
                    "❌ Failed to join campaign.", ephemeral=True
                )
        except discord.errors.NotFound:
            pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass

    @join_campaign.autocomplete("campaign_id")
    async def join_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            campaigns = await self.db.get_active_campaigns()
            return [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in campaigns
                if current.lower() in c['name'].lower() or current.lower() in c['id'].lower()
            ][:25]
        except Exception:
            return []

    @app_commands.command(name="leave", description="Leave a campaign")
    @app_commands.describe(campaign_id="Campaign to leave")
    async def leave_campaign(self, interaction: discord.Interaction, campaign_id: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return
            
        try:
            campaign = await self.db.get_campaign(campaign_id)
            if not campaign:
                await interaction.followup.send(
                    f"❌ Campaign `{campaign_id}` not found.", ephemeral=True
                )
                return
    
            success = await self.db.leave_campaign(campaign_id, str(interaction.user.id))
            if success:
                embed = discord.Embed(
                    title="👋 Left Campaign",
                    description=f"You have left **{campaign['name']}**.\nYour submitted videos will still be tracked.",
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    "❌ You're not an active member of this campaign.", ephemeral=True
                )
        except discord.errors.NotFound:
            pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass

    @leave_campaign.autocomplete("campaign_id")
    async def leave_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            user_campaigns = await self.db.get_user_campaigns(str(interaction.user.id))
            return [
                app_commands.Choice(name=f"{c['name']} ({c['id']})", value=c['id'])
                for c in user_campaigns
                if c.get('member_status') == 'active'
                and (current.lower() in c['name'].lower() or current.lower() in c['id'].lower())
            ][:25]
        except Exception:
            return []

    @app_commands.command(name="my_campaigns", description="View campaigns you are part of")
    async def my_campaigns(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            return
            
        try:
            user_campaigns = await self.db.get_user_campaigns(str(interaction.user.id))
    
            if not user_campaigns:
                embed = discord.Embed(
                    title="📋 My Campaigns",
                    description="You haven't joined any campaigns yet.\nUse `/join` to join a campaign!",
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed)
                return
    
            embed = discord.Embed(
                title="📋 My Campaigns",
                color=discord.Color.blue()
            )
    
            for c in user_campaigns[:10]:  # Limit to avoid embed size issues
                status = status_emoji(c.get('status', 'active'))
                member_status = c.get('member_status', 'active')
    
                # Get user's stats in this campaign
                stats = await self.db.get_user_campaign_stats(c['id'], str(interaction.user.id))
                rate = c.get('rate_per_10k_views', 10.0)
                earned = calculate_earnings(stats.get('total_views', 0), rate)
    
                value = (
                    f"**Status:** {status} {c.get('status', 'active').title()}"
                    f" | Member: {member_status.title()}\n"
                    f"📹 Videos: {stats.get('total_videos', 0)} │ "
                    f"👁️ Views: {format_number(stats.get('total_views', 0))} │ "
                    f"💵 Earned: {format_currency(earned)}\n"
                    f"Joined: {format_timestamp(c.get('member_joined_at', ''))}"
                )
    
                embed.add_field(
                    name=f"{c['name']} (`{c['id']}`)",
                    value=value,
                    inline=False
                )
    
            if len(user_campaigns) > 10:
                embed.set_footer(text=f"Showing 10 of {len(user_campaigns)} campaigns")
    
            await interaction.followup.send(embed=embed)
        except discord.errors.NotFound:
            pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass

    @app_commands.command(name="list_campaigns", description="List all campaigns")
    async def list_campaigns(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            return
            
        try:
            campaigns = await self.db.get_all_campaigns()
            if not campaigns:
                embed = discord.Embed(
                    title="📋 Campaigns",
                    description="No campaigns found.",
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed)
                return
    
            embed = discord.Embed(title="📋 All Campaigns", color=discord.Color.blue())
            for c in campaigns[:15]:
                status = status_emoji(c.get('status', 'active'))
                embed.add_field(
                    name=f"{status} {c['name']} (`{c['id']}`)",
                    value=(
                        f"Platforms: {c.get('platforms', 'all').title()} │ "
                        f"Rate: {format_currency(c.get('rate_per_10k_views', 10))}/10K │ "
                        f"Status: {c.get('status', 'active').title()}"
                    ),
                    inline=False
                )
    
            if len(campaigns) > 15:
                embed.set_footer(text=f"Showing 15 of {len(campaigns)} campaigns")
    
            await interaction.followup.send(embed=embed)
        except discord.errors.NotFound:
            pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(CampaignCommands(bot))
