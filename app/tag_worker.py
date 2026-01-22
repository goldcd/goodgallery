"""
GoodGallery Tag Worker
Subprocess for GPU-intensive LLaVA tagging

Runs as: python -m app.tag_worker <config_json>

This script runs as a separate process, loads the LLaVA model,
processes a batch of images, and exits. When the process terminates,
the OS forcibly releases ALL GPU memory, ensuring no memory leaks.
"""

import os
import sys
import json
import argparse

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.ai_tagger import AITagger

def main():
    parser = argparse.ArgumentParser(description='Tag images using LLaVA in subprocess')
    parser.add_argument('config_file', help='JSON config file path')
    args = parser.parse_args()
    
    # Load configuration
    with open(args.config_file, 'r') as f:
        config = json.load(f)
    
    all_image_paths = config['image_paths']
    output_file = config['output_file']
    model_config = config['model_config']
    batch_size = model_config.get('batch_size', 15)
    progress_file = config.get('progress_file')  # NEW: progress file for status updates
    
    total_images = len(all_image_paths)
    print(f"[WORKER] Started - processing {total_images} images in batches of {batch_size}")
    
    # Helper to write progress
    def update_progress(current, status):
        if progress_file:
            try:
                with open(progress_file, 'w') as f:
                    json.dump({'current': current, 'total': total_images, 'status': status}, f)
            except:
                pass  # Ignore write errors
    
    # Initialize tagger
    tagger = AITagger(
        model_id=model_config.get('model', 'llava-hf/llava-1.5-7b-hf'),
        use_quantization=model_config.get('use_quantization', True),
        batch_size=batch_size,
        tagging_prompt=model_config.get('tagging_prompt'),
        cache_dir=model_config.get('cache_dir')
    )
    
    # Load model ONCE (GPU memory allocated here)
    update_progress(0, 'Loading AI model...')
    tagger.load_model()
    
    # Process ALL images in batches
    all_results = []
    
    # Open output file in append mode for streaming results
    # We use a simple JSONL-like format (one JSON object per line) or just append to a list if needed
    # But since the server expects a specific format, we'll write incremental updates
    
    # Actually, for the incremental approach agreed in the plan:
    # We will treat the output file as a JSONL stream of batches
    
    for i in range(0, total_images, batch_size):
        batch_paths = all_image_paths[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total_images + batch_size - 1) // batch_size
        
        update_progress(i, f'Processing batch {batch_num}/{total_batches}...')
        print(f"[WORKER] Processing batch {batch_num}/{total_batches} ({len(batch_paths)} images)...")
        # Flush stdout to ensure it hits the log file immediately
        sys.stdout.flush()
        
        results = tagger.tag_batch(batch_paths)
        all_results.extend(results)
        
        # Write this batch's results immediately
        try:
            with open(output_file, 'a', encoding='utf-8') as f:
                # Write as a JSON line per batch
                f.write(json.dumps(results) + '\n')
        except Exception as e:
            print(f"[WORKER] Error writing batch results: {e}")
            sys.stdout.flush()
        
        processed = min(i + batch_size, total_images)
        update_progress(processed, f'Batch {batch_num}/{total_batches} complete')
        print(f"[WORKER] Progress: {processed}/{total_images} images tagged")
        sys.stdout.flush()
    
    # Final progress update
    update_progress(total_images, 'Complete')
    
    print(f"[WORKER] Complete - tagged {len(all_results)} images")
    print(f"[WORKER] Results streamed to: {output_file}")
    sys.stdout.flush()
    
    # Exit cleanly - OS will release ALL GPU memory
    sys.exit(0)

if __name__ == '__main__':
    main()
