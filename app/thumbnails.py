"""
GoodGallery Thumbnail Generator
Handles on-demand thumbnail creation with caching
Ported from PHP GD logic to use Pillow
"""

import os
from PIL import Image
from typing import Optional, Tuple


class ThumbnailGenerator:
    def __init__(self, source_dir: str, thumb_dir: str, size: int = 200):
        """
        Args:
            source_dir: Directory containing original images
            thumb_dir: Directory to store thumbnails
            size: Thumbnail size (width and height)
        """
        self.source_dir = source_dir
        self.thumb_dir = thumb_dir
        self.size = size
        
        # Create thumbnail directory if it doesn't exist
        os.makedirs(thumb_dir, exist_ok=True)
    
    def get_thumbnail_path(self, filename: str) -> str:
        """Get the full path for a thumbnail"""
        return os.path.join(self.thumb_dir, filename)
    
    def thumbnail_exists(self, filename: str) -> bool:
        """Check if thumbnail already exists"""
        return os.path.exists(self.get_thumbnail_path(filename))
    
    def create_thumbnail(self, filename: str) -> Optional[str]:
        """
        Create a square thumbnail for an image
        
        Logic ported from PHP index.php:311-341
        - Crop to center square
        - Resize to target size
        - Preserve transparency for PNG/WebP
        
        Returns: Path to thumbnail if successful, None otherwise
        """
        source_path = os.path.join(self.source_dir, filename)
        thumb_path = self.get_thumbnail_path(filename)
        
        # Sanity check
        if not os.path.exists(source_path):
            return None
        
        try:
            # Open image
            with Image.open(source_path) as img:
                # Convert to RGB if needed (handles RGBA, P, etc.)
                # But preserve alpha for PNG/WebP
                if img.mode in ('RGBA', 'LA', 'PA'):
                    # Has transparency
                    background = Image.new('RGBA', img.size, (255, 255, 255, 0))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, (0, 0), img)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Get dimensions
                width, height = img.size
                
                # Calculate center crop to square (same logic as PHP)
                min_dim = min(width, height)
                x = (width - min_dim) // 2
                y = (height - min_dim) // 2
                
                # Crop to center square
                img_cropped = img.crop((x, y, x + min_dim, y + min_dim))
                
                # Resize to thumbnail size (high quality)
                img_thumb = img_cropped.resize((self.size, self.size), Image.Resampling.LANCZOS)
                
                # Save thumbnail
                # Preserve format if possible, otherwise use JPEG
                ext = os.path.splitext(filename)[1].lower()
                
                if ext in ['.png', '.webp']:
                    # Preserve transparency
                    img_thumb.save(thumb_path, optimize=True)
                elif ext == '.gif':
                    img_thumb.save(thumb_path, format='GIF')
                else:
                    # JPEG with quality 80 (matches PHP)
                    if img_thumb.mode == 'RGBA':
                        img_thumb = img_thumb.convert('RGB')
                    img_thumb.save(thumb_path, format='JPEG', quality=80, optimize=True)
                
                return thumb_path
                
        except Exception as e:
            print(f"Error creating thumbnail for {filename}: {e}")
            return None
    
    def get_or_create(self, filename: str) -> Optional[str]:
        """
        Get thumbnail path, creating it if necessary
        """
        if self.thumbnail_exists(filename):
            return self.get_thumbnail_path(filename)
        
        return self.create_thumbnail(filename)

    def validate_cache(self):
        """
        Check all existing thumbnails against configured size.
        Delete those that don't match so they get regenerated.
        """
        if not os.path.exists(self.thumb_dir):
            return

        print("Validating thumbnail cache...")
        count = 0
        deleted = 0
        
        for filename in os.listdir(self.thumb_dir):
            if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                continue
                
            path = os.path.join(self.thumb_dir, filename)
            try:
                count += 1
                with Image.open(path) as img:
                    if img.size != (self.size, self.size):
                        # Close explicit (though context manager does it) before delete
                        pass
                
                # Check outcome (re-open to be safe/clean or just rely on logic? 
                # Actually, context manager closes it.
                # Let's do it cleanly:
                
                is_valid = False
                with Image.open(path) as img:
                    is_valid = (img.size == (self.size, self.size))
                
                if not is_valid:
                    os.remove(path)
                    deleted += 1
            except Exception as e:
                print(f"Error checking thumbnail {filename}: {e}")
                
        print(f"Thumbnail validation complete. Checked {count}, deleted {deleted} invalid.")
    
    def delete_thumbnail(self, filename: str) -> bool:
        """Delete a thumbnail file"""
        thumb_path = self.get_thumbnail_path(filename)
        
        if os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
                return True
            except Exception as e:
                print(f"Error deleting thumbnail {filename}: {e}")
                return False
        
        return False
