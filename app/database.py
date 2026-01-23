"""
GoodGallery Database Layer
SQLite operations for image tags
"""

import sqlite3
import os
import re
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_directory()
        self._init_schema()
    
    def _ensure_directory(self):
        """Create database directory if it doesn't exist"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_schema(self):
        """Create tables if they don't exist"""
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS image_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    tags TEXT,
                    tags_clean TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS consolidation_rules (
                    original_tag TEXT PRIMARY KEY,
                    replacement_tags TEXT,
                    status TEXT DEFAULT 'pending', -- pending, approved, rejected
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for faster searches
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_filename 
                ON image_tags(filename)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tags 
                ON image_tags(tags)
            """)

            # Check for tags_clean column (migration)
            cursor = conn.execute("PRAGMA table_info(image_tags)")
            columns = [info['name'] for info in cursor.fetchall()]
            if 'tags_clean' not in columns:
                print("Migrating database: Adding tags_clean column...")
                conn.execute("ALTER TABLE image_tags ADD COLUMN tags_clean TEXT")
    
    def get_tagged_filenames(self) -> set:
        """Get set of all tagged filenames (case-insensitive)"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT filename FROM image_tags WHERE tags IS NOT NULL AND tags != ''")
            return {row['filename'].lower() for row in cursor}
    
    def get_tags(self, filename: str) -> Optional[str]:
        """Get tags for a specific file"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT tags FROM image_tags WHERE filename = ? COLLATE NOCASE",
                (filename,)
            )
            row = cursor.fetchone()
            return row['tags'] if row else None
    
    def _clean_tags(self, tags_str: Optional[str]) -> Optional[str]:
        """
        Clean tag string by removing bullets and extra whitespace
        Input: "* tag1, - tag2, normal tag"
        Output: "tag1, tag2, normal tag"
        """
        if not tags_str:
            return None
            
        # Split by comma
        parts = tags_str.split(',')
        cleaned = []
        
        for p in parts:
            # Remove leading bullets (*, -, •, +), brackets, and whitespace
            # Regex: start of string, optional whitespace, one or more bullets/brackets, optional whitespace
            clean_p = re.sub(r'^\s*[\*\-•+\[\]\(\)]+\s*', '', p).strip()
            if clean_p:
                cleaned.append(clean_p)
                
        return ', '.join(cleaned)
    
    def save_tags(self, filename: str, tags: str):
        """
        Save or update tags for a file
        Uses INSERT OR REPLACE for upsert behavior
        """
        # Clean tags before saving
        clean_tags = self._clean_tags(tags)
        
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO image_tags (filename, tags, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(filename) DO UPDATE SET
                    tags = excluded.tags,
                    updated_at = CURRENT_TIMESTAMP
            """, (filename, clean_tags))
    
    def save_tags_batch(self, items: List[Dict[str, str]]):
        """
        Batch save tags for multiple files
        items: [{"filename": "...", "tags": "..."}, ...]
        """
        with self.get_connection() as conn:
            for item in items:
                filename = item.get('filename')
                tags = item.get('tags', '')
                
                # Convert list to comma-separated string if needed
                if isinstance(tags, list):
                    tags = ','.join(tags)
                
                # Clean tags
                clean_tags = self._clean_tags(tags)
                
                conn.execute("""
                    INSERT INTO image_tags (filename, tags, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(filename) DO UPDATE SET
                        tags = excluded.tags,
                        updated_at = CURRENT_TIMESTAMP
                """, (filename, clean_tags))
    
    def delete_tags(self, filename: str):
        """Delete tags entry for a file"""
        with self.get_connection() as conn:
            conn.execute(
                "DELETE FROM image_tags WHERE filename = ? COLLATE NOCASE",
                (filename,)
            )
    
    def search_by_tags(self, search_terms: List[Tuple[str, bool]]) -> List[str]:
        """
        Search for files by tags using boolean logic with whole-word matching.
        
        Matches PHP reference behavior (api.php lines 274-281):
        Uses REGEXP with word boundaries to avoid substring matches.
        
        search_terms: [(term, is_negative), ...]
        Example: [("beach", False), ("sunset", False), ("people", True)]
        = has beach AND sunset AND NOT people
        
        Returns: list of matching filenames
        """
        if not search_terms:
            return []
        
        # Build WHERE clause with REGEXP for each term
        conditions = []
        params = []
        
        for term, is_negative in search_terms:
            # Match complete tags in comma-separated list
            # Pattern matches:
            # - ^term$ (entire string is just this tag)
            # - ^term, (tag at start of list)
            # - ,term, (tag in middle of list)  
            # - ,term$ (tag at end of list)
            # With optional whitespace around commas
            escaped_term = re.escape(term.lower())
            # Match tag boundaries: start/end of string OR comma
            # Allow for optional spaces, bullets (*, -) around the term
            # This handles dirty data like "* tagname" or "- tagname" often produced by LLMs
            pattern = fr"(?:^|,)\s*(?:[\*\-\s]*){escaped_term}(?:[\*\-\s]*)(?:,|$)"
            
            if is_negative:
                conditions.append("tags NOT REGEXP ?")
            else:
                conditions.append("tags REGEXP ?")
            
            params.append(pattern)
        
        query = f"""
            SELECT filename FROM image_tags 
            WHERE {' AND '.join(conditions)}
        """
        
        with self.get_connection() as conn:
            # Register REGEXP function for SQLite
            def regexp(pattern, string):
                """Case-insensitive REGEXP for SQLite"""
                if string is None:
                    return False
                return re.search(pattern, string, re.IGNORECASE) is not None
            
            conn.create_function("REGEXP", 2, regexp)
            
            cursor = conn.execute(query, params)
            return [row['filename'] for row in cursor]
    
    def get_stats(self) -> Dict[str, int]:
        """Get database statistics"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) as total FROM image_tags")
            total = cursor.fetchone()['total']
            
            cursor = conn.execute(
                "SELECT COUNT(*) as tagged FROM image_tags WHERE tags IS NOT NULL AND tags != ''"
            )
            tagged = cursor.fetchone()['tagged']
            
            return {
                'total_entries': total,
                'tagged': tagged,
                'untagged': total - tagged
            }
    
    def get_all_tags(self) -> Dict[str, int]:
        """
        Get all unique tags with their frequencies
        Returns: {"tag": count, ...}
        """
        tag_counts = {}
        
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT tags FROM image_tags WHERE tags IS NOT NULL")
            
            for row in cursor:
                if row['tags']:
                    # Split by comma and count each tag
                    tags = [t.strip().lower() for t in row['tags'].split(',')]
                    for tag in tags:
                        if tag:
                            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        return tag_counts
    
    def get_top_tags(self, limit: int = 50, min_count: int = 2) -> List[Tuple[str, int]]:
        """
        Get most common tags
        Returns: [(tag, count), ...] sorted by frequency
        """
        tag_counts = self.get_all_tags()
        
        # Filter by minimum count and sort
        filtered = [(tag, count) for tag, count in tag_counts.items() if count >= min_count]
        filtered.sort(key=lambda x: x[1], reverse=True)
        
        return filtered[:limit]

    # --- Consolidation Rules ---
    
    def save_consolidation_rule(self, original: str, replacements: List[str], status: str = 'pending'):
        """Save a tag consolidation rule"""
        import json
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO consolidation_rules (original_tag, replacement_tags, status, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(original_tag) DO UPDATE SET
                    replacement_tags = excluded.replacement_tags,
                    status = excluded.status
            """, (original, json.dumps(replacements), status))

    def get_consolidation_rules(self, status: str = None) -> List[Dict]:
        """Get all consolidation rules, optionally filtered by status"""
        query = "SELECT * FROM consolidation_rules"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
            
        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            import json
            results = []
            for row in cursor:
                results.append({
                    'original_tag': row['original_tag'],
                    'replacement_tags': json.loads(row['replacement_tags']),
                    'status': row['status'],
                    'created_at': row['created_at']
                })
            return results

    def save_clean_tags_batch(self, items: List[Dict[str, str]]):
        """
        Batch save CLEAN tags for multiple files
        items: [{"filename": "...", "tags_clean": "..."}, ...]
        """
        with self.get_connection() as conn:
            for item in items:
                conn.execute("""
                    UPDATE image_tags 
                    SET tags_clean = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE filename = ?
                """, (item['tags_clean'], item['filename']))
                
    def get_clean_tags(self, filename: str) -> Optional[str]:
        """Get clean tags for a specific file"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT tags_clean FROM image_tags WHERE filename = ? COLLATE NOCASE",
                (filename,)
            )
            row = cursor.fetchone()
            return row['tags_clean'] if row else None
