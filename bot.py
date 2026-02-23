import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environmental variables from the .env file
load_dotenv()

# Intents are required for Discord bots to receive specific events
intents = discord.Intents.default()
intents.message_content = True # Allow to read command messages

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    """Triggered when the bot is successfully connected to Discord."""
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")

@bot.command(name="fetch_campaign_data", help="Initiates data fetching for a specific campaign.")
async def fetch_campaign_data(ctx, campaign_id: str):
    """
    Fetch data for a specific ongoing campaign.
    Example: !fetch_campaign_data camp_xyz
    """
    await ctx.send(f"⏳ Initiating data fetch for campaign: **{campaign_id}**...")
    # TODO: Connect to SQLite DB later, fetch users in campaign and hit X/TikTok/IG APIs
    await ctx.send(f"✅ Data fetched successfully for **{campaign_id}** (placeholder).")

@bot.command(name="get_user_metrics", help="Retrieves and displays metrics for a user.")
async def get_user_metrics(ctx, user_id: str):
    """
    Retrieve and display metrics across all supported platforms for a given user.
    Example: !get_user_metrics user_123
    """
    await ctx.send(f"📊 Fetching metrics for User **{user_id}**...")
    # TODO: Fetch aggregate records from the database
    embed = discord.Embed(title=f"User Metrics: {user_id}", color=discord.Color.blue())
    embed.add_field(name="Instagram", value="Views: 0 | Likes: 0", inline=False)
    embed.add_field(name="X (Twitter)", value="Views: 0 | Likes: 0", inline=False)
    embed.add_field(name="TikTok", value="Views: 0 | Likes: 0", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="campaign_statistics", help="Displays overall statistics for a campaign.")
async def campaign_statistics(ctx, campaign_id: str):
    """
    Fetch comprehensive metrics (views, likes, etc.) collectively for a specific campaign.
    Example: !campaign_statistics camp_xyz
    """
    # TODO: Fetch collective summary from database
    embed = discord.Embed(title=f"Campaign Summary: {campaign_id}", color=discord.Color.green())
    embed.description = "Here is the compiled data for the requested campaign."
    embed.add_field(name="Total Views", value="0", inline=True)
    embed.add_field(name="Total Likes", value="0", inline=True)
    embed.add_field(name="Active Users", value="0", inline=True)

    await ctx.send(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN or TOKEN == "your_discord_bot_token_here":
        print("ERROR: Please set your DISCORD_TOKEN inside the .env file")
    else:
        bot.run(TOKEN)
