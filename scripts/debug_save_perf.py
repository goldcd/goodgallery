
import sys
import os
import time
import random
import string

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Database

# Create temp db
DB_PATH = 'data/test_perf.db'
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

db = Database(DB_PATH)

def generate_data(count):
    data = []
    for i in range(count):
        data.append({
            'filename': f'image_{i}.jpg',
            'tags': ', '.join([''.join(random.choices(string.ascii_lowercase, k=5)) for _ in range(5)])
        })
    return data

def benchmark(count):
    print(f"Generating {count} items...")
    items = generate_data(count)
    
    print(f"Saving {count} items using save_tags_batch...")
    start = time.time()
    db.save_tags_batch(items)
    end = time.time()
    
    print(f"Time taken: {end - start:.2f} seconds")
    print(f"Rate: {count / (end - start):.2f} items/sec")

if __name__ == '__main__':
    benchmark(1000)
    benchmark(10000)
    # benchmark(50000) # Uncomment for larger test
