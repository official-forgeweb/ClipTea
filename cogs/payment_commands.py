"""Payment commands: set_payment, my_payment."""
import discord
from discord import app_commands
from discord.ext import commands
import re
from database.manager import DatabaseManager

class PaymentCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    @app_commands.command(name="set_payment", description="Set your crypto payment address")
    @app_commands.describe(
        crypto_type="Type of cryptocurrency",
        address="Your ERC20 wallet address"
    )
    @app_commands.choices(crypto_type=[
        app_commands.Choice(name="USDT (ERC20)", value="USDT-ERC20"),
        app_commands.Choice(name="USDC (ERC20)", value="USDC-ERC20"),
    ])
    async def set_payment(
        self,
        interaction: discord.Interaction,
        crypto_type: str,
        address: str
    ):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        address = address.strip()
        
        # ERC20 address validation
        if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
            await interaction.followup.send(
                "❌ Invalid ERC20 address format. Must start with `0x` followed by 40 hex characters.",
                ephemeral=True
            )
            return


        await self.db.set_user_payment(str(interaction.user.id), crypto_type, address)
        
        embed = discord.Embed(
            title="✅ Payment Address Saved",
            description=f"Your payment details have been updated successfully.",
            color=discord.Color.green()
        )
        embed.add_field(name="Type", value=crypto_type, inline=True)
        embed.add_field(name="Address", value=f"`{address}`", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="my_payment", description="View your saved payment address")
    async def my_payment(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        payment = await self.db.get_user_payment(str(interaction.user.id))
        
        if not payment:
            await interaction.followup.send(
                "❌ You haven't set a payment address yet.\nUse `/set_payment` to set one.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="💰 My Payment Details",
            color=discord.Color.blue()
        )
        embed.add_field(name="Type", value=payment['crypto_type'], inline=True)
        embed.add_field(name="Address", value=f"`{payment['crypto_address']}`", inline=True)
        embed.set_footer(text=f"Last updated: {payment['updated_at']}")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PaymentCommands(bot))
