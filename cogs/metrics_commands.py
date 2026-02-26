import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager

class MetricsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()
        
    @app_commands.command(name="campaign_statistics", description="Show overall statistics for a campaign")
    @app_commands.describe(campaign_id="Campaign to show statistics for")
    async def campaign_statistics(self, interaction: discord.Interaction, campaign_id: str):
        stats = await self.db.get_campaign_statistics(campaign_id)
        campaign = await self.db.get_campaign(campaign_id)
        
        if not campaign:
            await interaction.response.send_message(f"❌ Campaign `{campaign_id}` not found.", ephemeral=True)
            return
            
        if not stats or stats.get("total_posts") == 0:
            embed = discord.Embed(
                title=f"📊 Statistics: {campaign['name']}",
                description="No data available yet. Run `/fetch_campaign_data` first.",
                color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(title=f"📊 Statistics: {campaign['name']}", color=discord.Color.gold())
        embed.add_field(name="Total Posts Tracked", value=f"{stats['total_posts']:,}", inline=False)
        embed.add_field(name="Total Views", value=f"{stats['total_views'] or 0:,}", inline=True)
        embed.add_field(name="Total Likes", value=f"{stats['total_likes'] or 0:,}", inline=True)
        embed.add_field(name="Total Comments", value=f"{stats['total_comments'] or 0:,}", inline=True)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="get_user_metrics", description="Get metrics for a specific creator")
    @app_commands.describe(
        campaign_id="Campaign ID",
        username="Creator username"
    )
    async def get_user_metrics(self, interaction: discord.Interaction, campaign_id: str, username: str):
        stats = await self.db.get_user_metrics(campaign_id, username)
        
        if not stats or stats.get("total_posts") == 0:
            embed = discord.Embed(
                title=f"👤 Metrics: @{username}",
                description=f"No data available for @{username} in this campaign.",
                color=discord.Color.purple()
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(title=f"👤 Metrics: @{username}", color=discord.Color.purple())
        embed.add_field(name="Total Posts Tracked", value=f"{stats['total_posts']:,}", inline=False)
        embed.add_field(name="Total Views", value=f"{stats['total_views'] or 0:,}", inline=True)
        embed.add_field(name="Total Likes", value=f"{stats['total_likes'] or 0:,}", inline=True)
        embed.add_field(name="Total Comments", value=f"{stats['total_comments'] or 0:,}", inline=True)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="top_performers", description="List top performers in a campaign")
    @app_commands.describe(
        campaign_id="Campaign ID",
        limit="Number of performers to show (default 10)"
    )
    async def top_performers(self, interaction: discord.Interaction, campaign_id: str, limit: int = 10):
        performers = await self.db.get_top_performers(campaign_id, limit)
        
        if not performers:
            embed = discord.Embed(
                title=f"🏆 Top Performers (`{campaign_id}`)",
                description="No data available yet.",
                color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(title=f"🏆 Top Performers (`{campaign_id}`)", color=discord.Color.gold())
        
        for i, p in enumerate(performers, 1):
            icon = "📷" if p["platform"] == "instagram" else "🎵" if p["platform"] == "tiktok" else "🐦"
            embed.add_field(
                name=f"{i}. @{p['username']} {icon}",
                value=f"**{p['total_views']:,}** views | **{p['total_likes']:,}** likes | {p['total_posts']} posts",
                inline=False
            )
            
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(MetricsCommands(bot))
