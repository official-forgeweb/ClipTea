CAMPAIGNS_TABLE = """
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active' CHECK(status IN ('active','paused','completed'))
);
"""

CAMPAIGN_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS campaign_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    username TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('instagram','tiktok','twitter')),
    profile_url TEXT DEFAULT '',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE(campaign_id, username, platform)
);
"""

POSTS_TABLE = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_user_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    post_url TEXT NOT NULL UNIQUE,
    post_id TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    posted_at TEXT DEFAULT '',
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_user_id) REFERENCES campaign_users(id) ON DELETE CASCADE
);
"""

METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_cu_campaign ON campaign_users(campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(campaign_user_id);",
    "CREATE INDEX IF NOT EXISTS idx_metrics_post ON metric_snapshots(post_id);"
]

async def init_database(db_path: str):
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(CAMPAIGNS_TABLE)
        await db.execute(CAMPAIGN_USERS_TABLE)
        await db.execute(POSTS_TABLE)
        await db.execute(METRICS_TABLE)
        for index_query in INDEXES:
            await db.execute(index_query)
        await db.commit()
