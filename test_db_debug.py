import sqlite3

db_path = "c:\\Users\\lenovo\\OneDrive\\Desktop\\Projects\\ClipTea\\metrics.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Get users who have videos
cur.execute("SELECT discord_user_id, COUNT(*) FROM submitted_videos GROUP BY discord_user_id ORDER BY COUNT(*) DESC LIMIT 5")
users = cur.fetchall()
print("Top users with videos:", users)

# Check for a specific user ID if needed
cur.execute("SELECT id, video_url, status FROM submitted_videos LIMIT 3")
print("Sample videos:", cur.fetchall())

conn.close()
