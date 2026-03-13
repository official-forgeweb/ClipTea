import asyncio
import discord
from discord.ext import commands
import os
import sys

# Mock bot
class MockBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

async def main():
    bot = MockBot()
    
    # Add cogs path
    sys.path.append(os.getcwd())
    
    print("--- Loading AdminCommands ---")
    try:
        from cogs.admin_commands import AdminCommands
        await bot.add_cog(AdminCommands(bot))
        print("✅ AdminCommands loaded")
    except Exception as e:
        print(f"❌ Failed to load AdminCommands: {e}")
        import traceback
        traceback.print_exc()

    print("\n--- Loading AccountCommands ---")
    try:
        from cogs.account_commands import AccountCommands
        await bot.add_cog(AccountCommands(bot))
        print("✅ AccountCommands loaded")
    except Exception as e:
        print(f"❌ Failed to load AccountCommands: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
