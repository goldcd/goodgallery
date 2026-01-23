import sys
import os
import json
import traceback
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Database
from app.ai_tagger import AITagger
from app.tag_consolidator import TagConsolidator

class SimpleTextTagger:
    """
    A lightweight wrapper for Text-only LLMs (like Qwen2.5-Instruct)
    Designed to mimic the interface required by TagConsolidator 
    but strictly for text processing.
    """
    def __init__(self, model_id, cache_dir=None):
        self.model_id = model_id
        self.cache_dir = cache_dir
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        
    def load_model(self):
        print(f"Loading Text Model ({self.model_id}) on {self.device}...")
        try:
            quantization_config = None
            if self.device == "cuda":
                try:
                    from transformers import BitsAndBytesConfig
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True
                    )
                    print("  Using 4-bit quantization (BitsAndBytes)")
                except ImportError:
                    print("  Warning: bitsandbytes not installed, falling back to float16")

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_id, 
                cache_dir=self.cache_dir,
                trust_remote_code=True
            )
            
            # Load model
            if quantization_config:
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_id,
                    quantization_config=quantization_config,
                    device_map="auto",
                    cache_dir=self.cache_dir,
                    trust_remote_code=True
                )
            else:
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_id,
                    torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                    device_map=self.device,
                    cache_dir=self.cache_dir,
                    trust_remote_code=True
                )
            print("Text Model loaded successfully.")
        except Exception as e:
            print(f"Error loading text model: {e}")
            raise

    def generate_text_response(self, dummy_image, prompt):
        """
        Generate response from text prompt. 
        Ignores dummy_image (kept for API compatibility).
        Uses streaming to show progress in logs.
        """
        from transformers import TextIteratorStreamer
        from threading import Thread

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
        
        # Apply chat template
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)
        
        # Initialize streamer
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        
        # Generation arguments
        generation_kwargs = dict(
            input_ids=model_inputs.input_ids,
            streamer=streamer,
            max_new_tokens=24000, # Increased to support large batch outputs
            do_sample=False,
            temperature=0.1
        )
        
        # Run generation in a separate thread so we can consume the streamer
        thread = Thread(target=self.model.generate, kwargs=generation_kwargs)
        thread.start()
        
        generated_text = ""
        print("AI Output: ", end="", flush=True)
        
        for new_text in streamer:
            print(new_text, end="", flush=True)
            generated_text += new_text
            
        print("\n") # Newline after done
        return generated_text

def run_worker(config_path):
    try:
        # Load config
        with open(config_path, 'r') as f:
            config = json.load(f)
            
        db_path = config['db_path']
        # Use consolidation_model if available, else fallback but warn
        model_id = config.get('consolidation_model', config.get('model_id', 'Qwen/Qwen2.5-1.5B-Instruct'))
        cache_dir = config['cache_dir']
        progress_file = config['progress_file']
        batch_size = config.get('consolidation_batch_size', 1000)
        prompt_template = config.get('consolidation_prompt', None)
        
        # Initialize
        db = Database(db_path)
        
        # Decide which tagger to use based on model name
        is_vlm = "vl" in model_id.lower() or "llava" in model_id.lower()
        
        if is_vlm:
            print(f"Detected VLM config ({model_id}). Using AITagger...")
            tagger = AITagger(
                model_id=model_id,
                use_quantization=config.get('use_quantization', True),
                cache_dir=cache_dir
            )
        else:
            print(f"Detected Text-Only config ({model_id}). Using SimpleTextTagger...")
            tagger = SimpleTextTagger(
                model_id=model_id,
                cache_dir=cache_dir
            )
        
        # Update progress: Loading
        with open(progress_file, 'w') as f:
            json.dump({'status': f'Loading {model_id}...', 'current': 0}, f)
            
        tagger.load_model()
        
        consolidator = TagConsolidator(db, tagger)
        
        def progress_callback(current, total, status):
            try:
                with open(progress_file, 'w') as f:
                    json.dump({
                        'status': status,
                        'current': current,
                        'total': total
                    }, f)
            except:
                pass

        # Run generation with configured batch size
        count = consolidator.generate_proposals(
            progress_callback=progress_callback,
            batch_size=batch_size,
            prompt_template=prompt_template
        )
        
        # Done
        with open(progress_file, 'w') as f:
            json.dump({'status': f'Completed. Generated {count} proposals.', 'current': count, 'done': True}, f)
            
    except Exception as e:
        traceback.print_exc()
        try:
            with open(progress_file, 'w') as f:
                json.dump({'error': str(e), 'status': 'Error'}, f)
        except:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: consolidation_worker.py <config_file>")
        sys.exit(1)
        
    run_worker(sys.argv[1])
