"""
File System Monitor for GoodGallery
Watches the photos directory for changes and updates the database accordingly
"""

import os
import time
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileDeletedEvent
import platform

def is_wsl():
    return platform.system() == 'Linux' and 'microsoft' in platform.release().lower()

class WSLSafeObserver(threading.Thread):
    """
    A lightweight mtime-based polling observer for WSL.
    Avoids fatal memory leaks caused by inotify on drvfs mounts,
    and avoids the CPU thrashing of watchdog's PollingObserver.
    """
    def __init__(self):
        super().__init__()
        self.photo_dir = None
        self.event_handler = None
        self.running = True
        self.daemon = True
        
    def schedule(self, event_handler, path, recursive=False):
        self.photo_dir = path
        self.event_handler = event_handler
        
    def run(self):
        if not self.photo_dir:
            return
            
        last_mtime = 0
        last_files = set()
        
        while self.running:
            try:
                current_mtime = os.path.getmtime(self.photo_dir)
                if current_mtime != last_mtime:
                    current_files = set(os.listdir(self.photo_dir))
                    
                    if last_mtime != 0:
                        added = current_files - last_files
                        removed = last_files - current_files
                        
                        for f in added:
                            self.event_handler.on_created(FileCreatedEvent(os.path.join(self.photo_dir, f)))
                        for f in removed:
                            self.event_handler.on_deleted(FileDeletedEvent(os.path.join(self.photo_dir, f)))
                            
                    last_mtime = current_mtime
                    last_files = current_files
            except Exception:
                pass
                
            time.sleep(2.0)
            
    def stop(self):
        self.running = False


class PhotoDirectoryWatcher(FileSystemEventHandler):
    """Monitors photo directory for file changes"""
    
    def __init__(self, photo_dir, db, thumbs, allowed_extensions):
        self.photo_dir = Path(photo_dir)
        self.db = db
        self.thumbs = thumbs
        self.allowed_extensions = set(ext.lower() for ext in allowed_extensions)
        
        # Debouncing
        self.pending_events = {}
        self.debounce_timer = None
        self.lock = threading.Lock()
        
    def _is_valid_image(self, path):
        """Check if file is a valid image"""
        if not os.path.isfile(path):
            return False
            
        filename = os.path.basename(path)
        # Skip hidden files and Mac metadata
        if filename.startswith('.') or filename.startswith('._'):
            return False
        
        try:
            # Skip zero-byte files
            if os.path.getsize(path) == 0:
                return False
        except OSError:
            return False
        
        ext = Path(path).suffix.lower().lstrip('.')
        return ext in self.allowed_extensions
    
    def _debounce_event(self, event_type, path):
        """Debounce file system events to avoid processing temp files"""
        with self.lock:
            event_key = f"{event_type}:{path}"
            self.pending_events[event_key] = (event_type, path, time.time())
            
            # Cancel existing timer
            if self.debounce_timer:
                self.debounce_timer.cancel()
            
            # Start new timer
            self.debounce_timer = threading.Timer(2.0, self._process_pending_events)
            self.debounce_timer.start()
    
    def _process_pending_events(self):
        """Process all pending events after debounce period"""
        with self.lock:
            events = list(self.pending_events.values())
            self.pending_events.clear()
        
        for event_type, path, timestamp in events:
            try:
                if event_type == 'created':
                    self._handle_created(path)
                elif event_type == 'deleted':
                    self._handle_deleted(path)
                elif event_type == 'moved':
                    # path is actually (src, dest) tuple for moves
                    self._handle_moved(path[0], path[1])
            except Exception as e:
                print(f"⚠️  Error processing {event_type} event for {path}: {e}")
    
    def _handle_created(self, path):
        """Handle new photo added"""
        if not self._is_valid_image(path):
            return
        
        filename = os.path.basename(path)
        print(f"📸 New photo detected: {filename}")
        
        # Photo will be picked up by next untagged scan
        # Database entry will be created when tagged
    
    def _handle_deleted(self, path):
        """Handle photo deleted"""
        filename = os.path.basename(path)
        
        # Remove from database
        deleted = self.db.delete_tags(filename)
        
        # Remove thumbnail
        self.thumbs.delete_thumbnail(filename)
        
        if deleted:
            print(f"🗑️  Removed photo from database: {filename}")
    
    def _handle_moved(self, src_path, dest_path):
        """Handle photo renamed/moved"""
        if not self._is_valid_image(dest_path):
            return
            
        src_filename = os.path.basename(src_path)
        dest_filename = os.path.basename(dest_path)
        
        # Get existing tags
        tags = self.db.get_tags(src_filename)
        
        if tags:
            # Delete old entry
            self.db.delete_tags(src_filename)
            
            # Create new entry with same tags
            self.db.save_tags_batch([{
                'filename': dest_filename,
                'tags': tags
            }])
            
            print(f"📝 Renamed photo: {src_filename} → {dest_filename}")
        
        # Remove old thumbnail
        self.thumbs.delete_thumbnail(src_filename)
    
    def on_created(self, event):
        """Watchdog callback: file created"""
        if event.is_directory:
            return
        self._debounce_event('created', event.src_path)
    
    def on_deleted(self, event):
        """Watchdog callback: file deleted"""
        if event.is_directory:
            return
        self._debounce_event('deleted', event.src_path)
    
    def on_moved(self, event):
        """Watchdog callback: file moved/renamed"""
        if event.is_directory:
            return
        self._debounce_event('moved', (event.src_path, event.dest_path))


def start_file_watcher(photo_dir, db, thumbs, allowed_extensions):
    """
    Start watching the photo directory for changes
    
    Args:
        photo_dir: Path to photo directory
        db: Database instance
        thumbs: ThumbnailGenerator instance
        allowed_extensions: List of allowed image extensions
    
    Returns:
        Observer instance (already started)
    """
    if not os.path.exists(photo_dir):
        print(f"⚠️  Photo directory not found: {photo_dir}")
        print("   File monitoring disabled")
        return None
    
    event_handler = PhotoDirectoryWatcher(photo_dir, db, thumbs, allowed_extensions)
    
    if is_wsl():
        print("🔧 WSL detected: Using lightweight mtime polling observer")
        observer = WSLSafeObserver()
    else:
        observer = Observer()
        
    observer.schedule(event_handler, photo_dir, recursive=False)
    observer.start()
    
    print(f"👁️  Watching for file changes: {photo_dir}")
    
    return observer


def stop_file_watcher(observer):
    """Stop the file watcher"""
    if observer:
        observer.stop()
        observer.join()
