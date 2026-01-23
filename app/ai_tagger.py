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
from transformers import AutoProcessor, LlavaForConditionalGeneration

# Global device detection
def get_device():
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    return "cpu"

class AITagger:
    def __init__(self, model_id: str = "llava-hf/llava-1.5-7b-hf", use_quantization: bool = True, batch_size: int = 1, tagging_prompt: str = None, cache_dir: str = None, max_image_size: int = 1024):
        self.model_id = model_id
        self.use_quantization = use_quantization
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        self.max_image_size = max_image_size
        self.device = get_device()
        
        # Disable quantization on non-CUDA devices (BitsAndBytes is CUDA-only)
        if self.device != "cuda" and self.use_quantization:
            print(f"[{self.device}] 4-bit quantization disabled (requires CUDA). Using float16 instead.")
            self.use_quantization = False
            
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
        Load AI model into memory (LLaVA or Qwen2-VL)
        """
        if self.is_loaded:
            return
        
        self.is_qwen = "qwen" in self.model_id.lower()
        print(f"Loading AI model ({self.model_id}) on {self.device.upper()}...")
        
        # Clean prompt for logging
        prompt_preview = self.tagging_prompt.replace('\n', ' ')[:80]
        print(f"  Using prompt: {prompt_preview}...")
        
        try:
            quantization_config = None
            
            # Windows/CUDA: Use BitsAndBytes if requested
            if self.device == "cuda" and self.use_quantization:
                try:
                    from transformers import BitsAndBytesConfig
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True
                    )
                except ImportError:
                    print("Warning: bitsandbytes not installed, falling back to float16")
            
            # 1. Load Processor
            print("  Loading processor...")
            self.processor = AutoProcessor.from_pretrained(
                self.model_id, 
                use_fast=True,
                cache_dir=self.cache_dir
            )
            
            # 2. Load Model
            print("  Loading model weights...")
            
            # Use AutoModelForVision2Seq for both LLaVA and Qwen2-VL
            # This handles class mapping automatically based on config.json
            from transformers import AutoModelForVision2Seq
            model_class = AutoModelForVision2Seq

            if quantization_config:
                try:
                    # 4-bit customized load (CUDA only)
                    print("  Attempting 4-bit quantization load...")
                    self.model = model_class.from_pretrained(
                        self.model_id,
                        quantization_config=quantization_config,
                        device_map="auto",
                        cache_dir=self.cache_dir,
                        trust_remote_code=True
                    )
                except Exception as e:
                    print(f"⚠️  Quantization load failed: {e}")
                    print("  Falling back to standard FP16 load (may use more VRAM)...")
                    self.model = model_class.from_pretrained(
                        self.model_id,
                        device_map=self.device, 
                        torch_dtype=torch.float16, 
                        cache_dir=self.cache_dir,
                        trust_remote_code=True
                    )
            else:
                # Standard load
                self.model = model_class.from_pretrained(
                    self.model_id,
                    device_map=self.device, 
                    torch_dtype=torch.float16, 
                    cache_dir=self.cache_dir,
                    trust_remote_code=True
                )
            
            # Qwen specific configuration
            if self.is_qwen:
                # Helper for Qwen vision inputs
                try:
                    from qwen_vl_utils import process_vision_info
                    self.process_vision_info = process_vision_info
                except ImportError:
                    print("❌ Error: qwen-vl-utils not installed. Qwen model requires it.")
                    print("   pip install qwen-vl-utils")
                    raise
            
            print("[OK] Model loaded successfully!")
            self.is_loaded = True
            
        except Exception as e:
            print(f"Error loading model: {e}")
            raise

    def _load_image_worker(self, path: str):
        """Reference: tagger_client_v2.py:79-84"""
        try:
            img = Image.open(path).convert("RGB")
            
            # RESIZE LOGIC for Qwen Memory Safety
            # Qwen2-VL creates tokens based on resolution. 
            # Native 4K images = thousands of tokens = OOM.
            # 1024px is plenty for tagging and keeps VRAM < 8GB.
            max_dim = self.max_image_size
            if max_dim and max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                
            return img, path
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None, path
    
    def tag_batch(self, image_paths: List[str]) -> List[Dict[str, any]]:
        """
        Process batch of images
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
            
            # --- QWEN LOGIC ---
            if self.is_qwen:
                # Clean prompt: Remove "USER: <image>" artifacts if present, Qwen handles distinct roles
                clean_prompt = self.tagging_prompt
                clean_prompt = re.sub(r'USER:\s*<image>\s*', '', clean_prompt, flags=re.IGNORECASE).strip()
                if "ASSISTANT:" in clean_prompt:
                    clean_prompt = clean_prompt.split("ASSISTANT:")[0].strip()
                
                # Construct batch messages
                messages = []
                for img in valid_images:
                    messages.append([
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "image": img},
                                {"type": "text", "text": clean_prompt},
                            ],
                        }
                    ])
                
                # Prepare inputs
                texts = [
                    self.processor.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
                    for msg in messages
                ]
                
                image_inputs, video_inputs = self.process_vision_info(messages)
                
                # INFERENCE WITH NO GRADIENT TRACKING (Crucial for VRAM)
                with torch.no_grad():
                    inputs = self.processor(
                        text=texts,
                        images=image_inputs,
                        videos=video_inputs,
                        padding=True,
                        return_tensors="pt",
                    ).to(self.device)
                    
                    # Generate
                    generated_ids = self.model.generate(**inputs, max_new_tokens=128)
                    
                    # Trim inputs from outputs
                    generated_ids_trimmed = [
                        out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
                    ]
                    
                    outputs = self.processor.batch_decode(
                        generated_ids_trimmed, 
                        skip_special_tokens=True, 
                        clean_up_tokenization_spaces=False
                    )

                # Aggressive Cleanup
                del inputs, generated_ids, generated_ids_trimmed, image_inputs, video_inputs
                if self.device == "cuda":
                    torch.cuda.empty_cache()
            
            # --- LLaVA LOGIC (Legacy) ---
            else:
                # Ensure prompt has image token
                prompt = self.tagging_prompt
                if "<image>" not in prompt:
                    prompt = "USER: <image>\n" + prompt
                
                prompts = [prompt] * len(valid_images)
                
                inputs = self.processor(
                    text=prompts,
                    images=valid_images,
                    return_tensors="pt",
                    padding=True
                ).to(self.device)
                
                generate_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=60,
                    do_sample=True,
                    temperature=0.6,
                    top_p=0.9
                )
                
                outputs = self.processor.batch_decode(
                    generate_ids,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False
                )

            # 6. Parse Results
            for i, output in enumerate(outputs):
                original_path = valid_paths[i]
                filename = os.path.basename(original_path)
                
                # LLaVA output often includes input prompt, Qwen usually doesn't (due to trim above)
                response = output
                if "ASSISTANT:" in response:
                    response = response.split("ASSISTANT:")[-1].strip()
                
                print(f"[DEBUG] Raw response for {filename}: {repr(response)}")
                
                # Cleanup Logic
                tags = self._clean_tags(response)
                print(f"[DEBUG] Cleaned tags for {filename}: {tags}")
                
                tags = self._truncate_tags(tags)
                
                results.append({"filename": filename, "tags": tags})
                
        except Exception as e:
            print(f"Batch Processing Error: {e}")
            import traceback
            traceback.print_exc()
            for path in valid_paths:
                if not any(r['filename'] == os.path.basename(path) for r in results):
                    results.append({"filename": os.path.basename(path), "tags": []})
        
        return results

    def _clean_tags(self, response: str) -> List[str]:
        """Reference: tagger_client_v2.py:147-183"""
        # Replace newlines with commas to handle list formats
        response = response.replace('\n', ',')
        
        # Remove common chatty prefixes/headers
        remove_patterns = [
            r'main objects\s*(&\s*people)?\s*:', 
            r'actions\s*(&\s*activities)?\s*:', 
            r'exact location\s*(&\s*landmarks)?\s*:', 
            r'time\s*(of day)?\s*(&\s*lighting)?\s*:',
            r'art style\s*(&\s*mood)?\s*:',
            r'distinctive features\s*:',
            r'keywords\s*:',
            # Remove numbering patterns like "1.", "1)", "[1]", or "- "
            r'\b\d+\.\s*', 
            r'\b\d+\)\s*',
            r'\[\d+\]\s*',
            r'-\s*'
        ]
        
        clean_response = response
        for pat in remove_patterns:
            clean_response = re.sub(pat, '', clean_response, flags=re.IGNORECASE)
            
        # Split by comma
        raw_tags = [tag.strip() for tag in clean_response.split(',')]
        
        seen = set()
        tags = []
        
        for tag in raw_tags:
            tag_lower = tag.lower().strip()
            
            # Skip empty or weird tags
            if not tag_lower: continue
            if ':' in tag_lower: continue # Skip ignored categories
            
            # Skip tags that are JUST numbers (e.g. "12", "11")
            if tag_lower.isdigit(): continue
            
            # Skip single characters (unless it's something meaningful, but usually noise)
            if len(tag_lower) < 2: continue
            
            if tag_lower not in seen:
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
        """
        Comprehensive GPU memory cleanup following PyTorch best practices.
        """
        if self.model is not None:
            print("🧹 Unloading model and releasing GPU memory...")
            
            try:
                self.model = self.model.to('cpu')
            except:
                pass
            
            del self.model
            self.model = None
            
            if hasattr(self, 'processor') and self.processor is not None:
                del self.processor
            self.processor = None
            
            self.is_loaded = False
            
            import gc
            gc.collect()
            gc.collect()
            
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                try:
                    torch.cuda.ipc_collect()
                except:
                    pass
            
            print("[CLEANUP] Model unloaded")
