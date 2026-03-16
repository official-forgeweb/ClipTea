import discord
from discord.ext import commands
from discord import app_commands

class DebugCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="debug_db", description="Debug prints the active database path")
    async def debug_db(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Active DB path is: {self.bot.db.db_path}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(DebugCog(bot))
