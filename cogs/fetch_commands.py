import discord
from discord import app_commands
from discord.ext import commands
from campaign.manager import CampaignManager
from database.manager import DatabaseManager

class FetchCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.campaign_mgr = CampaignManager(self.db)
        
    async def cog_load(self):
        """Initializes proxies for campaign manager."""
        await self.campaign_mgr.initialize()
    
    @app_commands.command(name="fetch_campaign_data", description="Fetch fresh metrics for all users in a campaign")
    @app_commands.describe(campaign_id="Campaign to fetch fresh data for")
    async def fetch_campaign_data(self, interaction: discord.Interaction, campaign_id: str):
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            await interaction.response.send_message(f"❌ Campaign `{campaign_id}` not found.", ephemeral=True)
            return
            
        # Acknowledge the interaction to prevent timeout
        await interaction.response.defer()
        
        # Progress message
        msg = await interaction.followup.send(embed=discord.Embed(
            title="⏳ Fetching Campaign Data", 
            description="Initializing scrapers... This may take a while.",
            color=discord.Color.gold()
        ), wait=True)
        
        async def progress_callback(status_text: str):
            await msg.edit(embed=discord.Embed(
                title="⏳ Fetching Campaign Data", 
                description=status_text,
                color=discord.Color.gold()
            ))

        result = await self.campaign_mgr.fetch_campaign_data(campaign_id, progress_callback)
        
        if result["success"]:
            summary = result["summary"]
            embed = discord.Embed(
                title="✅ Fetch Complete",
                description=f"Successfully processed {summary['successful_users']}/{summary['total_users']} users.",
                color=discord.Color.green()
            )
            embed.add_field(name="New Posts Found", value=str(summary['total_posts_found']))
            if summary['errors']:
                error_text = "\n".join(summary['errors'][:5])
                if len(summary['errors']) > 5:
                    error_text += f"\n...and {len(summary['errors']) - 5} more errors."
                embed.add_field(name="Errors encountered", value=error_text, inline=False)
            
            await msg.edit(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Fetch Failed",
                description=result.get("message", "Unknown error occurred."),
                color=discord.Color.red()
            )
            await msg.edit(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(FetchCommands(bot))
