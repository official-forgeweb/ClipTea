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

def get_connection():
    return sqlite3.connect(DB_PATH)

# --- Campaigns ---
def add_campaign(campaign_id: str, name: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO campaigns (id, name) VALUES (?, ?)", (campaign_id, name))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_campaign(campaign_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    res = cursor.fetchone()
    conn.close()
    return res

# --- Users ---
def add_user(user_id: str, discord_id: str, campaign_id: str, twitter: str = None, tiktok: str = None, instagram: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO users (id, discord_id, campaign_id, twitter_handle, tiktok_handle, instagram_handle) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, discord_id, campaign_id, twitter, tiktok, instagram))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_users_in_campaign(campaign_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE campaign_id = ?", (campaign_id,))
    res = cursor.fetchall()
    conn.close()
    return res

def get_user_metrics_summary(user_id: str):
    """Calculates sum of views/likes per platform from the metrics history."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT platform, SUM(views), SUM(likes) FROM metrics 
        WHERE user_id = ? 
        GROUP BY platform
    ''', (user_id,))
    res = cursor.fetchall()
    conn.close()
    return res

# --- Metrics ---
def get_campaign_metrics_summary(campaign_id: str):
     conn = get_connection()
     cursor = conn.cursor()
     # Get unique users, total views and total likes
     cursor.execute('''
        SELECT 
            COUNT(DISTINCT user_id) as active_users,
            SUM(views) as total_views,
            SUM(likes) as total_likes
        FROM metrics
        WHERE campaign_id = ?
     ''', (campaign_id,))
     res = cursor.fetchone()
     conn.close()
     return res

def add_metric(user_id: str, campaign_id: str, platform: str, post_url: str, views: int, likes: int):
     conn = get_connection()
     cursor = conn.cursor()
     cursor.execute('''
        INSERT INTO metrics (user_id, campaign_id, platform, post_url, views, likes)
        VALUES (?, ?, ?, ?, ?, ?)
     ''', (user_id, campaign_id, platform, post_url, views, likes))
     conn.commit()
     conn.close()

if __name__ == "__main__":
    init_db()
