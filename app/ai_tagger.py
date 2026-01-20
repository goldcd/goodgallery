"""
Good Gallery AI Tagger
LLaVA-based image tagging using HuggingFace Transformers
Ported from tagger_client_v2.py
"""

import os
import re
import concurrent.futures
from typing import List, Dict, Optional
from PIL import Image
import torch
from transformers import AutoProcessor, LlavaForConditionalGeneration, BitsAndBytesConfig


class AITagger:
    def __init__(self, model_id: str = "llava-hf/llava-1.5-7b-hf", use_quantization: bool = True, batch_size: int = 15):
        """
        Args:
            model_id: HuggingFace model identifier
            use_quantization: Use 4-bit quantization (saves VRAM)
            batch_size: Number of images to process per GPU batch
        """
        self.model_id = model_id
        self.use_quantization = use_quantization
        self.batch_size = batch_size
        self.model = None
        self.processor = None
        self.is_loaded = False
    
    def load_model(self):
        """
        Load LLaVA model into memory
        
        Ported from tagger_client_v2.py:26-49
        """
        if self.is_loaded:
            return
        
        print("Loading LLaVA model (this may take a while)...")
        
        try:
            # Quantization config for 4-bit loading (fits in ~6GB VRAM)
            if self.use_quantization:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16
                )
            else:
                quantization_config = None
            
            # Load processor
            self.processor = AutoProcessor.from_pretrained(self.model_id, use_fast=True)
            
            # Load model
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
            
            self.is_loaded = True
            print("✓ Model loaded successfully!")
            
        except Exception as e:
            print(f"✗ Error loading model: {e}")
            print("Ensure you have installed: torch transformers accelerate bitsandbytes")
            raise
    
    def _load_image_worker(self, path: str):
        """
        Load image in worker thread
        
        Ported from tagger_client_v2.py:79-84
        """
        try:
            return Image.open(path).convert("RGB"), path
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None, path
    
    def tag_batch(self, image_paths: List[str]) -> List[Dict[str, any]]:
        """
        Process a batch of images and generate tags
        
        Ported from tagger_client_v2.py:86-210
        
        Returns: [{"filename": "...", "tags": ["tag1", "tag2", ...]}, ...]
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        if not image_paths:
            return []
        
        results = []
        valid_images = []
        valid_paths = []
        
        try:
            # 1. Load all images in parallel (speeds up network drive reads)
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.batch_size) as executor:
                loaded_data = list(executor.map(self._load_image_worker, image_paths))
            
            for img, path in loaded_data:
                if img:
                    valid_images.append(img)
                    valid_paths.append(path)
                else:
                    # Failed to load - tag with error
                    results.append({
                        "filename": os.path.basename(path),
                        "tags": ["error_loading"]
                    })
            
            if not valid_images:
                return results
            
            # 2. Prepare prompts (one per image)
            # Detailed prompt from tagger_client_v2.py:111-118
            prompt = (
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
            prompts = [prompt] * len(valid_images)
            
            # 3. Batch tokenize/process
            inputs = self.processor(
                text=prompts,
                images=valid_images,
                return_tensors="pt",
                padding=True
            ).to(self.model.device)
            
            # 4. Generate
            generate_ids = self.model.generate(
                **inputs,
                max_new_tokens=60,
                do_sample=True,
                temperature=0.6,
                top_p=0.9
            )
            
            # 5. Decode
            outputs = self.processor.batch_decode(
                generate_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )
            
            # 6. Parse and clean results (lines 138-201)
            for i, output in enumerate(outputs):
                original_path = valid_paths[i]
                filename = os.path.basename(original_path)
                
                # Extract response after ASSISTANT:
                if "ASSISTANT:" in output:
                    response = output.split("ASSISTANT:")[-1].strip()
                else:
                    response = output.strip()
                
                # Clean response
                tags = self._clean_tags(response)
                
                # Truncate to 255 chars if needed (database limit)
                tags = self._truncate_tags(tags)
                
                print(f"  [{filename}] → {tags[:5] + ['...'] if len(tags) > 5 else tags}")
                
                results.append({
                    "filename": filename,
                    "tags": tags
                })
        
        except Exception as e:
            print(f"Batch processing error: {e}")
            # Return empty tags for failed images
            for path in valid_paths:
                if not any(r['filename'] == os.path.basename(path) for r in results):
                    results.append({
                        "filename": os.path.basename(path),
                        "tags": []
                    })
        
        return results
    
    def _clean_tags(self, response: str) -> List[str]:
        """
        Clean and deduplicate tags from model response
        
        Ported from tagger_client_v2.py:147-183
        """
        # 1. Replace newlines with commas
        response = response.replace('\n', ',')
        
        # 2. Remove category headers (aggressive cleaning)
        remove_patterns = [
            r'main objects\s*(&\s*people)?\s*:',
            r'actions\s*(&\s*activities)?\s*:',
            r'exact location\s*(&\s*landmarks)?\s*:',
            r'time\s*(of day)?\s*(&\s*lighting)?\s*:',
            r'art style\s*(&\s*mood)?\s*:',
            r'distinctive features\s*:',
            r'\d+\.\s*',  # "1. "
            r'-\s*'       # "- "
        ]
        
        clean_response = response
        for pattern in remove_patterns:
            clean_response = re.sub(pattern, '', clean_response, flags=re.IGNORECASE)
        
        # 3. Split by comma and deduplicate
        raw_tags = [tag.strip() for tag in clean_response.split(',')]
        seen = set()
        tags = []
        
        for tag in raw_tags:
            tag_lower = tag.lower().strip()
            
            # Skip if contains colon (likely a label we missed)
            if ':' in tag_lower:
                continue
            
            # Deduplicate and filter short tags
            if tag_lower and tag_lower not in seen and len(tag_lower) > 1:
                seen.add(tag_lower)
                tags.append(tag_lower)
        
        return tags
    
    def _truncate_tags(self, tags: List[str], max_length: int = 255) -> List[str]:
        """
        Truncate tag list to fit within character limit
        
        Ported from tagger_client_v2.py:189-201
        """
        final_str = ",".join(tags)
        
        if len(final_str) <= max_length:
            return tags
        
        # Cut to max_length
        cut_str = final_str[:max_length]
        
        # Trim to last comma to avoid partial words
        if "," in cut_str:
            cut_str = cut_str.rsplit(',', 1)[0]
        
        # Re-split to list
        return cut_str.split(',')
    
    def unload_model(self):
        """Free up GPU memory"""
        if self.model is not None:
            del self.model
            del self.processor
            self.model = None
            self.processor = None
            self.is_loaded = False
            
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            print("🧹 Model unloaded from memory")
    
    def get_memory_usage(self):
        """Get current GPU memory usage"""
        if not torch.cuda.is_available():
            return None
        
        return {
            'allocated_gb': round(torch.cuda.memory_allocated() / 1e9, 2),
            'reserved_gb': round(torch.cuda.memory_reserved() / 1e9, 2),
            'device_name': torch.cuda.get_device_name(0),
            'device_count': torch.cuda.device_count()
        }
