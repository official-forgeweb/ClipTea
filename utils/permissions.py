"""Admin permission check decorators for Discord commands."""
import discord
from discord import app_commands
from database.manager import DatabaseManager


async def is_admin(interaction: discord.Interaction) -> bool:
    """Check if a user has admin role or is server owner."""
    # Server owner always has admin
    if interaction.guild and interaction.user.id == interaction.guild.owner_id:
        return True

    # Check for Discord Administrator permission
    try:
        if interaction.user.guild_permissions.administrator:
            return True
    except (AttributeError, Exception):
        pass

    # Check member roles directly via the interaction's resolved permissions
    try:
        permissions = interaction.permissions
        if permissions.administrator:
            return True
    except (AttributeError, Exception):
        pass

    # Check for configured admin role
    db = DatabaseManager()
    admin_role_id = await db.get_setting("admin_role_id")
    if admin_role_id and admin_role_id.strip():  # Ignore empty string
        try:
            role_id = int(admin_role_id)
            # Check if user has this role via interaction.user.roles (may need members intent)
            if hasattr(interaction.user, 'roles'):
                for role in interaction.user.roles:
                    if role.id == role_id:
                        return True
            # Fallback: check via guild
            if interaction.guild:
                role = interaction.guild.get_role(role_id)
                if role and role in getattr(interaction.user, 'roles', []):
                    return True
        except (ValueError, AttributeError):
            pass

    return False


def admin_only():
    """Decorator that restricts a command to admin users only."""
    async def predicate(interaction: discord.Interaction) -> bool:
        result = await is_admin(interaction)
        if not result:
            raise app_commands.errors.CheckFailure("Admin permissions required")
        return result
    return app_commands.check(predicate)


def owner_only():
    """Decorator that restricts a command to the IDs defined in BOT_OWNER_ID in .env."""
    async def predicate(interaction: discord.Interaction) -> bool:
        import os
        # Prioritize BOT_OWNER_ID from .env
        owner_ids = [x.strip() for x in os.getenv("BOT_OWNER_ID", "").split(",") if x.strip()]
        
        # If not set in .env, fallback to guild owner for safety
        if not owner_ids:
            if interaction.guild and interaction.user.id == interaction.guild.owner_id:
                return True
            raise app_commands.errors.CheckFailure("This command is restricted to the bot owner.")

        if str(interaction.user.id) in owner_ids:
            return True
            
        raise app_commands.errors.CheckFailure("This command is restricted to the bot owner.")
    return app_commands.check(predicate)

