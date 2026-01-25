"""
GoodGallery Analysis Worker
Background process for generating Tag Cloud embeddings and clusters.

Runs as: python -m app.analysis_worker <config_json>
"""

import os
import sys
import json
import argparse
import sqlite3
import numpy as np

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import ML libraries inside worker to avoid server overhead
try:
    from sentence_transformers import SentenceTransformer
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    from sklearn.cluster import KMeans
except ImportError as e:
    print(f"[WORKER] Critical Import Error: {e}")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Analyze tags')
    parser.add_argument('config_file', help='JSON config file path')
    args = parser.parse_args()
    
    # Load configuration
    with open(args.config_file, 'r') as f:
        config = json.load(f)
        
    db_path = config['db_path']
    output_path = config['output_path']
    progress_file = config.get('progress_file')
    project_root_dir = config.get('project_root', project_root)
    
    # Helper to write progress
    def update_progress(current, total, status):
        print(f"[WORKER] {status}")
        sys.stdout.flush()
        if progress_file:
            try:
                with open(progress_file, 'w') as f:
                    json.dump({'current': current, 'total': total, 'status': status}, f)
            except:
                pass

    try:
        # 1. Fetch Tags
        update_progress(0, 100, "Fetching tags from database...")
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT tags FROM image_tags WHERE tags IS NOT NULL")
        
        tag_counts = {}
        for row in cursor:
            if row[0]:
                tags = [t.strip().lower() for t in row[0].split(',')]
                for tag in tags:
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        conn.close()
        
        unique_tags = sorted(list(tag_counts.keys()))
        total_unique = len(unique_tags)
        
        if total_unique < 5:
            raise Exception("Not enough tags to analyze (need at least 5)")
            
        update_progress(10, 100, f"Found {total_unique} unique tags. Loading model...")
        
        # 2. Load Model
        # Using a high quality but efficient model
        model_name = 'BAAI/bge-small-en-v1.5' 
        # Note: used 'small' for speed/size balance (33MB), 'large' is 1.3GB. 
        # User has 16GB VRAM, but for <10k tags, 'small' is sufficient and download is faster.
        # If user explicitly requested uncensored/large, maybe 'BAAI/bge-large-en-v1.5'.
        # Let's start with 'all-MiniLM-L6-v2' (classic) or 'BAAI/bge-base-en-v1.5'.
        # Given user said "size isn't really a concern", let's use 'BAAI/bge-large-en-v1.5'.
        
        model_name = 'BAAI/bge-large-en-v1.5'
        cache_dir = os.path.join(project_root_dir, 'models', 'embeddings')
        
        model = SentenceTransformer(model_name, cache_folder=cache_dir)
        
        # 3. Embed Tags
        update_progress(30, 100, f"Generating embeddings for {total_unique} tags...")
        embeddings = model.encode(unique_tags, show_progress_bar=True, batch_size=32)
        
        # 4. Dimensionality Reduction (384/1024 -> 2)
        update_progress(60, 100, "Projecting to 2D space (t-SNE)...")
        
        # Use PCA first to 50 dims if count is high (standard t-SNE practice)
        if total_unique > 50:
            pca = PCA(n_components=min(50, total_unique))
            pca_result = pca.fit_transform(embeddings)
        else:
            pca_result = embeddings
            
        # Perplexity must be less than number of samples
        perplexity = min(30, total_unique - 1)
        tsne = TSNE(n_components=2, perplexity=perplexity, random_state=42, init='pca', learning_rate='auto')
        coords = tsne.fit_transform(pca_result)
        
        # 5. Clustering (K-Means)
        update_progress(80, 100, "Identifying topic clusters...")
        # Heuristic for K: sqrt(N/2) usually works okay for topic modeling
        n_clusters = max(3, int(np.sqrt(total_unique / 2)))
        n_clusters = min(n_clusters, 20) # Cap at 20 clusters
        
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(embeddings)
        
        # 6. Format Output
        update_progress(95, 100, "Saving analysis results...")
        
        nodes = []
        for i, tag in enumerate(unique_tags):
            nodes.append({
                'id': tag,
                'x': float(coords[i][0]),
                'y': float(coords[i][1]),
                'cluster': int(clusters[i]),
                'count': tag_counts[tag]
            })
            
        # Calculate cluster centroids/labels (most frequent tag in cluster)
        cluster_info = {}
        for i in range(n_clusters):
            cluster_indices = [idx for idx, c in enumerate(clusters) if c == i]
            if not cluster_indices:
                continue
            # Find closest to centroid? Or just most frequent?
            # Most frequent is easier to explain
            cluster_tags = [unique_tags[idx] for idx in cluster_indices]
            top_tag = max(cluster_tags, key=lambda t: tag_counts[t])
            cluster_info[i] = {'label': top_tag, 'count': len(cluster_tags)}
            
        output_data = {
            'metadata': {
                'total_tags': total_unique,
                'model': model_name,
                'generated_at': "now" 
            },
            'nodes': nodes,
            'clusters': cluster_info
        }
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f)
            
        update_progress(100, 100, "Analysis complete")
        
    except Exception as e:
        print(f"[WORKER] Error: {e}")
        import traceback
        traceback.print_exc()
        update_progress(0, 0, f"Error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
