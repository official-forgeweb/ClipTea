"""
Database schema definitions for the Campaign Analytics Bot.
7 tables: bot_settings, campaigns, user_accounts, campaign_members,
submitted_videos, metric_snapshots, notifications.
"""

BOT_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

BOT_SETTINGS_DEFAULTS = """
INSERT OR IGNORE INTO bot_settings (key, value) VALUES 
    ('default_rate_per_10k', '10.00'),
    ('default_duration_days', 'unlimited'),
    ('default_budget', 'unlimited'),
    ('default_min_views', '0'),
    ('default_max_views', 'unlimited'),
    ('scrape_interval_minutes', '60'),
    ('admin_role_id', ''),
    ('notification_channel_id', ''),
    ('daily_summary_enabled', 'false'),
    ('daily_summary_time', '09:00');
"""

CAMPAIGNS_TABLE = """
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    duration_days INTEGER DEFAULT NULL,
    budget REAL DEFAULT NULL,
    min_views_to_join INTEGER DEFAULT 0,
    max_views_cap INTEGER DEFAULT NULL,
    rate_per_10k_views REAL NOT NULL DEFAULT 10.00,
    platforms TEXT DEFAULT 'all',
    auto_stop BOOLEAN DEFAULT 1,
    status TEXT DEFAULT 'active' CHECK(status IN ('active','paused','completed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP DEFAULT NULL,
    end_reason TEXT DEFAULT NULL,
    created_by_discord_id TEXT NOT NULL
);
"""

USER_ACCOUNTS_TABLE = """
CREATE TABLE IF NOT EXISTS user_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    discord_username TEXT DEFAULT '',
    platform TEXT NOT NULL CHECK(platform IN ('instagram','tiktok','twitter')),
    platform_username TEXT NOT NULL,
    verified BOOLEAN DEFAULT 0,
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(discord_user_id, platform)
);
"""

CAMPAIGN_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS campaign_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    discord_user_id TEXT NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active' CHECK(status IN ('active','left','removed')),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE(campaign_id, discord_user_id)
);
"""

SUBMITTED_VIDEOS_TABLE = """
CREATE TABLE IF NOT EXISTS submitted_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    discord_user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    video_url TEXT NOT NULL,
    video_id TEXT DEFAULT '',
    author_username TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_verified BOOLEAN DEFAULT 0,
    status TEXT DEFAULT 'tracking' 
        CHECK(status IN ('tracking','stopped','rejected','deleted')),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE(campaign_id, video_url)
);
"""

METRIC_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES submitted_videos(id) ON DELETE CASCADE
);
"""

NOTIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_to_channel TEXT DEFAULT ''
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ua_discord ON user_accounts(discord_user_id);",
    "CREATE INDEX IF NOT EXISTS idx_cm_campaign ON campaign_members(campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_cm_user ON campaign_members(discord_user_id);",
    "CREATE INDEX IF NOT EXISTS idx_sv_campaign ON submitted_videos(campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_sv_user ON submitted_videos(discord_user_id);",
    "CREATE INDEX IF NOT EXISTS idx_ms_video ON metric_snapshots(video_id);",
]


async def init_database(db_path: str):
    """Initialize the database with all tables and default settings."""
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(BOT_SETTINGS_TABLE)
        await db.executescript(BOT_SETTINGS_DEFAULTS)
        await db.execute(CAMPAIGNS_TABLE)
        await db.execute(USER_ACCOUNTS_TABLE)
        await db.execute(CAMPAIGN_MEMBERS_TABLE)
        await db.execute(SUBMITTED_VIDEOS_TABLE)
        await db.execute(METRIC_SNAPSHOTS_TABLE)
        await db.execute(NOTIFICATIONS_TABLE)
        for index_query in INDEXES:
            await db.execute(index_query)
        await db.commit()
