import sqlite3
import os

DB_PATH = 'cliptea.db'

def run_migration():
    print(f"Running database migration for {DB_PATH}...")
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found!")
        return

    try:
        with sqlite3.connect(DB_PATH) as db:
            cursor = db.cursor()
            
            # Check if platform column exists
            cursor.execute("PRAGMA table_info(submitted_videos)")
            columns = cursor.fetchall()
            col_names = [col[1] for col in columns]
            
            if 'platform' not in col_names:
                print("Adding 'platform' column to submitted_videos...")
                cursor.execute("ALTER TABLE submitted_videos ADD COLUMN platform TEXT DEFAULT 'instagram'")
                db.commit()
                print("Column added successfully!")
            else:
                print("'platform' column already exists in submitted_videos.")

            # Check if extra_data column exists in metric_snapshots  
            cursor.execute("PRAGMA table_info(metric_snapshots)")
            columns = cursor.fetchall()
            col_names = [col[1] for col in columns]
            
            if 'extra_data' not in col_names:
                print("Adding 'extra_data' column to metric_snapshots...")
                cursor.execute("ALTER TABLE metric_snapshots ADD COLUMN extra_data TEXT DEFAULT ''")
                db.commit()
                print("Column added successfully!")
            else:
                print("'extra_data' column already exists in metric_snapshots.")
                
            print("Migration complete!")
    except Exception as e:
        print(f"Error during migration: {e}")

if __name__ == "__main__":
    run_migration()
