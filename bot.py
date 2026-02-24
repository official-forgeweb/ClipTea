import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import database as db

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

@bot.command(name="start_campaign", help="Creates a new campaign in the database.")
async def start_campaign(ctx, campaign_id: str, *, name: str):
    """
    Creates a new campaign so we can start tracking users.
    Example: !start_campaign camp_xyz My Awesome Campaign
    """
    success = db.add_campaign(campaign_id, name)
    if success:
         await ctx.send(f"✅ Campaign **{name}** (`{campaign_id}`) created successfully!")
    else:
         await ctx.send(f"❌ A campaign with the ID `{campaign_id}` already exists.")

@bot.command(name="add_user", help="Adds a user to a campaign.")
async def add_user(ctx, campaign_id: str, discord_user: discord.Member, tg_handle: str="None", tiktok_handle: str="None", ig_handle: str="None"):
    """
    Adds a Discord member to an existing campaign so the bot knows to fetch their metrics.
    Example: !add_user camp_xyz @User TwitterHandle TikTokHandle IGHandle
    """
    # Check if campaign exists
    if not db.get_campaign(campaign_id):
          await ctx.send(f"❌ Campaign `{campaign_id}` does not exist. Create it first using `!start_campaign`.")
          return

    # In a real scenario we might map their discord user ID. Here we auto create an ID.
    user_unique_id = f"{campaign_id}_{discord_user.id}"
    
    success = db.add_user(
        user_id=user_unique_id, 
        discord_id=str(discord_user.id), 
        campaign_id=campaign_id,
        twitter=tg_handle if tg_handle != "None" else None,
        tiktok=tiktok_handle if tiktok_handle != "None" else None,
        instagram=ig_handle if ig_handle != "None" else None
    )

    if success:
         await ctx.send(f"✅ Added {discord_user.mention} to campaign `{campaign_id}`!")
    else:
         await ctx.send(f"❌ User is already registered in this campaign.")


@bot.command(name="fetch_campaign_data", help="Initiates data fetching for a specific campaign.")
async def fetch_campaign_data(ctx, campaign_id: str):
    """
    Fetch data for a specific ongoing campaign.
    Example: !fetch_campaign_data camp_xyz
    """
    # Check if campaign exists
    if not db.get_campaign(campaign_id):
          await ctx.send(f"❌ Campaign `{campaign_id}` does not exist.")
          return

    await ctx.send(f"⏳ Initiating data fetch for campaign: **{campaign_id}**...")
    
    users = db.get_users_in_campaign(campaign_id)
    if not users:
         await ctx.send(f"⚠️ No users found in campaign `{campaign_id}`. Add users first!")
         return
    
    # Simulate API fetching delays and results for each user
    import asyncio
    import random
    
    for user in users:
        # database tuple order: id, discord_id, campaign_id, twitter, tiktok, ig
        uid = user[0]
        twitter_handle = user[3]
        tiktok_handle = user[4]
        ig_handle = user[5]

        # Simulate fetching data platform by platform
        if twitter_handle:
            await asyncio.sleep(1) # simulate API wait
            db.add_metric(uid, campaign_id, "twitter", f"https://x.com/{twitter_handle}/status/random", random.randint(100,500), random.randint(10,50))
        if tiktok_handle:
            await asyncio.sleep(1)
            db.add_metric(uid, campaign_id, "tiktok", f"https://tiktok.com/@{tiktok_handle}/video/random", random.randint(1000,5000), random.randint(100,500))
        if ig_handle:
            await asyncio.sleep(1)
            db.add_metric(uid, campaign_id, "instagram", f"https://instagram.com/p/random", random.randint(500,2000), random.randint(50,200))
            
    await ctx.send(f"✅ Data fetched & stored successfully for **{len(users)} users** in **{campaign_id}**.")

@bot.command(name="get_user_metrics", help="Retrieves and displays metrics for a user.")
async def get_user_metrics(ctx, campaign_id: str, discord_user: discord.Member):
    """
    Retrieve and display metrics across all supported platforms for a given user in a campaign.
    Example: !get_user_metrics camp_xyz @User
    """
    user_unique_id = f"{campaign_id}_{discord_user.id}"
    
    await ctx.send(f"📊 Fetching metrics for {discord_user.mention}...")
    
    metrics = db.get_user_metrics_summary(user_unique_id)
    
    if not metrics:
         await ctx.send("❌ No metrics found for this user. Have you fetched data recently?")
         return

    embed = discord.Embed(title=f"User Metrics: {discord_user.display_name}", color=discord.Color.blue())
    
    platform_names = {
        "instagram": "Instagram",
        "twitter": "X (Twitter)",
        "tiktok": "TikTok"
    }

    # metrics structure: [(platform, sum_views, sum_likes), ...]
    for record in metrics:
        platform_db_name, views, likes = record
        name = platform_names.get(platform_db_name, platform_db_name.capitalize())
        embed.add_field(name=name, value=f"Views: {views} | Likes: {likes}", inline=False)
        
    await ctx.send(embed=embed)

@bot.command(name="campaign_statistics", help="Displays overall statistics for a campaign.")
async def campaign_statistics(ctx, campaign_id: str):
    """
    Fetch comprehensive metrics (views, likes, etc.) collectively for a specific campaign.
    Example: !campaign_statistics camp_xyz
    """
    campaign = db.get_campaign(campaign_id)
    if not campaign:
          await ctx.send(f"❌ Campaign `{campaign_id}` does not exist.")
          return

    summary = db.get_campaign_metrics_summary(campaign_id)
    # structure: (active_users, total_views, total_likes)

    if not summary or summary[0] == 0:
        await ctx.send(f"⚠️ No metrics exist for `{campaign_id}`. Run `!fetch_campaign_data` first.")
        return

    active_users, total_views, total_likes = summary

    # Default to 0 if columns are null
    total_views = total_views or 0
    total_likes = total_likes or 0

    embed = discord.Embed(title=f"Campaign Summary: {campaign[1]}", color=discord.Color.green())
    embed.description = "Here is the compiled data for the requested campaign."
    embed.add_field(name="Total Views", value=f"{total_views:,}", inline=True)
    embed.add_field(name="Total Likes", value=f"{total_likes:,}", inline=True)
    embed.add_field(name="Active Users", value=f"{active_users}", inline=True)

    await ctx.send(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN or TOKEN == "your_discord_bot_token_here":
        print("ERROR: Please set your DISCORD_TOKEN inside the .env file")
    else:
        bot.run(TOKEN)
