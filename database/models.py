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
    UNIQUE(discord_user_id, platform, platform_username)
);
"""

IG_VERIFICATION_CODES_TABLE = """
CREATE TABLE IF NOT EXISTS ig_verification_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'instagram',
    platform_username TEXT NOT NULL,
    code TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    verified BOOLEAN DEFAULT 0,
    UNIQUE(discord_user_id, platform_username)
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
    posted_at TIMESTAMP DEFAULT NULL,
    tracking_expires_at TIMESTAMP DEFAULT NULL,
    is_final INTEGER DEFAULT 0,
    final_views INTEGER DEFAULT 0,
    final_likes INTEGER DEFAULT 0,
    final_comments INTEGER DEFAULT 0,
    is_verified BOOLEAN DEFAULT 0,
    status TEXT DEFAULT 'tracking' 
        CHECK(status IN ('tracking','stopped','rejected','deleted')),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE(campaign_id, video_url)
);
"""

USER_PAYMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS user_payments (
    discord_user_id TEXT PRIMARY KEY,
    crypto_type TEXT DEFAULT '',
    crypto_address TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


APIFY_CACHE_TABLE = """
CREATE TABLE IF NOT EXISTS apify_cache (
    shortcode TEXT PRIMARY KEY,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    author_username TEXT DEFAULT '',
    raw_response TEXT DEFAULT '',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

API_USAGE_TABLE = """
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT DEFAULT 'apify',
    endpoint TEXT DEFAULT '',
    shortcode TEXT DEFAULT '',
    credits_used REAL DEFAULT 0,
    success INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

async def init_database(db_path: str):
    """Initialize the database with all tables and default settings."""
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(BOT_SETTINGS_TABLE)
        await db.executescript(BOT_SETTINGS_DEFAULTS)
        await db.execute(CAMPAIGNS_TABLE)
        # Run migration for multi-account support before creating the table
        await _migrate_user_accounts(db)
        await db.execute(USER_ACCOUNTS_TABLE)
        await db.execute(CAMPAIGN_MEMBERS_TABLE)
        await db.execute(SUBMITTED_VIDEOS_TABLE)
        await _migrate_submitted_videos(db)
        await db.execute(USER_PAYMENTS_TABLE)
        await db.execute(METRIC_SNAPSHOTS_TABLE)
        await db.execute(NOTIFICATIONS_TABLE)
        await db.execute(IG_VERIFICATION_CODES_TABLE)
        await db.execute(APIFY_CACHE_TABLE)
        await db.execute(API_USAGE_TABLE)
        for index_query in INDEXES:
            await db.execute(index_query)
        await db.commit()


async def _migrate_user_accounts(db):
    """Migrate user_accounts UNIQUE constraint from (user, platform) to (user, platform, username).
    This allows multiple Instagram accounts per user. Runs safely on both fresh and existing DBs."""
    # Check if old table exists with old constraint by inspecting sqlite_master
    async with db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='user_accounts'"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return  # Fresh DB, no migration needed — CREATE IF NOT EXISTS will handle it
    existing_sql = row[0] or ""
    # If the existing table already has the new 3-column unique key, skip
    if "platform_username" in existing_sql and "UNIQUE(discord_user_id, platform, platform_username)" in existing_sql:
        return
    # Perform migration: rename old table, create new one, copy data, drop old
    await db.executescript("""
        PRAGMA foreign_keys = OFF;
        ALTER TABLE user_accounts RENAME TO user_accounts_old;
        CREATE TABLE IF NOT EXISTS user_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_user_id TEXT NOT NULL,
            discord_username TEXT DEFAULT '',
            platform TEXT NOT NULL CHECK(platform IN ('instagram','tiktok','twitter')),
            platform_username TEXT NOT NULL,
            verified BOOLEAN DEFAULT 0,
            linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(discord_user_id, platform, platform_username)
        );
        INSERT OR IGNORE INTO user_accounts
            (id, discord_user_id, discord_username, platform, platform_username, verified, linked_at)
        SELECT id, discord_user_id, discord_username, platform, platform_username, verified, linked_at
        FROM user_accounts_old;
        DROP TABLE user_accounts_old;
        PRAGMA foreign_keys = ON;
    """)


async def _migrate_submitted_videos(db):
    """Add new columns to submitted_videos for tracking validity. Runs safely on existing DBs."""
    columns_to_add = [
        ("posted_at", "TIMESTAMP DEFAULT NULL"),
        ("tracking_expires_at", "TIMESTAMP DEFAULT NULL"),
        ("is_final", "INTEGER DEFAULT 0"),
        ("final_views", "INTEGER DEFAULT 0"),
        ("final_likes", "INTEGER DEFAULT 0"),
        ("final_comments", "INTEGER DEFAULT 0"),
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            # Check if column exists
            async with db.execute(f"PRAGMA table_info(submitted_videos)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if col_name not in columns:
                    await db.execute(f"ALTER TABLE submitted_videos ADD COLUMN {col_name} {col_type}")
        except Exception as e:
            print(f"Migration error for {col_name}: {e}")
    await db.commit()
