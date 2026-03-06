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
        address="Your wallet address"
    )
    @app_commands.choices(crypto_type=[
        app_commands.Choice(name="Ethereum (ETH) / ERC20", value="ETH"),
        app_commands.Choice(name="Bitcoin (BTC)", value="BTC"),
        app_commands.Choice(name="Solana (SOL)", value="SOL"),
        app_commands.Choice(name="USDT (ERC20)", value="USDT-ERC20"),
        app_commands.Choice(name="USDT (TRC20)", value="USDT-TRC20"),
        app_commands.Choice(name="Other", value="Other")
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
        
        # Basic validation
        is_valid = True
        error_msg = ""
        
        if crypto_type == "ETH" or crypto_type == "USDT-ERC20":
            if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
                is_valid = False
                error_msg = "Invalid Ethereum/ERC20 address format."
        elif crypto_type == "BTC":
            if not re.match(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$|^bc1[ac-hj-np-z02-9]{11,71}$", address):
                is_valid = False
                error_msg = "Invalid Bitcoin address format."
        elif crypto_type == "SOL":
            if not re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", address):
                is_valid = False
                error_msg = "Invalid Solana address format."
        
        if not is_valid:
            await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
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
