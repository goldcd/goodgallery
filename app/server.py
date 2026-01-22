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
import json
from flask import Flask, render_template, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename
from urllib.parse import unquote, quote

from app.database import Database
from app.gallery import Gallery
from app.thumbnails import ThumbnailGenerator
from app.ai_tagger import AITagger
from app.file_monitor import start_file_watcher


# Determine project root directory (one level up from app/)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load configuration
def load_config():
    config_path = os.path.join(ROOT_DIR, 'config.yaml')
    if not os.path.exists(config_path):
        # Try example config
        config_path = os.path.join(ROOT_DIR, 'config.yaml.example')
    
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


# Initialize app
app = Flask(__name__)
config = load_config()

# Resolve absolute paths
PHOTO_DIR = os.path.normpath(os.path.join(ROOT_DIR, config['gallery']['photo_directory']))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'gallery.db')

# Override config to use absolute path for server logic
config['gallery']['photo_directory'] = PHOTO_DIR

# Initialize components
db = Database(DB_PATH)
gallery = Gallery(
    PHOTO_DIR,
    os.path.join(DATA_DIR, 'cache'),
    config['gallery']['allowed_extensions']
)
thumbs = ThumbnailGenerator(
    PHOTO_DIR,
    os.path.join(DATA_DIR, 'thumbnails'),
    config['gallery']['thumbnail_size']
)

# AI Tagger (lazy load)
ai_tagger = None


def get_ai_tagger():
    """Lazy load AI tagger (only when needed)"""
    global ai_tagger
    if ai_tagger is None:
        prompt_from_config = config['ai'].get('tagging_prompt')
        
        # Use local models directory to keep it contained in project
        models_dir = os.path.join(ROOT_DIR, 'models')
        os.makedirs(models_dir, exist_ok=True)
        
        ai_tagger = AITagger(
            model_id=config['ai']['model'],
            use_quantization=config['ai']['use_quantization'],
            batch_size=config['ai']['batch_size'],
            tagging_prompt=prompt_from_config,
            cache_dir=models_dir
        )
        # Debug: Verify prompt source
        if prompt_from_config:
            print(f"✓ Using custom tagging prompt from config ({len(prompt_from_config)} chars)")
        else:
            print("ℹ Using default tagging prompt (config not set)")
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
    
    # Get tags for all files in current page
    tags_map = {}
    for file in page_files:
        tags_str = db.get_tags(file['name'])
        if tags_str:
            # Clean tags: remove asterisks and extra whitespace, and sort alphabetically
            tag_list = [tag.strip(' *') for tag in tags_str.split(',')]
            tag_list = sorted([t for t in tag_list if t], key=str.lower)
            cleaned_tags = ', '.join(tag_list)
            tags_map[file['name']] = cleaned_tags
        else:
            tags_map[file['name']] = None
    
    # Parse active tag states for UI
    active_tag_states = {}
    if search_type == 'tag' and search_query:
        search_terms = gallery.parse_tag_search(search_query)
        for term, is_negative in search_terms:
            active_tag_states[term.lower()] = 'exclude' if is_negative else 'include'

    return render_template('index.html',
        files=page_files,
        tags_map=tags_map,
        active_tag_states=active_tag_states,
        search_query=search_query,
        search_type=search_type,
        page=page,
        has_more=has_more,
        total_files=total_files,
        tagged_count=stats['tagged'],
    )


def resolve_file_path(base_dir, filename):
    """
    Helper to resolve file path with multiple encoding fallback checks
    Handles standard filenames, URL-encoded filenames, and double-encoded filenames
    """
    # 1. Check direct path
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        return path

    # 2. Check decoded path (e.g. %20 -> space)
    if '%' in filename:
        try:
            decoded = unquote(filename)
            path = os.path.join(base_dir, decoded)
            if os.path.exists(path):
                return path
        except:
            pass
            
    # 3. Check encoded path (e.g. space -> %20)
    # Some file systems/browsers might request unencoded but file IS encoded on disk
    try:
        encoded = quote(filename)
        if encoded != filename:
            path = os.path.join(base_dir, encoded)
            if os.path.exists(path):
                return path
    except:
        pass
        
    return None

@app.route('/thumb/<path:filename>')
def serve_thumbnail(filename):
    """Generate and serve thumbnail"""
    # Prevent directory traversal
    if '..' in filename or filename.startswith('/') or '\\' in filename:
        abort(404)
    
    # Get or create thumbnail
    thumb_path = thumbs.get_or_create(filename)
    
    # If standard get_or_create failed, try strict path resolution on source to see if we can find it
    # This handles edge cases where thumbnail generation might need to find the source first
    if not thumb_path:
        # Try to find source file using robust resolution
        source_path = resolve_file_path(gallery.photo_dir, filename)
        if source_path:
            # Found source, try creating thumbnail from this specific path
            # We need to extract the actual filename found on disk
            actual_filename = os.path.basename(source_path)
            thumb_path = thumbs.get_or_create(actual_filename)

    if thumb_path and os.path.exists(thumb_path):
        return send_file(thumb_path)
    
    # Fallback to original if thumbnail fails
    original_path = resolve_file_path(gallery.photo_dir, filename)
    if original_path:
        return send_file(original_path)
    
    abort(404)


@app.route('/img/<path:filename>')
def serve_image(filename):
    """Serve original image"""
    # Prevent directory traversal
    if '..' in filename or filename.startswith('/') or '\\' in filename:
        abort(404)
        
    image_path = resolve_file_path(gallery.photo_dir, filename)
    
    if image_path:
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


@app.route('/api/file_count')
def api_file_count():
    """Get current file count for change detection"""
    total_files = len(gallery.get_file_index())
    return jsonify({'count': total_files})


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


@app.route('/api/upload', methods=['POST'])
def api_upload():
    """Handle photo uploads via drag-and-drop"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        uploaded = []
        
        for file in files:
            if file.filename == '':
                continue
            
            # Check if allowed extension
            ext = os.path.splitext(file.filename)[1].lower().lstrip('.')
            if ext not in config['gallery']['allowed_extensions']:
                continue
            
            # Save to photos directory
            filename = secure_filename(file.filename)
            filepath = os.path.join(config['gallery']['photo_directory'], filename)
            file.save(filepath)
            uploaded.append(filename)
        
        return jsonify({'status': 'ok', 'uploaded': uploaded, 'count': len(uploaded)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500



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
    """
    Background worker for manual tagging using subprocess approach.
    
    Spawns ONE tag_worker.py subprocess for ALL untagged images.
    Worker handles batching internally, then exits to release GPU memory.
    
    This is more efficient than spawning per-batch (avoids reloading model).
    """
    import tempfile
    import subprocess
    
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
        
        # Prepare ALL image paths
        total = len(untagged)
        image_paths = [os.path.normpath(os.path.join(gallery.photo_dir, f)) for f in untagged]
        
        # Prepare model configuration
        model_config = {
            'model': config['ai'].get('model', 'llava-hf/llava-1.5-7b-hf'),
            'use_quantization': config['ai'].get('use_quantization', True),
            'batch_size': config['ai'].get('batch_size', 15),
            'tagging_prompt': config['ai'].get('tagging_prompt'),
            'cache_dir': os.path.join(ROOT_DIR, 'models')
        }
        
        # Create temporary files for worker communication
        config_fd, config_file = tempfile.mkstemp(suffix='.json', text=True)
        output_fd, output_file = tempfile.mkstemp(suffix='.json', text=True)
        progress_fd, progress_file = tempfile.mkstemp(suffix='.json', text=True)  # NEW: progress file
        os.close(progress_fd)  # Worker will write to this
        
        try:
            # Write worker configuration with ALL images
            worker_config = {
                'image_paths': image_paths,
                'output_file': output_file,
                'model_config': model_config,
                'progress_file': progress_file,  # Pass progress file to worker
                'total_images': total  # So worker can report progress
            }
            
            with os.fdopen(config_fd, 'w') as f:
                json.dump(worker_config, f)
            
            os.close(output_fd)  # Close FD, worker will write to file
            
            # Spawn worker process - it will handle ALL batches internally
            worker_script = os.path.join(ROOT_DIR, 'app', 'tag_worker.py')
            
            with tagging_lock:
                tagging_state['status'] = f'Starting worker subprocess for {total} images...'
            
            # Force UTF-8 encoding for subprocess to avoid Windows cp1252 issues
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            print(f"[SERVER] Spawning worker for {total} images...")
            
            # Start subprocess - worker will process all batches
            process = subprocess.Popen(
                [sys.executable, worker_script, config_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            
            # Poll subprocess and update progress by reading progress file
            import time
            while process.poll() is None:
                # Check for cancellation
                with tagging_lock:
                    if tagging_state['cancel_requested']:
                        process.terminate()
                        process.wait(timeout=5)
                        tagging_state['running'] = False
                        tagging_state['status'] = 'Cancelled by user'
                        return
                
                # Read progress from worker's progress file
                try:
                    with open(progress_file, 'r') as f:
                        progress_data = json.load(f)
                        with tagging_lock:
                            tagging_state['current'] = progress_data.get('current', 0)
                            tagging_state['status'] = progress_data.get('status', 'Processing...')
                except:
                    # Progress file may not exist yet or be incomplete
                    pass
                
                time.sleep(1)  # Poll every second
            
            # Process completed - get output
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                error_msg = f"Worker failed (exit {process.returncode})"
                if stderr:
                    error_msg += f"\nStderr: {stderr}"
                if stdout:
                    error_msg += f"\nStdout: {stdout}"
                raise Exception(error_msg)
            
            # Read results from worker
            with open(output_file, 'r') as f:
                results = json.load(f)
            
            # Save tags to database
            db.save_tags_batch(results)
            
            # Update progress
            with tagging_lock:
                tagging_state['current'] = total
            
            print(f"[SERVER] Worker complete - processed {len(results)} images, GPU memory released")
            
        except subprocess.TimeoutExpired:
            with tagging_lock:
                tagging_state['error'] = 'Worker timeout'
                tagging_state['running'] = False
            return
        except Exception as e:
            with tagging_lock:
                tagging_state['error'] = str(e)
                tagging_state['running'] = False
            return
        finally:
            # Cleanup temporary files
            try:
                os.unlink(config_file)
            except:
                pass
            try:
                os.unlink(output_file)
            except:
                pass
            try:
                os.unlink(progress_file)  # Clean up progress file too
            except:
                pass
        
        # Complete
        with tagging_lock:
            if not tagging_state['cancel_requested']:
                tagging_state['running'] = False
                tagging_state['status'] = f'Tagged {total} images - GPU memory released'
                tagging_state['current'] = total
    
    except Exception as e:
        with tagging_lock:
            tagging_state['running'] = False
            tagging_state['error'] = str(e)
            tagging_state['status'] = 'Error occurred'


# --- RUN SERVER ---

<<<<<<< HEAD
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
            PHOTO_DIR,
            db,
            thumbs,
            config['gallery']['allowed_extensions']
        )
        if watcher:
            print("👁️  File monitoring: enabled")
    
    # Check auto-tag setting (disabled by default for better UX)
    # Users can trigger tagging manually from UI
    if config['ai'].get('auto_tag', False):
        print("🤖 Auto-tagging: disabled (use UI button to start tagging)")
=======
>>>>>>> 330560c153dd5ff82c23722a9c86631682502cda
    else:
        print("🤖 Auto-tagging: disabled")
    
    print("\nPress Ctrl+C to stop\n")
    print("="*60 + "\n")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_server(debug=False)
