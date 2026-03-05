"""
Campaign Analytics Discord Bot — Main Entry Point

Complete feature set:
  • Smart campaign creation with auto-generated IDs
  • User account linking for Instagram, TikTok, Twitter
  • Video submission with ownership verification
  • Automatic periodic scraping of tracked videos
  • Auto-stop system for budget/duration/views limits
  • Admin dashboard, leaderboard, detailed stats
  • Notification system with daily summaries

Setup:
  1. pip install -r requirements.txt
  2. playwright install chromium
  3. Add DISCORD_TOKEN to .env
  4. python bot.py
"""

import sys
import asyncio
import logging

# Suppress discord.py's noisy internal error logs — we handle everything ourselves
logging.getLogger('discord.app_commands.tree').setLevel(logging.CRITICAL)

# Prevent noisy asyncio pipe connection errors on Windows
if sys.platform == 'win32':
    import asyncio.proactor_events
    def silence_event_loop_closed(func):
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except (ConnectionResetError, OSError, RuntimeError):
                pass
        return wrapper
    asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = silence_event_loop_closed(
        asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost
    )
import discord
from discord.ext import commands

from config import DISCORD_TOKEN
from database.models import init_database
from config import DATABASE_PATH


class CampaignBot(commands.Bot):
    """Main bot class with cog and task loading."""

    def __init__(self):
        intents = discord.Intents.default()
        # intents.members = True  # Commented out to prevent PrivilegedIntentsRequired error

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None  # We use a custom /help command
        )

    async def setup_hook(self):
        """Load cogs and sync commands on startup."""
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("  Campaign Analytics Bot — Starting up...")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Initialize database
        await init_database(DATABASE_PATH)
        print("✅ Database initialized")

        # Initialize Apify tables (fixes missing columns)
        from services.apify_instagram import ApifyInstagramService
        apify_service = ApifyInstagramService()
        await apify_service.init_tables()
        print("[BOT] Apify database tables initialized")

        # Override tree error handler to suppress noisy "Ignoring exception" logs
        self.tree.on_error = self._tree_error_handler

        # Load command cogs
        cog_modules = [
            "cogs.admin_commands",
            "cogs.settings_commands",
            "cogs.account_commands",
            "cogs.campaign_commands",
            "cogs.submission_commands",
            "cogs.stats_commands",
            "cogs.dashboard_commands",
            "cogs.help_commands",
        ]

        for cog in cog_modules:
            try:
                await self.load_extension(cog)
                print(f"  ✅ Loaded: {cog}")
            except Exception as e:
                print(f"  ❌ Failed: {cog} — {e}")

        # Load background tasks
        task_modules = [
            "tasks.periodic_scraper",
            "tasks.campaign_monitor",
            "tasks.daily_summary",
        ]

        for task in task_modules:
            try:
                await self.load_extension(task)
                print(f"  ✅ Loaded: {task}")
            except Exception as e:
                print(f"  ❌ Failed: {task} — {e}")

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            print(f"✅ Synced {len(synced)} slash commands")
        except Exception as e:
            print(f"❌ Command sync error: {e}")

        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    async def on_ready(self):
        """Log bot connection info."""
        print(f"🟢 Bot online as {self.user} (ID: {self.user.id})")
        print(f"🌐 Serving {len(self.guilds)} guild(s)")

        # Set presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="campaigns | /help"
            )
        )

    async def on_command_error(self, ctx, error):
        """Global error handler for command prefixes (fallback)."""
        if isinstance(error, commands.CommandNotFound):
            return
        print(f"[ERROR] {type(error).__name__}: {error}")

    async def _tree_error_handler(self, interaction: discord.Interaction, error):
        """
        Custom tree-level error handler.
        This REPLACES discord.py's default tree.on_error which logs every error
        as 'Ignoring exception in command ...' at ERROR level. We handle
        everything silently and respond to the user instead.
        """
        # 1. Expired interactions (10062) — nothing to do
        if isinstance(error, discord.app_commands.errors.CommandInvokeError):
            if isinstance(error.original, discord.errors.NotFound) and error.original.code == 10062:
                return
            # Transient network errors
            err_name = type(error.original).__name__
            if err_name in ('ClientConnectorDNSError', 'ClientConnectorError',
                            'ClientOSError', 'ConnectionResetError', 'OSError'):
                print(f"[NETWORK] Transient error in {getattr(interaction.command, 'name', '?')}: {err_name}")
                return

        # 2. Permission denied — tell the user nicely
        if isinstance(error, discord.app_commands.errors.CheckFailure):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ You don't have permission for this command.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ You don't have permission for this command.",
                        ephemeral=True
                    )
            except:
                pass
        else:
            try:
                msg = f"❌ Error: {str(error)[:200]}"
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.followup.send(msg, ephemeral=True)
            except:
                pass

        print(f"[APP_ERROR] {type(error).__name__}: {error}")


def main():
    """Entry point."""
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN not found in .env file!")
        print("   Create a .env file with: DISCORD_TOKEN=your_token_here")
        return

    bot = CampaignBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
