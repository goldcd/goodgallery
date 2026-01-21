import sqlite3
import os

conn = sqlite3.connect(os.path.join('data', 'gallery.db'))
cursor = conn.cursor()
cursor.execute("SELECT filename, tags FROM image_tags LIMIT 10")
rows = cursor.fetchall()

print("\n=== Current Tags Sample (First 10) ===\n")
for row in rows:
    print(f"File: {row[0]}")
    tags = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
    print(f"Tags: {tags}")
    
    # Check for prompt leakage
    if any(word in row[1].lower() for word in ['analyze', 'generate', 'keywords', 'include']):
        print("  ⚠️  WARNING: Possible prompt leakage detected!")
    print("-" * 50)

conn.close()
