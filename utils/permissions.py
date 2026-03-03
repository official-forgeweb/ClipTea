"""Admin permission check decorators for Discord commands."""
import discord
from discord import app_commands
from database.manager import DatabaseManager


async def is_admin(interaction: discord.Interaction) -> bool:
    """Check if a user has admin role or is server owner."""
    # Server owner always has admin
    if interaction.user.id == interaction.guild.owner_id:
        return True

    # Check for configured admin role
    db = DatabaseManager()
    admin_role_id = await db.get_setting("admin_role_id")
    if admin_role_id:
        try:
            role = interaction.guild.get_role(int(admin_role_id))
            if role and role in interaction.user.roles:
                return True
        except (ValueError, AttributeError):
            pass

    # Check for Discord Administrator permission
    if interaction.user.guild_permissions.administrator:
        return True

    return False


def admin_only():
    """Decorator that restricts a command to admin users only."""
    async def predicate(interaction: discord.Interaction) -> bool:
        result = await is_admin(interaction)
        if not result:
            raise app_commands.errors.CheckFailure("Admin permissions required")
        return result
    return app_commands.check(predicate)
