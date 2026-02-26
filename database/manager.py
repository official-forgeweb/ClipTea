import aiosqlite
import sqlite3
from typing import List, Dict, Optional, Any
from config import DATABASE_PATH
from database.models import init_database

class DatabaseManager:
    """Handles all CRUD operations for the SQLite database."""
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self):
        """Initializes the database schema."""
        await init_database(self.db_path)

    async def create_campaign(self, campaign_id: str, name: str, description: str = "") -> bool:
        """Creates a new campaign."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO campaigns (id, name, description) VALUES (?, ?, ?)",
                    (campaign_id, name, description)
                )
                await db.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    async def get_all_campaigns(self) -> List[Dict[str, Any]]:
        """Returns a list of all campaigns."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM campaigns ORDER BY created_at DESC") as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_campaign(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        """Returns details for a single campaign."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def delete_campaign(self, campaign_id: str) -> bool:
        """Deletes a campaign and cascades deletions."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cursor = await db.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def add_user(self, campaign_id: str, username: str, platform: str) -> bool:
        """Adds a user to a campaign."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO campaign_users (campaign_id, username, platform) VALUES (?, ?, ?)",
                    (campaign_id, username, platform)
                )
                await db.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    async def remove_user(self, campaign_id: str, username: str, platform: str) -> bool:
        """Removes a user from a campaign."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM campaign_users WHERE campaign_id = ? AND username = ? AND platform = ?",
                (campaign_id, username, platform)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_campaign_users(self, campaign_id: str) -> List[Dict[str, Any]]:
        """Returns all users in a specific campaign."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM campaign_users WHERE campaign_id = ? ORDER BY added_at DESC",
                (campaign_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_user_id(self, campaign_id: str, username: str, platform: str) -> Optional[int]:
        """Returns the internal ID of a enrolled user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id FROM campaign_users WHERE campaign_id=? AND username=? AND platform=?",
                (campaign_id, username, platform)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def save_post_and_metrics(self, campaign_user_id: int, platform: str, post_data: dict):
        """Saves a discovered post and its metric snapshot."""
        async with aiosqlite.connect(self.db_path) as db:
            # Upsert the post
            cursor = await db.execute(
                "SELECT id FROM posts WHERE post_url = ?",
                (post_data["post_url"],)
            )
            row = await cursor.fetchone()
            if row:
                post_id = row[0]
            else:
                cursor = await db.execute(
                    """INSERT INTO posts (campaign_user_id, platform, post_url, post_id, caption, posted_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        campaign_user_id, platform, post_data["post_url"],
                        post_data.get("post_id", ""), post_data.get("caption", ""),
                        post_data.get("posted_at", "")
                    )
                )
                post_id = cursor.lastrowid

            # Insert metric snapshot
            await db.execute(
                """INSERT INTO metric_snapshots (post_id, views, likes, comments, shares)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    post_id,
                    post_data.get("views", 0),
                    post_data.get("likes", 0),
                    post_data.get("comments", 0),
                    post_data.get("shares", 0)
                )
            )
            await db.commit()

    async def get_campaign_statistics(self, campaign_id: str) -> Dict[str, Any]:
        """Gets overall metrics for a campaign by aggregating the LATEST snapshots of each post."""
        query = """
            SELECT 
                COUNT(DISTINCT p.id) as total_posts,
                SUM(latest_metrics.views) as total_views,
                SUM(latest_metrics.likes) as total_likes,
                SUM(latest_metrics.comments) as total_comments,
                SUM(latest_metrics.shares) as total_shares
            FROM campaign_users cu
            JOIN posts p ON cu.id = p.campaign_user_id
            JOIN (
                SELECT post_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.post_id = m1.post_id
                )
            ) latest_metrics ON p.id = latest_metrics.post_id
            WHERE cu.campaign_id = ?
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (campaign_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}

    async def get_user_metrics(self, campaign_id: str, username: str) -> Dict[str, Any]:
        """Gets overall metrics for a specific user across their platforms in a campaign."""
        query = """
            SELECT 
                COUNT(DISTINCT p.id) as total_posts,
                SUM(latest_metrics.views) as total_views,
                SUM(latest_metrics.likes) as total_likes,
                SUM(latest_metrics.comments) as total_comments,
                SUM(latest_metrics.shares) as total_shares
            FROM campaign_users cu
            JOIN posts p ON cu.id = p.campaign_user_id
            JOIN (
                SELECT post_id, views, likes, comments, shares
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.post_id = m1.post_id
                )
            ) latest_metrics ON p.id = latest_metrics.post_id
            WHERE cu.campaign_id = ? AND cu.username = ?
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (campaign_id, username)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}

    async def get_top_performers(self, campaign_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Gets users ordered by total views."""
        query = """
            SELECT 
                cu.username,
                cu.platform,
                COUNT(DISTINCT p.id) as total_posts,
                COALESCE(SUM(latest_metrics.views), 0) as total_views,
                COALESCE(SUM(latest_metrics.likes), 0) as total_likes
            FROM campaign_users cu
            LEFT JOIN posts p ON cu.id = p.campaign_user_id
            LEFT JOIN (
                SELECT post_id, views, likes
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.post_id = m1.post_id
                )
            ) latest_metrics ON p.id = latest_metrics.post_id
            WHERE cu.campaign_id = ?
            GROUP BY cu.id
            ORDER BY total_views DESC
            LIMIT ?
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (campaign_id, limit)) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

