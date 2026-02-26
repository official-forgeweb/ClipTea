import asyncio
import discord
from discord.ext import commands
from config import DISCORD_TOKEN, DATABASE_PATH
from database.models import init_database

# 1. Create virtual environment
# python -m venv venv
# source venv/bin/activate  (Linux/Mac)
# venv\Scripts\activate     (Windows)
# 2. Install dependencies
# pip install -r requirements.txt
# 3. Install Playwright browser
# playwright install chromium
# 4. Create .env file with:
# DISCORD_TOKEN=your_bot_token_here
# TWITTER_BEARER_TOKEN=optional_twitter_token
# 5. Run the bot
# python bot.py
# 6. FIRST TIME: Slash commands take up to 1 hour to appear in Discord
#    For instant sync during development, sync to a specific guild:
#    await bot.tree.sync(guild=discord.Object(id=YOUR_SERVER_ID))

class CampaignBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
    
    async def setup_hook(self):
        # Initialize database
        await init_database(DATABASE_PATH)
        
        # Load cog extensions
        await self.load_extension("cogs.campaign_commands")
        await self.load_extension("cogs.fetch_commands")
        await self.load_extension("cogs.metrics_commands")
        
        # Sync slash commands with Discord
        await self.tree.sync()
        print("[BOT] Slash commands synced!")
    
    async def on_ready(self):
        print(f"[BOT] Logged in as {self.user.name}")
        print(f"[BOT] Bot is ready! Use /help in Discord")
        # Set bot status
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="campaign metrics"
            )
        )

bot = CampaignBot()

if __name__ == "__main__":
    if DISCORD_TOKEN == "your_bot_token_here" or not DISCORD_TOKEN:
        print("[ERROR] Please set a valid DISCORD_TOKEN in the .env file.")
    else:
        bot.run(DISCORD_TOKEN)
