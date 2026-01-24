"""
GoodGallery Core Logic
File scanning, caching, search, and filtering
Ported from PHP index.php
"""

import os
import json
import time
from typing import List, Dict, Optional, Tuple
import re


class Gallery:
    def __init__(self, photo_dir: str, cache_dir: str, allowed_extensions: List[str]):
        """
        Args:
            photo_dir: Directory containing photos
            cache_dir: Directory for cache files
            allowed_extensions: List of allowed file extensions (e.g., ['jpg', 'png'])
        """
        self.photo_dir = photo_dir
        self.cache_dir = cache_dir
        self.allowed_extensions = [ext.lower() for ext in allowed_extensions]
        self.index_file = os.path.join(cache_dir, 'file_index.json')
        
        # Create cache directory
        os.makedirs(cache_dir, exist_ok=True)
    
    def get_file_index(self, force_rebuild: bool = False) -> List[Dict[str, any]]:
        """
        Get cached file index or rebuild if necessary
        
        Ported from PHP index.php:130-199 (Smart Cache logic)
        
        Returns: [{"name": filename, "time": mtime}, ...]
        """
        dir_mtime = os.path.getmtime(self.photo_dir)
        index_mtime = os.path.getmtime(self.index_file) if os.path.exists(self.index_file) else 0
        
        # Check if rebuild needed
        if force_rebuild or not os.path.exists(self.index_file) or dir_mtime > index_mtime:
            return self._rebuild_index()
        
        # Load from cache
        try:
            with open(self.index_file, 'r') as f:
                files = json.load(f)
                return files if isinstance(files, list) else []
        except Exception as e:
            print(f"Error loading file index: {e}")
            return self._rebuild_index()
    
    def _rebuild_index(self) -> List[Dict[str, any]]:
        """
        Rebuild file index by scanning directory
        
        Incremental scan logic from PHP (lines 143-193)
        """
        print(f"Scanning photo directory: {self.photo_dir}")
        
        files = []
        known_files = set()
        
        # Load existing cache if available (for incremental update)
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r') as f:
                    existing = json.load(f)
                    if isinstance(existing, list):
                        # Filter out files that no longer exist on disk
                        for f_item in existing:
                            file_path = os.path.join(self.photo_dir, f_item['name'])
                            if os.path.exists(file_path):
                                files.append(f_item)
                                known_files.add(f_item['name'])
            except:
                pass
        
        # Scan directory for new files
        has_changes = False
        
        try:
            for filename in os.listdir(self.photo_dir):
                # Skip if already in cache
                if filename in known_files:
                    continue
                
                # Skip hidden files and metadata
                if filename.startswith('.') or filename.startswith('._'):
                    continue
                
                filepath = os.path.join(self.photo_dir, filename)
                
                # Only process files (not directories)
                if not os.path.isfile(filepath):
                    continue
                
                # Check extension
                ext = os.path.splitext(filename)[1].lower().lstrip('.')
                if ext not in self.allowed_extensions:
                    continue
                
                # Skip zero-byte files
                try:
                    if os.path.getsize(filepath) == 0:
                        continue
                except OSError:
                    continue
                
                # Add new file
                files.append({
                    'name': filename,
                    'time': int(os.path.getmtime(filepath))
                })
                has_changes = True
        
        except Exception as e:
            print(f"Error scanning directory: {e}")
        
        # Check if files were removed
        if len(files) != len(known_files) + (1 if has_changes else 0):
            has_changes = True
        
        # Sort by time (newest first) - PHP line 183
        files.sort(key=lambda x: x['time'], reverse=True)
        
        # Save cache if changes
        if has_changes or not os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'w') as f:
                    json.dump(files, f)
            except Exception as e:
                print(f"Error saving file index: {e}")
        
        print(f"Index complete: {len(files)} images found")
        return files
    
    def sort_files(self, files: List[Dict], sort_method: str = 'date_desc') -> List[Dict]:
        """
        Sort files based on method
        
        methods:
        - date_desc (default): Newest first
        - date_asc: Oldest first
        - name_asc: A-Z
        - name_desc: Z-A
        """
        if not files:
            return []
            
        if sort_method == 'date_asc':
            return sorted(files, key=lambda x: x['time'])
        elif sort_method == 'name_asc':
            return sorted(files, key=lambda x: x['name'].lower())
        elif sort_method == 'name_desc':
            return sorted(files, key=lambda x: x['name'].lower(), reverse=True)
        else: # date_desc (default)
            return sorted(files, key=lambda x: x['time'], reverse=True)

    def search_by_filename(self, files: List[Dict], query: str) -> List[Dict]:
        """
        Filter files by filename
        
        Ported from PHP lines 210-214
        """
        if not query:
            return files
        
        query_lower = query.lower()
        return [f for f in files if query_lower in f['name'].lower()]
    
    def parse_tag_search(self, query: str) -> List[Tuple[str, bool]]:
        """
        Parse boolean tag search query
        
        Supports:
        - word = AND
        - +word = AND (explicit)
        - -word = NOT
        - "multi word" = quoted phrases
        
        Ported from PHP lines 218-245
        
        Returns: [(term, is_negative), ...]
        """
        # Regex from PHP: ([+-]?)(?:"([^"]*)"|([^\s"]+))
        pattern = r'([+-]?)(?:"([^"]*)"|([^\s"]+))'
        matches = re.findall(pattern, query)
        
        terms = []
        for prefix, quoted, unquoted in matches:
            term = quoted if quoted else unquoted
            term = term.strip()
            
            if not term:
                continue
            
            is_negative = (prefix == '-')
            terms.append((term, is_negative))
        
        return terms
    
    def paginate(self, files: List[Dict], page: int, per_page: int) -> Tuple[List[Dict], bool]:
        """
        Paginate file list
        
        Returns: (page_files, has_more)
        """
        if page < 1:
            page = 1
        
        offset = (page - 1) * per_page
        page_files = files[offset:offset + per_page]
        has_more = len(files) > offset + per_page
        
        return page_files, has_more
    
    def delete_image(self, filename: str) -> bool:
        """
        Move image to 'removed' directory
        
        Ported from PHP lines 77-122
        """
        source_path = os.path.join(self.photo_dir, filename)
        removed_dir = os.path.join(self.photo_dir, 'removed')
        dest_path = os.path.join(removed_dir, filename)
        
        # Create removed directory
        os.makedirs(removed_dir, exist_ok=True)
        
        # Move file
        if not os.path.exists(source_path):
            return False
        
        try:
            os.rename(source_path, dest_path)
            
            # Remove from cache
            self._remove_from_cache(filename)
            
            return True
        except Exception as e:
            print(f"Error deleting {filename}: {e}")
            return False
    
    def _remove_from_cache(self, filename: str):
        """Remove a file from the cached index"""
        if not os.path.exists(self.index_file):
            return
        
        try:
            with open(self.index_file, 'r') as f:
                files = json.load(f)
            
            if isinstance(files, list):
                # Filter out the deleted file
                files = [f for f in files if f['name'] != filename]
                
                with open(self.index_file, 'w') as f:
                    json.dump(files, f)
        except Exception as e:
            print(f"Error updating cache: {e}")
