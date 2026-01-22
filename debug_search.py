import sqlite3
import re
import os

DB_PATH = 'data/gallery.db'

def regexp(pattern, string):
    if string is None:
        return False
    return re.search(pattern, string, re.IGNORECASE) is not None

def check_db():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, regexp)
    
    # 1. Check if "laughing" exists in any tags
    print("--- Searching DB for 'laughing' ---")
    cursor = conn.execute("SELECT filename, tags FROM image_tags WHERE tags LIKE '%laughing%'")
    rows = cursor.fetchall()
    if not rows:
        print("No tags containing 'laughing' found.")
    else:
        for row in rows:
            print(f"Found in: {row['filename']}")
            print(f"Tags: '{row['tags']}'")

            # 2. Test the specific regex logic used in app
            term = "laughing"
            escaped_term = re.escape(term.lower())
            # New regex pattern
            pattern = fr"(?:^|,)\s*(?:[\*\-\s]*){escaped_term}(?:[\*\-\s]*)(?:,|$)"
            
            print(f"Testing regex '{pattern}' against tags...")
            match = re.search(pattern, row['tags'], re.IGNORECASE)
            print(f"Match result: {bool(match)}")
            
            # 3. Test SQL query with REGEXP
            print("Testing SQL REGEXP...")
            c2 = conn.execute("SELECT filename FROM image_tags WHERE filename=? AND tags REGEXP ?", (row['filename'], pattern))
            if c2.fetchone():
                print("SQL REGEXP matched!")
            else:
                print("SQL REGEXP FAILED!")

    conn.close()

if __name__ == '__main__':
    check_db()
