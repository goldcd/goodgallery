import sys
import os
import re

# Add parent dir to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Database

def clean_tag(tag_str):
    if not tag_str:
        return None
    
    # Same logic as in Database._clean_tags
    parts = tag_str.split(',')
    cleaned = []
    
    for p in parts:
        # Remove leading bullets (*, -, •, +), brackets, and whitespace
        clean_p = re.sub(r'^\s*[\*\-•+\[\]\(\)]+\s*', '', p).strip()
        if clean_p:
            cleaned.append(clean_p)
            
    return ', '.join(cleaned)

def main():
    db_path = os.path.join('data', 'gallery.db')
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    print(f"Opening database: {db_path}")
    db = Database(db_path)
    
    count = 0
    modified = 0
    
    with db.get_connection() as conn:
        # Get all rows
        cursor = conn.execute("SELECT filename, tags FROM image_tags")
        rows = cursor.fetchall()
        
        print(f"Scanning {len(rows)} entries...")
        
        for row in rows:
            filename = row['filename']
            original_tags = row['tags']
            
            if not original_tags:
                continue
                
            cleaned_tags = clean_tag(original_tags)
            
            if cleaned_tags != original_tags:
                # Update DB
                conn.execute(
                    "UPDATE image_tags SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE filename = ?",
                    (cleaned_tags, filename)
                )
                print(f"Cleaned [{filename}]: '{original_tags}' -> '{cleaned_tags}'")
                modified += 1
            
            count += 1
            
    print(f"\nScan complete.")
    print(f"Processed: {count}")
    print(f"Modified: {modified}")

if __name__ == '__main__':
    main()
