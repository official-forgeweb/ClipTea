import aiosqlite
import sqlite3
from typing import List, Dict, Optional, Any
from config import DATABASE_PATH
from database.models import init_database


class DatabaseManager:
    """Handles all CRUD operations for the Campaign Analytics Bot."""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self):
        await init_database(self.db_path)

    # ═══════════════════════════════════════════════
    # BOT SETTINGS
    # ═══════════════════════════════════════════════

    async def get_setting(self, key: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, value)
            )
            await db.commit()
            return True

    async def get_all_settings(self) -> Dict[str, str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT key, value FROM bot_settings") as cursor:
                rows = await cursor.fetchall()
                return {row[0]: row[1] for row in rows}

    # ═══════════════════════════════════════════════
    # CAMPAIGNS
    # ═══════════════════════════════════════════════

    async def create_campaign(self, campaign_id: str, name: str, created_by: str,
                              description: str = "", duration_days: Optional[int] = None,
                              budget: Optional[float] = None, min_views_to_join: int = 0,
                              max_views_cap: Optional[int] = None,
                              rate_per_10k_views: float = 10.00,
                              platforms: str = "all", auto_stop: bool = True) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """INSERT INTO campaigns 
                       (id, name, description, duration_days, budget, min_views_to_join,
                        max_views_cap, rate_per_10k_views, platforms, auto_stop, created_by_discord_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (campaign_id, name, description, duration_days, budget,
                     min_views_to_join, max_views_cap, rate_per_10k_views,
                     platforms, auto_stop, created_by)
                )
                await db.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    async def get_campaign(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_campaigns(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM campaigns ORDER BY created_at DESC") as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_active_campaigns(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM campaigns WHERE status = 'active' ORDER BY created_at DESC"
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_campaigns_by_status(self, status: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM campaigns WHERE status = ? ORDER BY created_at DESC", (status,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def update_campaign(self, campaign_id: str, **kwargs) -> bool:
        if not kwargs:
            return False
        valid_fields = {
            'name', 'description', 'duration_days', 'budget', 'min_views_to_join',
            'max_views_cap', 'rate_per_10k_views', 'platforms', 'auto_stop', 'status',
            'ended_at', 'end_reason'
        }
        fields = {k: v for k, v in kwargs.items() if k in valid_fields}
        if not fields:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [campaign_id]

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE campaigns SET {set_clause} WHERE id = ?", values
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_campaign_status(self, campaign_id: str, status: str,
                                     end_reason: str = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            if status == 'completed':
                await db.execute(
                    "UPDATE campaigns SET status = ?, ended_at = CURRENT_TIMESTAMP, end_reason = ? WHERE id = ?",
                    (status, end_reason, campaign_id)
                )
            else:
                await db.execute(
                    "UPDATE campaigns SET status = ? WHERE id = ?",
                    (status, campaign_id)
                )
            await db.commit()
            return True

    async def delete_campaign(self, campaign_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cursor = await db.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
            await db.commit()
            return cursor.rowcount > 0

    # ═══════════════════════════════════════════════
    # USER ACCOUNTS
    # ═══════════════════════════════════════════════

    async def link_account(self, discord_user_id: str, discord_username: str,
                           platform: str, platform_username: str) -> bool:
        """Link or update a social media account for a Discord user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO user_accounts (discord_user_id, discord_username, platform, platform_username, verified)
                   VALUES (?, ?, ?, ?, 0)
                   ON CONFLICT(discord_user_id, platform) 
                   DO UPDATE SET platform_username = ?, discord_username = ?, verified = 0, linked_at = CURRENT_TIMESTAMP""",
                (discord_user_id, discord_username, platform, platform_username,
                 platform_username, discord_username)
            )
            await db.commit()
            return True

    async def verify_account(self, discord_user_id: str, platform: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE user_accounts SET verified = 1 WHERE discord_user_id = ? AND platform = ?",
                (discord_user_id, platform)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def unlink_account(self, discord_user_id: str, platform: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM user_accounts WHERE discord_user_id = ? AND platform = ?",
                (discord_user_id, platform)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_user_accounts(self, discord_user_id: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_accounts WHERE discord_user_id = ?", (discord_user_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_user_account(self, discord_user_id: str, platform: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_accounts WHERE discord_user_id = ? AND platform = ?",
                (discord_user_id, platform)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    # ═══════════════════════════════════════════════
    # CAMPAIGN MEMBERS
    # ═══════════════════════════════════════════════

    async def join_campaign(self, campaign_id: str, discord_user_id: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO campaign_members (campaign_id, discord_user_id) VALUES (?, ?)",
                    (campaign_id, discord_user_id)
                )
                await db.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    async def leave_campaign(self, campaign_id: str, discord_user_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE campaign_members SET status = 'left' WHERE campaign_id = ? AND discord_user_id = ? AND status = 'active'",
                (campaign_id, discord_user_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def is_campaign_member(self, campaign_id: str, discord_user_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM campaign_members WHERE campaign_id = ? AND discord_user_id = ? AND status = 'active'",
                (campaign_id, discord_user_id)
            ) as cursor:
                return await cursor.fetchone() is not None

    async def get_campaign_members(self, campaign_id: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM campaign_members WHERE campaign_id = ? AND status = 'active' ORDER BY joined_at",
                (campaign_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_campaign_member_count(self, campaign_id: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM campaign_members WHERE campaign_id = ? AND status = 'active'",
                (campaign_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_user_campaigns(self, discord_user_id: str) -> List[Dict[str, Any]]:
        """Get all campaigns a user has joined with campaign details."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT c.*, cm.joined_at as member_joined_at, cm.status as member_status
                   FROM campaign_members cm
                   JOIN campaigns c ON cm.campaign_id = c.id
                   WHERE cm.discord_user_id = ?
                   ORDER BY cm.joined_at DESC""",
                (discord_user_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # ═══════════════════════════════════════════════
    # SUBMITTED VIDEOS
    # ═══════════════════════════════════════════════

    async def submit_video(self, campaign_id: str, discord_user_id: str,
                           platform: str, video_url: str, video_id: str = "",
                           author_username: str = "", caption: str = "",
                           is_verified: bool = False) -> Optional[int]:
        """Submit a video. Returns the video record ID or None on duplicate."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """INSERT INTO submitted_videos 
                       (campaign_id, discord_user_id, platform, video_url, video_id,
                        author_username, caption, is_verified)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (campaign_id, discord_user_id, platform, video_url, video_id,
                     author_username, caption, is_verified)
                )
                await db.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    async def get_submitted_video_by_url(self, campaign_id: str, video_url: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM submitted_videos WHERE campaign_id = ? AND video_url = ?",
                (campaign_id, video_url)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_campaign_videos(self, campaign_id: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM submitted_videos WHERE campaign_id = ? AND status = 'tracking' ORDER BY submitted_at DESC",
                (campaign_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_user_videos(self, discord_user_id: str, campaign_id: str = None) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if campaign_id:
                query = """SELECT sv.*, c.name as campaign_name 
                           FROM submitted_videos sv
                           JOIN campaigns c ON sv.campaign_id = c.id
                           WHERE sv.discord_user_id = ? AND sv.campaign_id = ?
                           ORDER BY sv.submitted_at DESC"""
                params = (discord_user_id, campaign_id)
            else:
                query = """SELECT sv.*, c.name as campaign_name
                           FROM submitted_videos sv
                           JOIN campaigns c ON sv.campaign_id = c.id
                           WHERE sv.discord_user_id = ?
                           ORDER BY sv.submitted_at DESC"""
                params = (discord_user_id,)
            async with db.execute(query, params) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_video_by_url(self, video_url: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT sv.*, c.name as campaign_name 
                   FROM submitted_videos sv
                   JOIN campaigns c ON sv.campaign_id = c.id
                   WHERE sv.video_url = ?""",
                (video_url,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_tracking_videos(self) -> List[Dict[str, Any]]:
        """Get all videos that are actively being tracked across all active campaigns."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT sv.* FROM submitted_videos sv
                   JOIN campaigns c ON sv.campaign_id = c.id
                   WHERE sv.status = 'tracking' AND c.status = 'active'
                   ORDER BY sv.submitted_at"""
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def update_video_status(self, video_id: int, status: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE submitted_videos SET status = ? WHERE id = ?",
                (status, video_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete_video(self, video_url: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cursor = await db.execute(
                "UPDATE submitted_videos SET status = 'deleted' WHERE video_url = ?",
                (video_url,)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_campaign_video_count(self, campaign_id: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM submitted_videos WHERE campaign_id = ? AND status = 'tracking'",
                (campaign_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # ═══════════════════════════════════════════════
    # METRIC SNAPSHOTS
    # ═══════════════════════════════════════════════

    async def save_metric_snapshot(self, video_id: int, views: int = 0,
                                   likes: int = 0, comments: int = 0,
                                   shares: int = 0) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO metric_snapshots (video_id, views, likes, comments, shares)
                   VALUES (?, ?, ?, ?, ?)""",
                (video_id, views, likes, comments, shares)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_latest_metrics(self, video_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM metric_snapshots WHERE video_id = ? ORDER BY id DESC LIMIT 1",
                (video_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_metric_history(self, video_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM metric_snapshots WHERE video_id = ? ORDER BY fetched_at ASC",
                (video_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # ═══════════════════════════════════════════════
    # CAMPAIGN STATISTICS
    # ═══════════════════════════════════════════════

    async def get_campaign_statistics(self, campaign_id: str) -> Dict[str, Any]:
        """Get aggregate statistics for a campaign using latest snapshots per video."""
        query = """
            SELECT 
                COUNT(DISTINCT sv.id) as total_videos,
                COALESCE(SUM(latest.views), 0) as grand_total_views,
                COALESCE(SUM(latest.likes), 0) as total_likes,
                COALESCE(SUM(latest.comments), 0) as total_comments,
                COALESCE(SUM(latest.shares), 0) as total_shares
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.campaign_id = ? AND sv.status = 'tracking'
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (campaign_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {
                    'total_videos': 0, 'grand_total_views': 0,
                    'total_likes': 0, 'total_comments': 0, 'total_shares': 0
                }

    async def get_user_campaign_stats(self, campaign_id: str, discord_user_id: str) -> Dict[str, Any]:
        """Get a specific user's stats within a campaign."""
        query = """
            SELECT 
                COUNT(DISTINCT sv.id) as total_videos,
                COALESCE(SUM(latest.views), 0) as total_views,
                COALESCE(SUM(latest.likes), 0) as total_likes,
                COALESCE(SUM(latest.comments), 0) as total_comments,
                COALESCE(SUM(latest.shares), 0) as total_shares
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.campaign_id = ? AND sv.discord_user_id = ? AND sv.status = 'tracking'
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (campaign_id, discord_user_id)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {
                    'total_videos': 0, 'total_views': 0,
                    'total_likes': 0, 'total_comments': 0, 'total_shares': 0
                }

    async def get_user_all_time_stats(self, discord_user_id: str) -> Dict[str, Any]:
        """Get all-time stats for a user across all campaigns."""
        query = """
            SELECT 
                COUNT(DISTINCT sv.id) as total_videos,
                COALESCE(SUM(latest.views), 0) as total_views,
                COALESCE(SUM(latest.likes), 0) as total_likes,
                COALESCE(SUM(latest.comments), 0) as total_comments,
                COALESCE(SUM(latest.shares), 0) as total_shares
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.discord_user_id = ? AND sv.status != 'deleted'
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (discord_user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {
                    'total_videos': 0, 'total_views': 0,
                    'total_likes': 0, 'total_comments': 0, 'total_shares': 0
                }

    async def get_first_submission_date(self, discord_user_id: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT MIN(submitted_at) FROM submitted_videos WHERE discord_user_id = ?",
                (discord_user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row and row[0] else None

    async def get_leaderboard(self, campaign_id: str = None, metric: str = "views",
                              limit: int = 10) -> List[Dict[str, Any]]:
        """Get leaderboard sorted by a metric. If campaign_id is None, global."""
        metric_col = {
            "views": "COALESCE(SUM(latest.views), 0)",
            "likes": "COALESCE(SUM(latest.likes), 0)",
            "videos": "COUNT(DISTINCT sv.id)",
        }.get(metric, "COALESCE(SUM(latest.views), 0)")

        where_clause = "WHERE sv.status = 'tracking'"
        params = []
        if campaign_id:
            where_clause += " AND sv.campaign_id = ?"
            params.append(campaign_id)

        query = f"""
            SELECT 
                sv.discord_user_id,
                COUNT(DISTINCT sv.id) as total_videos,
                COALESCE(SUM(latest.views), 0) as total_views,
                COALESCE(SUM(latest.likes), 0) as total_likes,
                COALESCE(SUM(latest.comments), 0) as total_comments
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            {where_clause}
            GROUP BY sv.discord_user_id
            ORDER BY {metric_col} DESC
            LIMIT ?
        """
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_campaign_platform_breakdown(self, campaign_id: str) -> List[Dict[str, Any]]:
        """Get view breakdown by platform for a campaign."""
        query = """
            SELECT 
                sv.platform,
                COUNT(DISTINCT sv.id) as video_count,
                COALESCE(SUM(latest.views), 0) as total_views
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.campaign_id = ? AND sv.status = 'tracking'
            GROUP BY sv.platform
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (campaign_id,)) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # ═══════════════════════════════════════════════
    # NOTIFICATIONS
    # ═══════════════════════════════════════════════

    async def log_notification(self, campaign_id: str, notif_type: str,
                               message: str, channel_id: str = "") -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO notifications (campaign_id, type, message, sent_to_channel)
                   VALUES (?, ?, ?, ?)""",
                (campaign_id, notif_type, message, channel_id)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_recent_notifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM notifications ORDER BY sent_at DESC LIMIT ?", (limit,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
