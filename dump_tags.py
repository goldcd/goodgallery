
import sqlite3
import os

try:
    conn = sqlite3.connect(os.path.join('data', 'gallery.db'))
    cursor = conn.cursor()
    cursor.execute("SELECT filename, tags FROM image_tags LIMIT 5")
    rows = cursor.fetchall()
    
    print("\n--- DB Tag Dump (First 5) ---")
    if not rows:
        print("No tags found.")
    for row in rows:
        print(f"File: {row[0]}")
        print(f"Tags: {row[1]}")
        print("-" * 30)
    conn.close()
except Exception as e:
    print(f"Error: {e}")
