"""Account commands: link_account, unlink_account, my_accounts.

Instagram accounts require bio-verification:
  1. /link_account platform:Instagram username:your_handle
     → Bot generates a CLIPTEA-XXXXXX code and sends it to the user
  2. User pastes the code into their Instagram bio
  3. User clicks the "✅ Verify Now" button
     → Bot scrapes the public bio and confirms the code is present
     → On success: account is marked as ✅ Verified

Multiple Instagram accounts per user are supported.
TikTok / Twitter remain one-account-per-platform (instant link).
"""
import random
import string
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from utils.formatters import platform_emoji
from utils.validators import validate_username
from utils.ig_bio_verifier import IGBioVerifier

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────

def _generate_code(length: int = 6) -> str:
    """Generate a short alphanumeric code like CLIPTEA-A3X9YZ."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=length))
    return f"CLIPTEA-{suffix}"


# ──────────────────────────────────────────────────
# Verification UI (buttons)
# ──────────────────────────────────────────────────

class VerifyView(discord.ui.View):
    """Interactive view with Verify Now and Cancel buttons."""

    def __init__(self, discord_user_id: str, username: str, code: str,
                 db: DatabaseManager, *, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.discord_user_id = discord_user_id
        self.username = username
        self.code = code
        self.db = db
        self.verifier = IGBioVerifier(timeout=20.0)

    # ── Verify Now ─────────────────────────────────
    @discord.ui.button(
        label="✅ Verify Now",
        style=discord.ButtonStyle.success,
        custom_id="ig_verify_now"
    )
    async def verify_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Only the original user may press the button
        if str(interaction.user.id) != self.discord_user_id:
            await interaction.response.send_message(
                "❌ This verification is not for you.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Check the code is still valid in DB
        pending = await self.db.get_pending_verification(
            self.discord_user_id, self.username
        )
        if not pending:
            await interaction.followup.send(
                "⚠️ Your verification code has **expired**.\n"
                "Run `/link_account` again to get a fresh code.",
                ephemeral=True
            )
            self._disable_all()
            await interaction.message.edit(view=self)
            return

        # Scrape the Instagram bio
        found = await self.verifier.check_bio(self.username, self.code)

        if found:
            # Link the account and mark verified
            await self.db.link_account(
                discord_user_id=self.discord_user_id,
                discord_username=str(interaction.user),
                platform="instagram",
                platform_username=self.username,
            )
            await self.db.mark_verified_by_code(self.discord_user_id, self.username)

            embed = discord.Embed(
                title="🎉 Instagram Account Verified!",
                description=(
                    f"**@{self.username}** has been linked and verified ✅\n\n"
                    "You can now remove the verification code from your bio."
                ),
                color=discord.Color.green()
            )
            embed.set_footer(text="Use /my_accounts to see all linked accounts.")

            self._disable_all()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await interaction.followup.send(embed=embed, ephemeral=True)

        else:
            embed = discord.Embed(
                title="❌ Code Not Found in Bio",
                description=(
                    f"The code **`{self.code}`** was **not found** in the bio of **@{self.username}**.\n\n"
                    "Please make sure you've:\n"
                    "1. Added the exact code to your Instagram bio\n"
                    "2. Saved your profile\n"
                    "3. Set your account to **Public** (private accounts can't be scraped)\n\n"
                    "Then click **Verify Now** again."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Cancel ─────────────────────────────────────
    @discord.ui.button(
        label="❌ Cancel",
        style=discord.ButtonStyle.danger,
        custom_id="ig_verify_cancel"
    )
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if str(interaction.user.id) != self.discord_user_id:
            await interaction.response.send_message(
                "❌ This verification is not for you.", ephemeral=True
            )
            return

        self._disable_all()
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.response.send_message(
            "🚫 Verification cancelled.", ephemeral=True
        )

    def _disable_all(self):
        for child in self.children:
            child.disabled = True

    async def on_timeout(self):
        self._disable_all()


# ──────────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────────

class AccountCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    # ── /link_account ──────────────────────────────
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
        clean_username = validate_username(username)
        if not clean_username:
            await interaction.response.send_message(
                "❌ Invalid username. Please provide your username without @.",
                ephemeral=True
            )
            return

        # ── Instagram: bio-verification flow ───────
        if platform.value == "instagram":
            await interaction.response.defer(ephemeral=True)

            code = _generate_code()
            await self.db.save_verification_code(
                discord_user_id=str(interaction.user.id),
                platform_username=clean_username,
                code=code,
                ttl_minutes=10,
            )

            # Pre-link the account as unverified so it shows up in my_accounts
            await self.db.link_account(
                discord_user_id=str(interaction.user.id),
                discord_username=str(interaction.user),
                platform="instagram",
                platform_username=clean_username,
            )

            embed = discord.Embed(
                title="📷 Instagram Account Verification",
                description=(
                    f"To link **@{clean_username}**, add the code below to your **Instagram bio**.\n"
                    "Once done, click **✅ Verify Now**."
                ),
                color=discord.Color.from_rgb(193, 53, 132)  # Instagram pink
            )
            embed.add_field(
                name="🔑 Your Verification Code",
                value=f"```{code}```",
                inline=False
            )
            embed.add_field(
                name="📋 Steps",
                value=(
                    "1. Open Instagram → Edit Profile\n"
                    "2. Paste the code into your **Bio** field\n"
                    "3. Save and come back\n"
                    "4. Click **✅ Verify Now** below"
                ),
                inline=False
            )
            embed.set_footer(text="⏳ Code expires in 10 minutes • You can remove it after verification")

            view = VerifyView(
                discord_user_id=str(interaction.user.id),
                username=clean_username,
                code=code,
                db=self.db,
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return

        # ── TikTok / Twitter: instant link ─────────
        await interaction.response.defer(ephemeral=False)

        await self.db.link_account(
            discord_user_id=str(interaction.user.id),
            discord_username=str(interaction.user),
            platform=platform.value,
            platform_username=clean_username
        )
        # Auto-verify non-Instagram platforms (trust user input)
        await self.db.verify_account(str(interaction.user.id), platform.value)

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
        _add_accounts_fields(embed, accounts)
        await interaction.followup.send(embed=embed)

    # ── /unlink_account ───────────────────────────
    @app_commands.command(name="unlink_account", description="Unlink a social media account")
    @app_commands.describe(
        platform="Platform to unlink",
        username="Instagram username to remove (required only for Instagram)"
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Instagram 📷", value="instagram"),
        app_commands.Choice(name="TikTok 🎵", value="tiktok"),
        app_commands.Choice(name="Twitter/X 🐦", value="twitter"),
    ])
    async def unlink_account(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        username: str = None,
    ):
        if platform.value == "instagram" and username:
            clean = validate_username(username)
            if not clean:
                await interaction.response.send_message(
                    "❌ Invalid username.", ephemeral=True
                )
                return
            success = await self.db.unlink_instagram_account(
                str(interaction.user.id), clean
            )
        else:
            success = await self.db.unlink_account(str(interaction.user.id), platform.value)

        if success:
            embed = discord.Embed(
                title="✅ Account Unlinked",
                description=(
                    f"{platform_emoji(platform.value)} **@{username or platform.name}** "
                    "has been unlinked."
                ),
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="⚠️ Not Found",
                description=f"You don't have that {platform.name} account linked.",
                color=discord.Color.orange()
            )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.errors.NotFound:
            pass

    # ── /my_accounts ──────────────────────────────
    @app_commands.command(name="my_accounts", description="View your linked social media accounts")
    async def my_accounts(self, interaction: discord.Interaction):
        accounts = await self.db.get_user_accounts(str(interaction.user.id))

        embed = discord.Embed(
            title="🔗 Your Linked Accounts",
            color=discord.Color.blue()
        )

        # Group accounts
        ig_accounts = [a for a in accounts if a['platform'] == 'instagram']
        other = {p: None for p in ('tiktok', 'twitter')}
        for acc in accounts:
            if acc['platform'] in other:
                other[acc['platform']] = acc

        # Instagram (multiple)
        ig_emoji = platform_emoji("instagram")
        if ig_accounts:
            lines = []
            for acc in ig_accounts:
                status = "✅ Verified" if acc.get('verified') else "⏳ Pending verification"
                lines.append(f"@{acc['platform_username']} — {status}")
            embed.add_field(
                name=f"{ig_emoji} Instagram",
                value="\n".join(lines),
                inline=False
            )
        else:
            embed.add_field(
                name=f"{ig_emoji} Instagram",
                value="Not linked — use `/link_account`",
                inline=False
            )

        # TikTok / Twitter (single)
        for plat, acc in other.items():
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
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.errors.NotFound:
            pass


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────

def _add_accounts_fields(embed: discord.Embed, accounts: list):
    """Add all linked accounts as embed fields (used in link_account success embed)."""
    embed.add_field(name="━━━ Your Linked Accounts ━━━", value="\u200b", inline=False)

    ig_accounts = [a for a in accounts if a['platform'] == 'instagram']
    other = {p: None for p in ('tiktok', 'twitter')}
    for acc in accounts:
        if acc['platform'] in other:
            other[acc['platform']] = acc

    # Instagram
    ig_emoji = platform_emoji("instagram")
    if ig_accounts:
        lines = [
            f"@{a['platform_username']} {'✅' if a.get('verified') else '⏳'}"
            for a in ig_accounts
        ]
        embed.add_field(
            name=f"{ig_emoji} Instagram", value="\n".join(lines), inline=True
        )
    else:
        embed.add_field(
            name=f"{ig_emoji} Instagram", value="Not linked", inline=True
        )

    for plat, acc in other.items():
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


async def setup(bot: commands.Bot):
    await bot.add_cog(AccountCommands(bot))
