"""Number formatting, embed builders, and display utilities."""
import discord
from datetime import datetime, timedelta
from typing import Optional


def format_number(n: int) -> str:
    """Format a number with commas: 1234567 -> 1,234,567"""
    if n is None:
        return "0"
    return f"{int(n):,}"


def format_compact(n: int) -> str:
    """Format a number compactly: 1234567 -> 1.2M"""
    if n is None:
        return "0"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def format_currency(amount: float) -> str:
    """Format as currency: 123.4 -> $123.40"""
    if amount is None:
        return "$0.00"
    return f"${amount:,.2f}"


def format_duration(days: Optional[int]) -> str:
    """Format duration days for display."""
    if days is None:
        return "Unlimited"
    return f"{days} days"


def format_timestamp(ts: str) -> str:
    """Format a database timestamp for display."""
    if not ts:
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %Y at %I:%M %p")
    except (ValueError, AttributeError):
        return ts


def format_date(ts: str) -> str:
    """Format a timestamp as just date."""
    if not ts:
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %Y")
    except (ValueError, AttributeError):
        return ts


def days_ago(ts: str) -> str:
    """Show how many days ago a timestamp was."""
    if not ts:
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        delta = datetime.now() - dt.replace(tzinfo=None)
        return f"{delta.days} days ago"
    except (ValueError, AttributeError):
        return "N/A"


def platform_emoji(platform: str) -> str:
    """Get emoji for a platform."""
    return {
        "instagram": "📷",
        "tiktok": "🎵",
        "twitter": "🐦",
        "youtube": "▶️"
    }.get(platform.lower(), "🌐")


def status_emoji(status: str) -> str:
    """Get emoji for a campaign/member status."""
    return {
        "active": "🟢",
        "paused": "⏸️",
        "completed": "✅",
        "left": "🚪",
        "removed": "❌",
    }.get(status.lower(), "❓")


def medal_emoji(rank: int) -> str:
    """Get medal emoji for leaderboard rank."""
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")


def progress_bar(current: float, maximum: float, length: int = 16) -> str:
    """Create a text-based progress bar."""
    if maximum <= 0:
        return "█" * length
    ratio = min(current / maximum, 1.0)
    filled = int(length * ratio)
    return "█" * filled + "░" * (length - filled)


def build_campaign_embed(campaign: dict, stats: dict = None) -> discord.Embed:
    """Build a rich embed for displaying campaign info."""
    status = campaign.get('status', 'active')
    color = {
        'active': discord.Color.green(),
        'paused': discord.Color.orange(),
        'completed': discord.Color.blue(),
    }.get(status, discord.Color.greyple())

    embed = discord.Embed(
        title=f"{status_emoji(status)} {campaign['name']}",
        color=color
    )
    embed.add_field(name="🆔 ID", value=f"`{campaign['id']}`", inline=True)
    embed.add_field(name="📱 Platforms", value=campaign.get('platforms', 'all').title(), inline=True)
    embed.add_field(name="💵 Rate",
                    value=f"{format_currency(campaign.get('rate_per_10k_views', 10))} per 10K views",
                    inline=True)

    duration = campaign.get('duration_days')
    if duration:
        created = campaign.get('created_at', '')
        try:
            created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            end_dt = created_dt + timedelta(days=duration)
            embed.add_field(name="⏱️ Duration",
                            value=f"{duration} days (ends {end_dt.strftime('%b %d, %Y')})",
                            inline=True)
        except (ValueError, AttributeError):
            embed.add_field(name="⏱️ Duration", value=f"{duration} days", inline=True)
    else:
        embed.add_field(name="⏱️ Duration", value="Unlimited", inline=True)

    budget = campaign.get('budget')
    embed.add_field(name="💰 Budget",
                    value=format_currency(budget) if budget else "Unlimited",
                    inline=True)

    min_views = campaign.get('min_views_to_join', 0)
    embed.add_field(name="👁️ Min Views to Join",
                    value=format_number(min_views) if min_views else "None",
                    inline=True)

    max_views = campaign.get('max_views_cap')
    embed.add_field(name="🔝 Max Views Cap",
                    value=format_number(max_views) if max_views else "Unlimited",
                    inline=True)

    embed.add_field(name="🛑 Auto-Stop",
                    value="Yes" if campaign.get('auto_stop', True) else "No",
                    inline=True)

    if stats:
        embed.add_field(name="━━━ Statistics ━━━", value="\u200b", inline=False)
        embed.add_field(name="📹 Videos", value=format_number(stats.get('total_videos', 0)), inline=True)
        embed.add_field(name="👁️ Views", value=format_number(stats.get('grand_total_views', 0)), inline=True)
        embed.add_field(name="❤️ Likes", value=format_number(stats.get('total_likes', 0)), inline=True)

    embed.set_footer(text=f"Created: {format_timestamp(campaign.get('created_at', ''))}")
    return embed
