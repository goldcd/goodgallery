"""
GoodGallery Flask Server
Main web application
"""

import os
import yaml
from flask import Flask, render_template, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

from .database import Database
from .gallery import Gallery
from .thumbnails import ThumbnailGenerator
from .ai_tagger import AITagger


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
    original_path = os.path.join(gallery.photo_dir, filename)
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
    image_paths = [os.path.join(gallery.photo_dir, f) for f in filenames]
    
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


# --- RUN SERVER ---

def run_server(host='127.0.0.1', port=None, debug=False):
    """Start Flask server"""
    if port is None:
        port = config['gallery']['port']
    
    print(f"\n🚀 GoodGallery running at http://{host}:{port}")
    print(f"📁 Photo directory: {config['gallery']['photo_directory']}")
    print(f"🏷️  Tagged images: {db.get_stats()['tagged']}")
    print("\nPress Ctrl+C to stop\n")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_server(debug=True)
