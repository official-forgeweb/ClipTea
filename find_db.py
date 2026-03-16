import sqlite3
import os
import glob

# Search for all sqlite databases in the dir recursively
db_files = glob.glob("c:\\Users\\lenovo\\OneDrive\\Desktop\\Projects\\ClipTea\\**\\*.db", recursive=True)

for db_path in db_files:
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='submitted_videos';")
        if cur.fetchone():
            cur.execute("SELECT count(*) FROM submitted_videos;")
            count = cur.fetchone()[0]
            if count > 0:
                print(f"FOUND ACTIVE DB! {db_path} - Rows: {count}")
                cur.execute("SELECT discord_user_id, COUNT(*) FROM submitted_videos GROUP BY discord_user_id LIMIT 3")
                print("  Sample users:", cur.fetchall())
        conn.close()
    except Exception as e:
        pass
