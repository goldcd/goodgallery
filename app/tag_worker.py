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
    
    total_images = len(all_image_paths)
    print(f"[WORKER] Started - processing {total_images} images in batches of {batch_size}")
    
    # Initialize tagger
    tagger = AITagger(
        model_id=model_config.get('model', 'llava-hf/llava-1.5-7b-hf'),
        use_quantization=model_config.get('use_quantization', True),
        batch_size=batch_size,
        tagging_prompt=model_config.get('tagging_prompt'),
        cache_dir=model_config.get('cache_dir')
    )
    
    # Load model ONCE (GPU memory allocated here)
    tagger.load_model()
    
    # Process ALL images in batches
    all_results = []
    for i in range(0, total_images, batch_size):
        batch_paths = all_image_paths[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total_images + batch_size - 1) // batch_size
        
        print(f"[WORKER] Processing batch {batch_num}/{total_batches} ({len(batch_paths)} images)...")
        
        results = tagger.tag_batch(batch_paths)
        all_results.extend(results)
        
        processed = min(i + batch_size, total_images)
        print(f"[WORKER] Progress: {processed}/{total_images} images tagged")
    
    # Save ALL results
    with open(output_file, 'w') as f:
        json.dump(all_results, f)
    
    print(f"[WORKER] Complete - tagged {len(all_results)} images")
    print(f"[WORKER] Results written to: {output_file}")
    
    # Exit cleanly - OS will release ALL GPU memory
    sys.exit(0)

if __name__ == '__main__':
    main()
