"""Settings commands: view/update global defaults, notification channel, daily summary."""
import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from utils.permissions import admin_only
from utils.formatters import format_currency


class SettingsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager()

    # ── SETTINGS GROUP ─────────────────────────────────
    settings_group = app_commands.Group(
        name="settings", 
        description="View or update global bot settings",
        default_permissions=discord.Permissions(administrator=True)
    )

    @settings_group.command(name="view", description="View current global default settings")
    @admin_only()
    async def settings_view(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except:
            return
        settings = await self.db.get_all_settings()

        embed = discord.Embed(
            title="⚙️ Global Default Settings",
            color=discord.Color.blue()
        )

        rate = settings.get('default_rate_per_10k', '10.00')
        embed.add_field(name="💵 Default Rate per 10K", value=f"${rate}", inline=True)

        duration = settings.get('default_duration_days', 'unlimited')
        embed.add_field(name="⏱️ Default Duration", value=f"{duration} days" if duration != 'unlimited' else "Unlimited", inline=True)

        budget = settings.get('default_budget', 'unlimited')
        embed.add_field(name="💰 Default Budget", value=f"${budget}" if budget != 'unlimited' else "Unlimited", inline=True)

        min_views = settings.get('default_min_views', '0')
        embed.add_field(name="👁️ Default Min Views", value=min_views, inline=True)

        max_views = settings.get('default_max_views', 'unlimited')
        embed.add_field(name="🔝 Default Max Views", value=max_views if max_views != 'unlimited' else "Unlimited", inline=True)

        interval = settings.get('scrape_interval_minutes', '60')
        embed.add_field(name="🔄 Scrape Interval", value=f"{interval} minutes", inline=True)

        admin_role_id = settings.get('admin_role_id', '')
        if admin_role_id:
            role = interaction.guild.get_role(int(admin_role_id))
            embed.add_field(name="🛡️ Admin Role", value=role.mention if role else f"ID: {admin_role_id}", inline=True)
        else:
            embed.add_field(name="🛡️ Admin Role", value="Not set", inline=True)

        notif_channel = settings.get('notification_channel_id', '')
        if notif_channel:
            embed.add_field(name="📡 Notification Channel", value=f"<#{notif_channel}>", inline=True)
        else:
            embed.add_field(name="📡 Notification Channel", value="Not set", inline=True)

        daily = settings.get('daily_summary_enabled', 'false')
        daily_time = settings.get('daily_summary_time', '09:00')
        embed.add_field(name="📅 Daily Summary", value=f"{'✅ Enabled' if daily == 'true' else '❌ Disabled'} at {daily_time}", inline=True)

        auto_stop = settings.get('default_auto_stop', 'true')
        embed.add_field(name="🛑 Global Auto-Stop", value="✅ Enabled" if auto_stop == 'true' else "❌ Disabled", inline=True)

        try:
            await interaction.followup.send(embed=embed)
        except Exception:
            pass

    @settings_group.command(name="update", description="Update global default settings")
    @app_commands.describe(
        default_rate_per_10k="Default payment rate per 10K views",
        default_duration_days="Default campaign duration in days (0 for unlimited)",
        default_budget="Default campaign budget (0 for unlimited)",
        default_min_views="Default minimum views to join",
        default_max_views="Default max views cap (0 for unlimited)",
        scrape_interval_minutes="Minutes between automatic scrapes",
        admin_role="Discord role that has admin access",
        auto_stop="Toggle whether new campaigns stop automatically by default"
    )
    @admin_only()
    async def settings_update(
        self,
        interaction: discord.Interaction,
        default_rate_per_10k: float = None,
        default_duration_days: int = None,
        default_budget: float = None,
        default_min_views: int = None,
        default_max_views: int = None,
        scrape_interval_minutes: int = None,
        admin_role: discord.Role = None,
        auto_stop: bool = None,
    ):
        try:
            await interaction.response.defer(ephemeral=True)
        except:
            return
        updated = []

        if default_rate_per_10k is not None:
            await self.db.set_setting("default_rate_per_10k", str(default_rate_per_10k))
            updated.append(f"💵 Rate: ${default_rate_per_10k}")

        if default_duration_days is not None:
            value = "unlimited" if default_duration_days == 0 else str(default_duration_days)
            await self.db.set_setting("default_duration_days", value)
            updated.append(f"⏱️ Duration: {value}")

        if default_budget is not None:
            value = "unlimited" if default_budget == 0 else str(default_budget)
            await self.db.set_setting("default_budget", value)
            updated.append(f"💰 Budget: {value}")

        if default_min_views is not None:
            await self.db.set_setting("default_min_views", str(default_min_views))
            updated.append(f"👁️ Min Views: {default_min_views}")

        if default_max_views is not None:
            value = "unlimited" if default_max_views == 0 else str(default_max_views)
            await self.db.set_setting("default_max_views", value)
            updated.append(f"🔝 Max Views: {value}")

        if scrape_interval_minutes is not None:
            await self.db.set_setting("scrape_interval_minutes", str(scrape_interval_minutes))
            updated.append(f"🔄 Scrape Interval: {scrape_interval_minutes}min")

        if admin_role is not None:
            await self.db.set_setting("admin_role_id", str(admin_role.id))
            updated.append(f"🛡️ Admin Role: {admin_role.mention}")

        if auto_stop is not None:
            await self.db.set_setting("default_auto_stop", "true" if auto_stop else "false")
            updated.append(f"🛑 Auto-Stop: {'✅ Enabled' if auto_stop else '❌ Disabled'}")

        if not updated:
            try:
                await interaction.followup.send("⚠️ No settings were changed.", ephemeral=True)
            except Exception:
                pass
            return

        embed = discord.Embed(
            title="✅ Settings Updated",
            description="\n".join(updated),
            color=discord.Color.green()
        )
        try:
            await interaction.followup.send(embed=embed)
        except Exception:
            pass

    # ── NOTIFICATION CHANNEL ───────────────────────────
    @app_commands.command(name="set_notification_channel", description="Set the channel for bot notifications")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        channel="Channel for bot notifications",
        notification_type="Type of notifications to send"
    )
    @app_commands.choices(notification_type=[
        app_commands.Choice(name="All Notifications", value="all"),
        app_commands.Choice(name="Admin Only", value="admin"),
        app_commands.Choice(name="Campaign Events", value="campaign"),
        app_commands.Choice(name="Errors Only", value="errors"),
    ])
    @admin_only()
    async def set_notification_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        notification_type: app_commands.Choice[str] = None,
    ):
        try:
            await interaction.response.defer(ephemeral=True)
        except:
            return
        await self.db.set_setting("notification_channel_id", str(channel.id))

        notif_type_value = notification_type.value if notification_type else "all"
        await self.db.set_setting("notification_type", notif_type_value)

        embed = discord.Embed(
            title="✅ Notification Channel Set",
            description=f"Notifications will be sent to {channel.mention}\nType: **{notif_type_value.title()}**",
            color=discord.Color.green()
        )
        try:
            await interaction.followup.send(embed=embed)
        except Exception:
            pass

    # ── DAILY SUMMARY ──────────────────────────────────
    @app_commands.command(name="set_daily_summary", description="Configure daily summary reports")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        enabled="Enable or disable daily summaries",
        time="Time to send (HH:MM format, e.g. 09:00)",
        channel="Channel to send daily summary to"
    )
    @admin_only()
    async def set_daily_summary(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        time: str = "09:00",
        channel: discord.TextChannel = None,
    ):
        try:
            await interaction.response.defer(ephemeral=True)
        except:
            return
        await self.db.set_setting("daily_summary_enabled", "true" if enabled else "false")
        await self.db.set_setting("daily_summary_time", time)

        if channel:
            await self.db.set_setting("notification_channel_id", str(channel.id))

        status = "✅ Enabled" if enabled else "❌ Disabled"
        embed = discord.Embed(
            title="📅 Daily Summary Updated",
            description=f"Status: {status}\nTime: **{time}**",
            color=discord.Color.green() if enabled else discord.Color.greyple()
        )
        if channel:
            embed.add_field(name="Channel", value=channel.mention)
        try:
            await interaction.followup.send(embed=embed)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCommands(bot))
