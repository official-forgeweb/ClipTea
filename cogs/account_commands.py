"""Account commands: link_account, unlink_account, my_accounts."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from utils.formatters import platform_emoji
from utils.validators import validate_username


class AccountCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    @app_commands.command(name="link_account", description="Link your social media account")
    @app_commands.describe(
        platform="Social media platform",
        username="Your username on this platform (without @)"
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Instagram 📷", value="instagram"),
        app_commands.Choice(name="TikTok 🎵", value="tiktok"),
        app_commands.Choice(name="Twitter/X 🐦", value="twitter"),
    ])
    async def link_account(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        username: str
    ):
        await interaction.response.defer()

        clean_username = validate_username(username)
        if not clean_username:
            await interaction.followup.send(
                "❌ Invalid username. Please provide your username without @.",
                ephemeral=True
            )
            return

        # Save the link
        await self.db.link_account(
            discord_user_id=str(interaction.user.id),
            discord_username=str(interaction.user),
            platform=platform.value,
            platform_username=clean_username
        )

        # Mark as verified (we trust user-provided usernames for now;
        # actual verification happens during video submission)
        await self.db.verify_account(str(interaction.user.id), platform.value)

        # Get all linked accounts for display
        accounts = await self.db.get_user_accounts(str(interaction.user.id))

        embed = discord.Embed(
            title="✅ Account Linked",
            color=discord.Color.green()
        )

        embed.add_field(
            name=f"{platform_emoji(platform.value)} {platform.name}",
            value=f"@{clean_username} ✅",
            inline=False
        )

        # Show all linked accounts
        embed.add_field(name="━━━ Your Linked Accounts ━━━", value="\u200b", inline=False)

        all_platforms = {"instagram": None, "tiktok": None, "twitter": None}
        for acc in accounts:
            all_platforms[acc['platform']] = acc

        for plat, acc in all_platforms.items():
            emoji = platform_emoji(plat)
            if acc:
                status = "✅" if acc.get('verified') else "⏳"
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value=f"@{acc['platform_username']} {status}",
                    inline=True
                )
            else:
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value="Not linked",
                    inline=True
                )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="unlink_account", description="Unlink a social media account")
    @app_commands.describe(platform="Platform to unlink")
    @app_commands.choices(platform=[
        app_commands.Choice(name="Instagram 📷", value="instagram"),
        app_commands.Choice(name="TikTok 🎵", value="tiktok"),
        app_commands.Choice(name="Twitter/X 🐦", value="twitter"),
    ])
    async def unlink_account(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str]
    ):
        success = await self.db.unlink_account(str(interaction.user.id), platform.value)
        if success:
            embed = discord.Embed(
                title="✅ Account Unlinked",
                description=f"{platform_emoji(platform.value)} {platform.name} account has been unlinked.",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="⚠️ Not Found",
                description=f"You don't have a {platform.name} account linked.",
                color=discord.Color.orange()
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="my_accounts", description="View your linked social media accounts")
    async def my_accounts(self, interaction: discord.Interaction):
        accounts = await self.db.get_user_accounts(str(interaction.user.id))

        embed = discord.Embed(
            title="🔗 Your Linked Accounts",
            color=discord.Color.blue()
        )

        all_platforms = {"instagram": None, "tiktok": None, "twitter": None}
        for acc in accounts:
            all_platforms[acc['platform']] = acc

        for plat, acc in all_platforms.items():
            emoji = platform_emoji(plat)
            if acc:
                status = "✅ Verified" if acc.get('verified') else "⏳ Pending"
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value=f"@{acc['platform_username']} {status}",
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"{emoji} {plat.title()}",
                    value="Not linked — use `/link_account`",
                    inline=False
                )

        embed.set_footer(text=f"User: {interaction.user}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AccountCommands(bot))
