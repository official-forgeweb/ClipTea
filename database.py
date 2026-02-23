import sqlite3
import os

DB_PATH = "metrics.db"

def init_db():
    """Initializes the SQLite database & ensures the schema exists."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create a table to track active Campaigns
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT,
        status TEXT DEFAULT 'active'
    )
    ''')
    
    # Create a table to track Users participating in Campaigns
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        discord_id TEXT,
        campaign_id TEXT,
        twitter_handle TEXT,
        tiktok_handle TEXT,
        instagram_handle TEXT,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
    )
    ''')

    # Create a table to store fetched metrics over time
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        campaign_id TEXT,
        platform TEXT, -- 'twitter', 'tiktok', 'instagram'
        post_url TEXT,
        views INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
    )
    ''')

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully.")

if __name__ == "__main__":
    init_db()
