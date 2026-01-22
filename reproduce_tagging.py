import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import yaml
from app.ai_tagger import AITagger

def test_tagging():
    # Load config
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    prompt = config['ai']['tagging_prompt']
    model_id = config['ai']['model']
    
    print(f"Testing Prompt:\n{prompt}\n")
    
    # Initialize Tagger
    tagger = AITagger(
        model_id=model_id,
        use_quantization=True,
        tagging_prompt=prompt
    )
    
    tagger.load_model()
    
    # Test Image
    image_path = os.path.join('photos', 'badbrains_belushiguitaranimalhouse-ezgifcom-resize.gif')
    if not os.path.exists(image_path):
        # Fallback to another image if not found
        print(f"Image not found: {image_path}")
        # Try to find any image
        for root, dirs, files in os.walk('photos'):
            for file in files:
                if file.lower().endswith(('.jpg', '.png', '.jpeg')):
                    image_path = os.path.join(root, file)
                    break
            if image_path: break
    
    print(f"Tagging image: {image_path}")
    
    results = tagger.tag_batch([image_path])
    
    print("\nResults:")
    for result in results:
        print(f"Tags: {result['tags']}")

if __name__ == "__main__":
    test_tagging()
