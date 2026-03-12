
import sqlite3
import os

db_path = "campaign_data.db"
if not os.path.exists(db_path):
    print(f"Database {db_path} not found")
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("--- Tables in DB ---")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [row['name'] for row in cursor.fetchall()]
print(", ".join(tables))

print("--- Recent Submissions (Last 10) ---")
query = """
SELECT sv.id, sv.video_url, sv.platform, m.views, m.likes, m.fetched_at, sv.status, sv.is_final
FROM submitted_videos sv
LEFT JOIN (
    SELECT video_id, views, likes, fetched_at
    FROM metric_snapshots
    WHERE id IN (SELECT MAX(id) FROM metric_snapshots GROUP BY video_id)
) m ON sv.id = m.video_id
ORDER BY sv.submitted_at DESC
LIMIT 10;
"""

cursor.execute(query)
rows = cursor.fetchall()

for row in rows:
    print(f"ID: {row['id']} | Plat: {row['platform']} | Views: {row['views']} | Likes: {row['likes']} | Status: {row['status']} | Final: {row['is_final']}")
    print(f"URL: {row['video_url']}")
    print("-" * 20)

print("\n--- Summary Statistics ---")
cursor.execute("SELECT COUNT(*) FROM submitted_videos")
total = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM submitted_videos WHERE status = 'tracking'")
tracking = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM submitted_videos WHERE status = 'rejected'")
rejected = cursor.fetchone()[0]

print(f"Total Videos: {total}")
print(f"Tracking: {tracking}")
print(f"Rejected: {rejected}")

conn.close()
