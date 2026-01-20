"""
GoodGallery Flask Server
Main web application
"""

import os
import sys

# Add parent directory to path for direct execution
if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from flask import Flask, render_template, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

from app.database import Database
from app.gallery import Gallery
from app.thumbnails import ThumbnailGenerator
from app.ai_tagger import AITagger
from app.file_monitor import start_file_watcher


# Load configuration
def load_config():
    config_path = 'config.yaml'
    if not os.path.exists(config_path):
        # Try example config
        config_path = 'config.yaml.example'
    
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


# Initialize app
app = Flask(__name__)
config = load_config()

# Initialize components
db = Database(config['database']['path'])
gallery = Gallery(
    config['gallery']['photo_directory'],
    'data/cache',
    config['gallery']['allowed_extensions']
)
thumbs = ThumbnailGenerator(
    config['gallery']['photo_directory'],
    'data/thumbnails',
    config['gallery']['thumbnail_size']
)

# AI Tagger (lazy load)
ai_tagger = None


def get_ai_tagger():
    """Lazy load AI tagger (only when needed)"""
    global ai_tagger
    if ai_tagger is None:
        ai_tagger = AITagger(
            model_id=config['ai']['model'],
            use_quantization=config['ai']['use_quantization'],
            batch_size=config['ai']['batch_size']
        )
    return ai_tagger


# --- WEB ROUTES ---

@app.route('/')
def index():
    """Main gallery page"""
    # Get search parameters
    search_query = request.args.get('q', '').strip()
    search_type = request.args.get('t', 'tag')  # 'tag' or 'name'
    page = int(request.args.get('page', 1))
    
    # Get all files
    files = gallery.get_file_index()
    
    # Apply search
    if search_query:
        if search_type == 'name':
            # Filename search
            files = gallery.search_by_filename(files, search_query)
        else:
            # Tag search
            search_terms = gallery.parse_tag_search(search_query)
            matching_filenames = db.search_by_tags(search_terms)
            
            # Filter files to only matching ones
            matching_set = set(f.lower() for f in matching_filenames)
            files = [f for f in files if f['name'].lower() in matching_set]
    
    # Paginate
    per_page = config['gallery']['images_per_page']
    page_files, has_more = gallery.paginate(files, page, per_page)
    
    # Get stats
    stats = db.get_stats()
    total_files = len(gallery.get_file_index())
    
    return render_template('index.html',
        files=page_files,
        search_query=search_query,
        search_type=search_type,
        page=page,
        has_more=has_more,
        total_files=total_files,
        tagged_count=stats['tagged'],
    )


@app.route('/thumb/<path:filename>')
def serve_thumbnail(filename):
    """Generate and serve thumbnail"""
    filename = secure_filename(filename)
    
    # Get or create thumbnail
    thumb_path = thumbs.get_or_create(filename)
    
    if thumb_path and os.path.exists(thumb_path):
        return send_file(thumb_path)
    
    # Fallback to original if thumbnail fails
    original_path = os.path.normpath(os.path.join(gallery.photo_dir, filename))
    if os.path.exists(original_path):
        return send_file(original_path)
    
    abort(404)


@app.route('/img/<path:filename>')
def serve_image(filename):
    """Serve original image"""
    filename = secure_filename(filename)
    image_path = os.path.join(gallery.photo_dir, filename)
    
    if os.path.exists(image_path):
        return send_file(image_path)
    
    abort(404)


# --- API ROUTES (ported from api.php) ---

@app.route('/api/stats')
def api_stats():
    """Get tagging statistics"""
    stats = db.get_stats()
    all_files = gallery.get_file_index()
    
    return jsonify({
        'status': 'ok',
        'total': len(all_files),
        'tagged': stats['tagged'],
        'untagged': len(all_files) - stats['tagged']
    })


@app.route('/api/untagged')
def api_untagged():
    """Get list of untagged images"""
    limit = int(request.args.get('limit', 50))
    
    # Get all files
    all_files = gallery.get_file_index()
    tagged = db.get_tagged_filenames()
    
    # Find untagged
    untagged = []
    for file_info in all_files:
        if file_info['name'].lower() not in tagged:
            untagged.append(file_info['name'])
            if len(untagged) >= limit:
                break
    
    return jsonify({
        'status': 'ok',
        'files': untagged
    })


@app.route('/api/save_tags', methods=['POST'])
def api_save_tags():
    """Save tags for one or more images"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Invalid input'}), 400
    
    # Handle single or batch format
    items = []
    if isinstance(data, dict) and 'filename' in data:
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        return jsonify({'error': 'Invalid format'}), 400
    
    # Save to database
    db.save_tags_batch(items)
    
    return jsonify({
        'status': 'ok',
        'processed': len(items)
    })


@app.route('/api/tags')
def api_tags():
    """Get all tags with frequencies"""
    min_count = int(request.args.get('min_count', 2))
    limit = int(request.args.get('limit', 100))
    
    top_tags = db.get_top_tags(limit=limit, min_count=min_count)
    
    # Return as simple list of tag names
    return jsonify([tag for tag, count in top_tags])


@app.route('/api/related_tags')
def api_related_tags():
    """Get related tags for a search query"""
    search_query = request.args.get('q', '').strip()
    
    if not search_query:
        # Return popular tags
        top_tags = db.get_top_tags(limit=30)
        return jsonify({tag: count for tag, count in top_tags})
    
    # Parse search and get matching files
    search_terms = gallery.parse_tag_search(search_query)
    matching_filenames = db.search_by_tags(search_terms)
    
    # Count tags in matching images
    tag_counts = {}
    for filename in matching_filenames:
        tags_str = db.get_tags(filename)
        if tags_str:
            tags = [t.strip().lower() for t in tags_str.split(',')]
            for tag in tags:
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
    
    # Sort and return top 30
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    
    return jsonify({tag: count for tag, count in sorted_tags})


@app.route('/api/tag_batch', methods=['POST'])
def api_tag_batch():
    """Tag a batch of images using AI"""
    data = request.get_json()
    filenames = data.get('files', [])
    
    if not filenames:
        return jsonify({'error': 'No files provided'}), 400
    
    # Load AI model
    tagger = get_ai_tagger()
    if not tagger.is_loaded:
        try:
            tagger.load_model()
        except Exception as e:
            return jsonify({'error': f'Failed to load model: {str(e)}'}), 500
    
    # Build full paths
    image_paths = [os.path.normpath(os.path.join(gallery.photo_dir, f)) for f in filenames]
    
    # Tag images
    try:
        results = tagger.tag_batch(image_paths)
        
        # Save to database
        db.save_tags_batch(results)
        
        return jsonify({
            'status': 'ok',
            'processed': len(results),
            'results': results
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete', methods=['POST'])
def api_delete():
    """Delete an image (move to removed folder)"""
    data = request.get_json()
    filename = data.get('filename')
    
    if not filename:
        return jsonify({'error': 'No filename provided'}), 400
    
    # Secure filename
    filename = secure_filename(filename)
    
    # Delete image
    if gallery.delete_image(filename):
        # Delete thumbnail
        thumbs.delete_thumbnail(filename)
        
        # Delete database entry
        db.delete_tags(filename)
        
        return jsonify({'status': 'ok'})
    else:
        return jsonify({'error': 'Failed to delete'}), 500


# --- MANUAL TAGGING STATE ---

import threading

tagging_state = {
    'running': False,
    'current': 0,
    'total': 0,
    'status': '',
    'error': None,
    'cancel_requested': False
}
tagging_lock = threading.Lock()
tagging_thread = None


@app.route('/api/start_tagging', methods=['POST'])
def api_start_tagging():
    """Start manual tagging process in background"""
    global tagging_thread
    
    with tagging_lock:
        if tagging_state['running']:
            return jsonify({'status': 'already_running'})
        
        # Reset state
        tagging_state['running'] = True
        tagging_state['current'] = 0
        tagging_state['total'] = 0
        tagging_state['status'] = 'Starting...'
        tagging_state['error'] = None
        tagging_state['cancel_requested'] = False
    
    # Start tagging in background
    tagging_thread = threading.Thread(target=manual_tagging_worker, daemon=True)
    tagging_thread.start()
    
    return jsonify({'status': 'started'})


@app.route('/api/tagging_status')
def api_tagging_status():
    """Get current tagging progress"""
    with tagging_lock:
        return jsonify({
            'running': tagging_state['running'],
            'current': tagging_state['current'],
            'total': tagging_state['total'],
            'status': tagging_state['status'],
            'error': tagging_state['error']
        })


@app.route('/api/cancel_tagging', methods=['POST'])
def api_cancel_tagging():
    """Cancel ongoing tagging process"""
    with tagging_lock:
        if tagging_state['running']:
            tagging_state['cancel_requested'] = True
            return jsonify({'status': 'cancelling'})
        else:
            return jsonify({'status': 'not_running'})


@app.route('/api/gpu_status')
def api_gpu_status():
    """Get GPU memory status"""
    tagger = get_ai_tagger()
    memory = tagger.get_memory_usage()
    return jsonify({
        'model_loaded': tagger.is_loaded,
        'memory': memory
    })


def manual_tagging_worker():
    """Background worker for manual tagging"""
    try:
        # Get untagged files
        all_files = gallery.get_file_index()
        tagged = db.get_tagged_filenames()
        
        untagged = [
            f['name'] for f in all_files
            if f['name'].lower() not in tagged
        ]
        
        with tagging_lock:
            tagging_state['total'] = len(untagged)
            tagging_state['status'] = f'Found {len(untagged)} untagged images'
        
        if not untagged:
            with tagging_lock:
                tagging_state['running'] = False
                tagging_state['status'] = 'No untagged images found'
            return
        
        # Load AI model
        with tagging_lock:
            tagging_state['status'] = 'Loading AI model...'
        
        tagger =get_ai_tagger()
        if not tagger.is_loaded:
            tagger.load_model()
        
        # Process in batches
        batch_size = config['ai']['batch_size']
        total = len(untagged)
        
        for i in range(0, total, batch_size):
            # Check for cancellation
            with tagging_lock:
                if tagging_state['cancel_requested']:
                    tagging_state['running'] = False
                    tagging_state['status'] = 'Cancelled by user'
                    break
            
            batch = untagged[i:i+batch_size]
            image_paths = [os.path.normpath(os.path.join(gallery.photo_dir, f)) for f in batch]
            
            # Update status
            with tagging_lock:
                tagging_state['status'] = f'Tagging batch {i//batch_size + 1}...'
            
            # Tag batch
            try:
                results = tagger.tag_batch(image_paths)
                db.save_tags_batch(results)
                
                # Update progress
                with tagging_lock:
                    tagging_state['current'] = min(i + batch_size, total)
            except Exception as e:
                with tagging_lock:
                    tagging_state['error'] = str(e)
                    tagging_state['running'] = False
                return
        
        # Unload model to free GPU memory
        if config['ai'].get('keep_model_loaded', False) == False:
            with tagging_lock:
                tagging_state['status'] = 'Unloading model...'
            tagger.unload_model()
        
        # Complete
        with tagging_lock:
            if not tagging_state['cancel_requested']:
                tagging_state['running'] = False
                tagging_state['status'] = f'✓ Tagged {total} images'
                tagging_state['current'] = total
    
    except Exception as e:
        with tagging_lock:
            tagging_state['running'] = False
            tagging_state['error'] = str(e)
            tagging_state['status'] = 'Error occurred'


# --- RUN SERVER ---

def auto_tag_on_startup():
    """Auto-tag untagged images on startup (runs in background)"""
    import time
    
    # Wait a moment for server to start
    time.sleep(2)
    
    try:
        print("🤖 Auto-tagging enabled - scanning for untagged images...")
        
        # Get untagged files
        all_files = gallery.get_file_index()
        tagged = db.get_tagged_filenames()
        
        untagged = [
            f['name'] for f in all_files 
            if f['name'].lower() not in tagged
        ]
        
        if not untagged:
            print("✓ All images are already tagged!\n")
            return
        
        print(f"   Found {len(untagged)} untagged images")
        print("   Starting AI tagging (this may take a while)...\n")
        
        # Load AI model
        tagger = get_ai_tagger()
        if not tagger.is_loaded:
            tagger.load_model()
        
        # Process in batches
        batch_size = config['ai']['batch_size']
        total = len(untagged)
        
        for i in range(0, total, batch_size):
            batch = untagged[i:i+batch_size]
            image_paths = [os.path.normpath(os.path.join(gallery.photo_dir, f)) for f in batch]
            
            # Tag batch
            results = tagger.tag_batch(image_paths)
            db.save_tags_batch(results)
            
            # Progress
            processed = min(i + batch_size, total)
            print(f"   Tagged {processed}/{total} images...")
        
        print(f"\n✓ Auto-tagging complete! Tagged {total} images")
        
        # Unload model to free GPU memory
        if config['ai'].get('keep_model_loaded', False) == False:
            print("🧹 Unloading model to free GPU memory...")
            tagger.unload_model()
        
    except Exception as e:
        print(f"\n⚠️  Auto-tagging failed: {e}")
        print("   You can still tag images manually from the web UI\n")


def run_server(host='127.0.0.1', port=None, debug=False):
    """Start Flask server"""
    if port is None:
        port = config['gallery']['port']
    
    # Startup info
    print("\n" + "="*60)
    print("   ✓ GoodGallery Started Successfully!")
    print("="*60)
    print(f"\n🌐 Server running at: http://{host}:{port}")
    print(f"📁 Photo directory: {config['gallery']['photo_directory']}")
    print(f"🏷️  Tagged images: {db.get_stats()['tagged']}")
    
    # Start file monitoring
    if config['gallery'].get('watch_for_changes', True):
        watcher = start_file_watcher(
            config['gallery']['photo_directory'],
            db,
            thumbs,
            config['gallery']['allowed_extensions']
        )
        if watcher:
            print("👁️  File monitoring: enabled")
    
    # Check auto-tag setting
    if config['ai'].get('auto_tag', False):
        print("🤖 Auto-tagging: enabled")
        
        # Start auto-tagging in background
        import threading
        thread = threading.Thread(target=auto_tag_on_startup, daemon=True)
        thread.start()
    else:
        print("🤖 Auto-tagging: disabled")
    
    print("\nPress Ctrl+C to stop\n")
    print("="*60 + "\n")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_server(debug=True)
