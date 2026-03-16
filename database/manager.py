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
        """Link or update a social media account for a Discord user.
        Multiple Instagram accounts per user are supported.
        For TikTok/Twitter the latest username replaces the previous (one per platform)."""
        async with aiosqlite.connect(self.db_path) as db:
            if platform == 'instagram':
                # Insert new row; if (user, platform, username) already exists just update meta
                await db.execute(
                    """INSERT INTO user_accounts (discord_user_id, discord_username, platform, platform_username, verified)
                       VALUES (?, ?, ?, ?, 0)
                       ON CONFLICT(discord_user_id, platform, platform_username)
                       DO UPDATE SET discord_username = ?, linked_at = CURRENT_TIMESTAMP""",
                    (discord_user_id, discord_username, platform, platform_username, discord_username)
                )
            else:
                # For TikTok / Twitter: one account per platform — replace by deleting old first
                await db.execute(
                    "DELETE FROM user_accounts WHERE discord_user_id = ? AND platform = ?",
                    (discord_user_id, platform)
                )
                await db.execute(
                    """INSERT INTO user_accounts (discord_user_id, discord_username, platform, platform_username, verified)
                       VALUES (?, ?, ?, ?, 0)""",
                    (discord_user_id, discord_username, platform, platform_username)
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

    async def unlink_instagram_account(self, discord_user_id: str, platform_username: str) -> bool:
        """Unlink a specific Instagram account by username."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM user_accounts WHERE discord_user_id = ? "
                "AND platform = 'instagram' AND platform_username = ?",
                (discord_user_id, platform_username)
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
        """Get the first linked account for a platform (for TikTok/Twitter single-account use)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_accounts WHERE discord_user_id = ? AND platform = ? ORDER BY linked_at DESC LIMIT 1",
                (discord_user_id, platform)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_instagram_accounts(self, discord_user_id: str) -> List[Dict[str, Any]]:
        """Get all linked Instagram accounts for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_accounts WHERE discord_user_id = ? AND platform = 'instagram' ORDER BY linked_at DESC",
                (discord_user_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # ═══════════════════════════════════════════════
    # USER PAYMENTS
    # ═══════════════════════════════════════════════

    async def set_user_payment(self, discord_user_id: str, crypto_type: str, crypto_address: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO user_payments (discord_user_id, crypto_type, crypto_address, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(discord_user_id) DO UPDATE SET
                       crypto_type = excluded.crypto_type,
                       crypto_address = excluded.crypto_address,
                       updated_at = excluded.updated_at""",
                (discord_user_id, crypto_type, crypto_address)
            )
            await db.commit()
            return True

    async def get_user_payment(self, discord_user_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_payments WHERE discord_user_id = ?", (discord_user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    # ═══════════════════════════════════════════════
    # INSTAGRAM VERIFICATION CODES
    # ═══════════════════════════════════════════════

    async def save_verification_code(self, discord_user_id: str, platform: str, platform_username: str,
                                     code: str, ttl_minutes: int = 10) -> bool:
        """Save a pending verification code for an account (10-minute TTL)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO ig_verification_codes
                       (discord_user_id, platform, platform_username, code, expires_at, verified)
                   VALUES (?, ?, ?, ?, datetime('now', '+' || ? || ' minutes'), 0)
                   ON CONFLICT(discord_user_id, platform, platform_username)
                   DO UPDATE SET code = ?, expires_at = datetime('now', '+' || ? || ' minutes'),
                                 verified = 0, created_at = CURRENT_TIMESTAMP""",
                (discord_user_id, platform, platform_username, code, ttl_minutes,
                 code, ttl_minutes)
            )
            await db.commit()
            return True

    async def get_pending_verification(self, discord_user_id: str, platform: str,
                                       platform_username: str) -> Optional[Dict[str, Any]]:
        """Return the active (non-expired, unverified) code for a user+platform+username pair."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM ig_verification_codes
                   WHERE discord_user_id = ? AND platform = ? AND platform_username = ?
                         AND verified = 0 AND expires_at > CURRENT_TIMESTAMP""",
                (discord_user_id, platform, platform_username)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def mark_verified_by_code(self, discord_user_id: str, platform: str,
                                    platform_username: str) -> bool:
        """Mark a verification code as used and verify the linked account."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE ig_verification_codes SET verified = 1
                   WHERE discord_user_id = ? AND platform = ? AND platform_username = ?""",
                (discord_user_id, platform, platform_username)
            )
            await db.execute(
                """UPDATE user_accounts SET verified = 1
                   WHERE discord_user_id = ? AND platform = ? AND platform_username = ?""",
                (discord_user_id, platform, platform_username)
            )
            await db.commit()
            return True

    # ═══════════════════════════════════════════════
    # CAMPAIGN MEMBERS
    # ═══════════════════════════════════════════════

    async def join_campaign(self, campaign_id: str, discord_user_id: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # First, check if user previously left this campaign
                cursor = await db.execute(
                    "UPDATE campaign_members SET status = 'active', joined_at = CURRENT_TIMESTAMP "
                    "WHERE campaign_id = ? AND discord_user_id = ? AND status = 'left'",
                    (campaign_id, discord_user_id)
                )
                if cursor.rowcount > 0:
                    await db.commit()
                    return True

                # No previous membership — insert a new row
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
                           is_verified: bool = False, posted_at: str = None,
                           tracking_expires_at: str = None) -> Optional[int]:
        """Submit a video. Returns the video record ID or None on duplicate."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """INSERT INTO submitted_videos 
                       (campaign_id, discord_user_id, platform, video_url, video_id,
                        author_username, caption, is_verified, posted_at, tracking_expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (campaign_id, discord_user_id, platform, video_url, video_id,
                     author_username, caption, is_verified, posted_at, tracking_expires_at)
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
                "SELECT * FROM submitted_videos WHERE campaign_id = ? AND status != 'deleted' ORDER BY submitted_at DESC",
                (campaign_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_user_videos(self, discord_user_id: str, campaign_id: str = None) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if campaign_id:
                query = """SELECT sv.*, c.name as campaign_name 
                           FROM submitted_videos sv
                           LEFT JOIN campaigns c ON sv.campaign_id = c.id
                           WHERE sv.discord_user_id = ? AND sv.campaign_id = ? AND sv.status != 'deleted'
                           ORDER BY sv.submitted_at DESC"""
                params = (discord_user_id, campaign_id)
            else:
                query = """SELECT sv.*, c.name as campaign_name
                           FROM submitted_videos sv
                           LEFT JOIN campaigns c ON sv.campaign_id = c.id
                           WHERE sv.discord_user_id = ? AND sv.status != 'deleted'
                           ORDER BY sv.submitted_at DESC"""
                params = (discord_user_id,)
            async with db.execute(query, params) as cursor:
                results = [dict(row) for row in await cursor.fetchall()]
                print(f"[DEBUG] get_user_videos({discord_user_id}) returned {len(results)} videos")
                return results

    async def get_video_by_url(self, video_url: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Use LEFT JOIN so the lookup works even if the campaign was deleted
            async with db.execute(
                """SELECT sv.*, c.name as campaign_name 
                   FROM submitted_videos sv
                   LEFT JOIN campaigns c ON sv.campaign_id = c.id
                   WHERE sv.video_url = ?""",
                (video_url,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
            
            # Fallback: try matching by base URL (handles query-param mismatch)
            # e.g. stored as "...reel/ABC?igsh=xyz" but user sends "...reel/ABC"
            base_url = video_url.split('?')[0].rstrip('/')
            async with db.execute(
                """SELECT sv.*, c.name as campaign_name 
                   FROM submitted_videos sv
                   LEFT JOIN campaigns c ON sv.campaign_id = c.id
                   WHERE sv.video_url LIKE ? OR sv.video_url = ?""",
                (base_url + '%', base_url)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_tracking_videos(self) -> List[Dict[str, Any]]:
        """Get all videos that are actively being tracked across all active campaigns."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                 """SELECT sv.*, c.name as campaign_name FROM submitted_videos sv
                   JOIN campaigns c ON sv.campaign_id = c.id
                   WHERE sv.status = 'tracking' AND c.status = 'active' AND sv.is_final = 0
                   ORDER BY sv.submitted_at"""
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_user_tracking_videos(self, discord_user_id: str) -> List[Dict[str, Any]]:
        """Get all actively tracked videos for a specific user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT sv.*, c.name as campaign_name FROM submitted_videos sv
                   JOIN campaigns c ON sv.campaign_id = c.id
                   WHERE sv.status = 'tracking' AND c.status = 'active' AND sv.is_final = 0
                     AND sv.discord_user_id = ?
                   ORDER BY sv.submitted_at""",
                (discord_user_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def mark_video_final(self, video_id: int, views: int, likes: int, comments: int) -> bool:
        """Mark a video as final and save its terminal metrics."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """UPDATE submitted_videos 
                   SET is_final = 1, final_views = ?, final_likes = ?, final_comments = ?
                   WHERE id = ?""",
                (views, likes, comments, video_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_video_metrics(self, video_id: int, views: int, likes: int, comments: int) -> bool:
        """Force update the 'final' metrics in submitted_videos table for immediate reflection in stats."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """UPDATE submitted_videos 
                   SET final_views = ?, final_likes = ?, final_comments = ?
                   WHERE id = ?""",
                (views, likes, comments, video_id)
            )
            await db.commit()
            return cursor.rowcount > 0


    async def update_video_status(self, video_id: int, status: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE submitted_videos SET status = ? WHERE id = ?",
                (status, video_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def reject_video(self, discord_user_id: str, video_url: str) -> bool:
        """Reject a user's video, stopping tracking and completely zeroing out its views."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cursor = await db.execute(
                """UPDATE submitted_videos 
                   SET status = 'rejected', is_final = 1, final_views = 0, final_likes = 0, final_comments = 0 
                   WHERE discord_user_id = ? AND video_url = ?""",
                (discord_user_id, video_url)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete_video(self, video_url: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            # Try exact match first
            cursor = await db.execute(
                "UPDATE submitted_videos SET status = 'deleted' WHERE video_url = ?",
                (video_url,)
            )
            if cursor.rowcount > 0:
                await db.commit()
                return True
            
            # Fallback: try matching by base URL (handles query-param mismatch)
            base_url = video_url.split('?')[0].rstrip('/')
            cursor = await db.execute(
                "UPDATE submitted_videos SET status = 'deleted' WHERE video_url LIKE ?",
                (base_url + '%',)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def reject_user(self, campaign_id: str, discord_user_id: str) -> bool:
        """Ban a user from a campaign, completely zeroing out all their video views."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute(
                "UPDATE campaign_members SET status = 'removed' WHERE campaign_id = ? AND discord_user_id = ?",
                (campaign_id, discord_user_id)
            )
            cursor = await db.execute(
                """UPDATE submitted_videos 
                   SET status = 'rejected', is_final = 1, final_views = 0, final_likes = 0, final_comments = 0 
                   WHERE campaign_id = ? AND discord_user_id = ? AND status != 'deleted'""",
                (campaign_id, discord_user_id)
            )
            await db.commit()
            return True

    async def unreject_user(self, campaign_id: str, discord_user_id: str) -> bool:
        """Unban a user from a campaign and restore their rejected videos to active tracking."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute(
                "UPDATE campaign_members SET status = 'active' WHERE campaign_id = ? AND discord_user_id = ? AND status = 'removed'",
                (campaign_id, discord_user_id)
            )
            cursor = await db.execute(
                """UPDATE submitted_videos 
                   SET status = 'tracking', is_final = 0 
                   WHERE campaign_id = ? AND discord_user_id = ? AND status = 'rejected'""",
                (campaign_id, discord_user_id)
            )
            await db.commit()
            return True

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
                                   shares: int = 0, extra_data: str = "") -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO metric_snapshots (video_id, views, likes, comments, shares, extra_data)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (video_id, views, likes, comments, shares, extra_data)
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
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE latest.views END), 0) as grand_total_views,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_likes ELSE latest.likes END), 0) as total_likes,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_comments ELSE latest.comments END), 0) as total_comments,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN 0 ELSE latest.shares END), 0) as total_shares
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.campaign_id = ? AND sv.status != 'deleted'
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
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE latest.views END), 0) as total_views,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_likes ELSE latest.likes END), 0) as total_likes,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_comments ELSE latest.comments END), 0) as total_comments,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN 0 ELSE latest.shares END), 0) as total_shares
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.campaign_id = ? AND sv.discord_user_id = ? AND sv.status != 'deleted'
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
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE latest.views END), 0) as total_views,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_likes ELSE latest.likes END), 0) as total_likes,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_comments ELSE latest.comments END), 0) as total_comments,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN 0 ELSE latest.shares END), 0) as total_shares
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
            "views": "COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE latest.views END), 0)",
            "likes": "COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_likes ELSE latest.likes END), 0)",
            "videos": "COUNT(DISTINCT sv.id)",
        }.get(metric, "COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE latest.views END), 0)")

        where_clause = "WHERE sv.status != 'deleted'"
        params = []
        if campaign_id:
            where_clause += " AND sv.campaign_id = ?"
            params.append(campaign_id)

        query = f"""
            SELECT 
                sv.discord_user_id,
                COUNT(DISTINCT sv.id) as total_videos,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE latest.views END), 0) as total_views,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_likes ELSE latest.likes END), 0) as total_likes,
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_comments ELSE latest.comments END), 0) as total_comments
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
                COALESCE(SUM(CASE WHEN sv.is_final = 1 THEN sv.final_views ELSE latest.views END), 0) as total_views
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.campaign_id = ? AND sv.status != 'deleted'
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

    # ═══════════════════════════════════════════════
    # MIGRATIONS (for queue system)
    # ═══════════════════════════════════════════════

    async def run_migrations(self):
        """Add new columns needed for the smart queue system."""
        migrations = [
            "ALTER TABLE submitted_videos ADD COLUMN last_scraped_at TIMESTAMP",
            "ALTER TABLE submitted_videos ADD COLUMN scrape_attempts INTEGER DEFAULT 0",
            "ALTER TABLE submitted_videos ADD COLUMN last_error TEXT DEFAULT ''",
        ]
        async with aiosqlite.connect(self.db_path) as db:
            for sql in migrations:
                try:
                    await db.execute(sql)
                except Exception:
                    pass  # Column already exists
            await db.commit()

    async def update_last_scraped(self, video_url: str):
        """Update last_scraped_at timestamp for a video."""
        from datetime import datetime
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE submitted_videos SET last_scraped_at = ? WHERE video_url = ?",
                (datetime.now().isoformat(), video_url),
            )
            await db.commit()

    async def set_user_overall_stats(self, discord_user_id: str, total_views: int, total_likes: int) -> bool:
        """
        Adjusts user stats by managing a virtual 'manual' video entry that accounts for the 
        difference between video-based stats and the desired manual total.
        """
        import time
        stats = await self.get_user_all_time_stats(discord_user_id)
        current_total_views = stats['total_views']
        current_total_likes = stats['total_likes']
        
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Check if we already have a manual adjustment row for this user
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, final_views, final_likes FROM submitted_videos WHERE discord_user_id = ? AND platform = 'manual' LIMIT 1",
                (discord_user_id,)
            ) as cursor:
                adj_row = await cursor.fetchone()
                
            current_adj_views = adj_row['final_views'] if adj_row else 0
            current_adj_likes = adj_row['final_likes'] if adj_row else 0
            
            # The sum without the adjustment row is:
            base_views = current_total_views - current_adj_views
            base_likes = current_total_likes - current_adj_likes
            
            # New adjustment needed to reach target
            new_adj_views = total_views - base_views
            new_adj_likes = total_likes - base_likes
            
            if adj_row:
                # Update existing adjustment row
                await db.execute(
                    "UPDATE submitted_videos SET final_views = ?, final_likes = ? WHERE id = ?",
                    (new_adj_views, new_adj_likes, adj_row['id'])
                )
            else:
                # Create new adjustment row — need a campaign ID
                async with db.execute(
                    "SELECT campaign_id FROM campaign_members WHERE discord_user_id = ? LIMIT 1",
                    (discord_user_id,)
                ) as cur:
                    c_row = await cur.fetchone()
                    if not c_row:
                        # Fallback: find any campaign
                        async with db.execute("SELECT id FROM campaigns LIMIT 1") as cur2:
                            row2 = await cur2.fetchone()
                            if not row2: return False
                            cid = row2[0]
                    else:
                        cid = c_row[0]
                
                await db.execute(
                    """INSERT INTO submitted_videos 
                       (campaign_id, discord_user_id, platform, video_url, video_id, author_username, is_final, final_views, final_likes, status)
                       VALUES (?, ?, 'manual', ?, 'ADJUSTMENT', 'Manual Manager', 1, ?, ?, 'tracking')""",
                    (cid, discord_user_id, f"MANUAL_ADJUSTMENT_{discord_user_id}", new_adj_views, new_adj_likes)
                )
            
            await db.commit()
            return True

