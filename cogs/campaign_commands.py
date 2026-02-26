import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager

class CampaignCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
    
    @app_commands.command(name="create_campaign", description="Create a new tracking campaign")
    @app_commands.describe(
        campaign_id="Unique ID for the campaign, e.g. summer2024",
        name="Display name for the campaign",
        description="Optional description for the campaign"
    )
    async def create_campaign(
        self, 
        interaction: discord.Interaction,
        campaign_id: str,
        name: str,
        description: str = ""
    ):
        success = await self.db.create_campaign(campaign_id, name, description)
        if success:
            embed = discord.Embed(title="Campaign Created", description=f"Successfully created campaign: **{name}** (`{campaign_id}`)", color=discord.Color.blue())
        else:
            embed = discord.Embed(title="Error", description=f"Campaign ID `{campaign_id}` already exists.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="delete_campaign", description="Delete an existing campaign")
    @app_commands.describe(campaign_id="Campaign to delete")
    async def delete_campaign(self, interaction: discord.Interaction, campaign_id: str):
        success = await self.db.delete_campaign(campaign_id)
        if success:
            embed = discord.Embed(title="Campaign Deleted", description=f"Successfully deleted campaign `{campaign_id}`", color=discord.Color.blue())
        else:
            embed = discord.Embed(title="Error", description=f"Campaign `{campaign_id}` not found.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="list_campaigns", description="List all active campaigns")
    async def list_campaigns(self, interaction: discord.Interaction):
        campaigns = await self.db.get_all_campaigns()
        if not campaigns:
            embed = discord.Embed(title="Campaigns", description="No campaigns found.", color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
            return
            
        embed = discord.Embed(title="Active Campaigns", color=discord.Color.blue())
        for c in campaigns:
            embed.add_field(name=f"{c['name']} (`{c['id']}`)", value=c['description'] or "No description", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="add_user", description="Add a creator to track in a campaign")
    @app_commands.describe(
        campaign_id="Campaign to add user to",
        username="Creator's username without @",
        platform="Social media platform"
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Instagram 📷", value="instagram"),
        app_commands.Choice(name="TikTok 🎵", value="tiktok"),
        app_commands.Choice(name="Twitter/X 🐦", value="twitter"),
    ])
    async def add_user(
        self,
        interaction: discord.Interaction,
        campaign_id: str,
        username: str,
        platform: app_commands.Choice[str]
    ):
        campaign = await self.db.get_campaign(campaign_id)
        if not campaign:
            embed = discord.Embed(title="Error", description=f"Campaign `{campaign_id}` not found.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return
            
        success = await self.db.add_user(campaign_id, username, platform.value)
        if success:
            embed = discord.Embed(title="User Added", description=f"Added **@{username}** on **{platform.name}** to campaign `{campaign_id}`", color=discord.Color.green())
        else:
            embed = discord.Embed(title="Error", description=f"User **@{username}** is already in campaign `{campaign_id}` for **{platform.name}**.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove_user", description="Remove a user from a campaign")
    @app_commands.describe(
        campaign_id="Campaign ID",
        username="Username to remove",
        platform="Platform"
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Instagram", value="instagram"),
        app_commands.Choice(name="TikTok", value="tiktok"),
        app_commands.Choice(name="Twitter/X", value="twitter"),
    ])
    async def remove_user(self, interaction: discord.Interaction, campaign_id: str, username: str, platform: app_commands.Choice[str]):
        success = await self.db.remove_user(campaign_id, username, platform.value)
        if success:
            embed = discord.Embed(title="User Removed", description=f"Removed **@{username}** ({platform.name}) from campaign `{campaign_id}`", color=discord.Color.blue())
        else:
            embed = discord.Embed(title="Error", description=f"User **@{username}** ({platform.name}) not found in campaign `{campaign_id}`.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="list_users", description="List all users in a campaign")
    @app_commands.describe(campaign_id="Campaign to list users for")
    async def list_users(self, interaction: discord.Interaction, campaign_id: str):
        users = await self.db.get_campaign_users(campaign_id)
        if not users:
            embed = discord.Embed(title="Campaign Users", description=f"No users found in campaign `{campaign_id}`.", color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
            return
            
        embed = discord.Embed(title=f"Users in Campaign (`{campaign_id}`)", color=discord.Color.blue())
        
        platforms = {"instagram": [], "tiktok": [], "twitter": []}
        for u in users:
            platforms[u["platform"]].append(u["username"])
            
        for plat, handles in platforms.items():
            if handles:
                icon = "📷" if plat == "instagram" else "🎵" if plat == "tiktok" else "🐦"
                embed.add_field(name=f"{icon} {plat.title()}", value=", ".join([f"@{h}" for h in handles]), inline=False)
                
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(CampaignCommands(bot))
