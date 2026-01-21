"""
Good Gallery AI Tagger
LLaVA-based image tagging using HuggingFace Transformers
Ported STRICTLY from tagger_client_v2.py
"""

import os
import re
import concurrent.futures
from typing import List, Dict, Optional
from PIL import Image
import torch
from transformers import AutoProcessor, LlavaForConditionalGeneration, BitsAndBytesConfig


class AITagger:
    def __init__(self, model_id: str = "llava-hf/llava-1.5-7b-hf", use_quantization: bool = True, batch_size: int = 15, tagging_prompt: str = None):
        self.model_id = model_id
        self.use_quantization = use_quantization
        self.batch_size = batch_size
        # Default comprehensive prompt if not provided
        default_prompt = (
            "USER: <image>\n"
            "Analyze the image and generate a single, comprehensive, comma-separated list of keywords, "
            "listed in their descending importance as a description of the image\n"
            "Include keywords for: main objects, people (including names of famous figures if recognized), "
            "actions, location, time of day, lighting, artistic style, mood, fictional characters, memes, "
            "distinctive features and anything else that seems to be a relevant keyword to search on this image by.\n"
            "Do not transcribe text. Do not use categories or labels. Just keywords.\n"
            "Example: car, woman, running, beach, sunny, sketch, vintage, afternoon\n"
            "ASSISTANT:"
        )
        self.tagging_prompt = tagging_prompt or default_prompt
        self.model = None
        self.processor = None
        self.is_loaded = False
    
    def load_model(self):
        """
        Load LLaVA model into memory
        Matches 'get_model' in tagger_client_v2.py
        """
        if self.is_loaded:
            return
        
        print("Loading LLaVA model (this may take a while)...")
        print(f"  Using tagging prompt: {self.tagging_prompt[:80]}..." if len(self.tagging_prompt) > 80 else f"  Using tagging prompt: {self.tagging_prompt}")
        
        try:
            # Quantization config for 4-bit loading (fits in ~6GB VRAM)
            # Reference: tagger_client_v2.py:30-33
            if self.use_quantization:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16
                )
            else:
                quantization_config = None
            
            # Load Processor
            # Reference: tagger_client_v2.py:38
            self.processor = AutoProcessor.from_pretrained(self.model_id, use_fast=True)
            
            # Load Model
            # Reference: tagger_client_v2.py:39-43
            if self.use_quantization:
                self.model = LlavaForConditionalGeneration.from_pretrained(
                    self.model_id,
                    quantization_config=quantization_config,
                    device_map="auto" 
                )
            else:
                self.model = LlavaForConditionalGeneration.from_pretrained(
                    self.model_id,
                    device_map="auto",
                    torch_dtype=torch.float16
                )
            
            print("✓ Model loaded successfully!")
            self.is_loaded = True
            
            # Optional: Log memory just for confirmation (not in reference, but harmless)
            try:
                footprint = self.model.get_memory_footprint() / 1024**3
                print(f"  Memory footprint: {footprint:.2f} GB")
            except:
                pass
            
        except Exception as e:
            print(f"Error loading model: {e}")
            print("Ensure you have installed: torch transformers accelerate bitsandbytes")
            raise

    def _load_image_worker(self, path: str):
        """Reference: tagger_client_v2.py:79-84"""
        try:
            return Image.open(path).convert("RGB"), path
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None, path
    
    def tag_batch(self, image_paths: List[str]) -> List[Dict[str, any]]:
        """
        Process batch - Matches 'process_batch' in tagger_client_v2.py
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded")
        
        if not image_paths:
            return []
        
        results = []
        valid_images = []
        valid_paths = []
        
        try:
            # 1. Load images
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.batch_size) as executor:
                loaded_data = list(executor.map(self._load_image_worker, image_paths))
            
            for img, path in loaded_data:
                if img:
                    valid_images.append(img)
                    valid_paths.append(path)
                else:
                    results.append({"filename": os.path.basename(path), "tags": ["error_loading"]})
            
            if not valid_images:
                return results
            
            # 2. Prompts - use configured prompt
            prompts = [self.tagging_prompt] * len(valid_images)
            
            # 3. Tokenize
            # Reference: tagger_client_v2.py:123
            inputs = self.processor(
                text=prompts,
                images=valid_images,
                return_tensors="pt",
                padding=True
            ).to("cuda") # Reference used to("cuda"), explicit here
            
            # 4. Generate
            # Reference: tagger_client_v2.py:126-132
            generate_ids = self.model.generate(
                **inputs,
                max_new_tokens=60,
                do_sample=True,
                temperature=0.6,
                top_p=0.9
            )
            
            # 5. Decode
            # Reference: tagger_client_v2.py:135
            outputs = self.processor.batch_decode(
                generate_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )
            
            # 6. Parse
            # Reference: tagger_client_v2.py:138-201
            for i, output in enumerate(outputs):
                original_path = valid_paths[i]
                filename = os.path.basename(original_path)
                
                if "ASSISTANT:" in output:
                    response = output.split("ASSISTANT:")[-1].strip()
                else:
                    response = output.strip()
                
                # Cleanup Logic
                tags = self._clean_tags(response)
                
                # Truncate Logic
                tags = self._truncate_tags(tags)
                
                print(f"  [{filename}] -> {tags[:5] + ['...'] if len(tags) > 5 else tags}")
                
                results.append({"filename": filename, "tags": tags})
                
        except Exception as e:
            print(f"Batch Processing Error: {e}")
            for path in valid_paths:
                if not any(r['filename'] == os.path.basename(path) for r in results):
                    results.append({"filename": os.path.basename(path), "tags": []})
        
        return results

    def _clean_tags(self, response: str) -> List[str]:
        """Reference: tagger_client_v2.py:147-183"""
        response = response.replace('\n', ',')
        
        remove_patterns = [
            r'main objects\s*(&\s*people)?\s*:', 
            r'actions\s*(&\s*activities)?\s*:', 
            r'exact location\s*(&\s*landmarks)?\s*:', 
            r'time\s*(of day)?\s*(&\s*lighting)?\s*:',
            r'art style\s*(&\s*mood)?\s*:',
            r'distinctive features\s*:',
            r'\d+\.\s*', 
            r'-\s*'
        ]
        
        clean_response = response
        for pat in remove_patterns:
            clean_response = re.sub(pat, '', clean_response, flags=re.IGNORECASE)
            
        raw_tags = [tag.strip() for tag in clean_response.split(',')]
        seen = set()
        tags = []
        
        for tag in raw_tags:
            tag_lower = tag.lower().strip()
            if ':' in tag_lower: continue
            
            if tag_lower and tag_lower not in seen and len(tag_lower) > 1:
                seen.add(tag_lower)
                tags.append(tag_lower)
        
        return tags

    def _truncate_tags(self, tags: List[str], max_length: int = 255) -> List[str]:
        """Reference: tagger_client_v2.py:191-201"""
        final_str = ",".join(tags)
        if len(final_str) <= max_length:
            return tags
            
        cut_str = final_str[:max_length]
        if "," in cut_str:
            cut_str = cut_str.rsplit(',', 1)[0]
        return cut_str.split(',')

    def unload_model(self):
        if self.model is not None:
            del self.model
            del self.processor
            self.model = None
            self.processor = None
            self.is_loaded = False
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("🧹 Model unloaded")
